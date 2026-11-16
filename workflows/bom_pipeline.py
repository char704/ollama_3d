"""Deterministic Excel -> VBOM -> Blender workflow with persisted step state."""

import datetime
import hashlib
import json
import os
import re
import threading
import uuid
from pathlib import Path

import httpx

from adapters.blender import apply_vbom
from adapters.common import (
    CONFIG,
    DEFAULT_MODEL,
    INPUTS,
    ROOT,
    RUNS,
    log,
    read_json,
    write_json,
)
from adapters.excel import export_excel
from project_config import endpoint

WORKFLOW_ROOT = ROOT / "runtime" / "workflows"
_workflow_lock = threading.Lock()


def _now():
    return datetime.datetime.now().astimezone().isoformat()


def _job_path(job_id):
    if not isinstance(job_id, str) or not re.fullmatch(r"[a-f0-9]{32}", job_id):
        raise ValueError("Invalid workflow job_id")
    return WORKFLOW_ROOT / (job_id + ".json")


def get_bom_pipeline_job(job_id):
    path = _job_path(job_id)
    if not path.is_file():
        raise FileNotFoundError("Workflow job not found")
    return read_json(path)


def _save(job, **updates):
    job.update(updates, updated_at=_now())
    write_json(_job_path(job["job_id"]), job)
    return job


def _file_identity(value):
    path = Path(value)
    identity = {"path": str(path.resolve())}
    if path.is_file():
        stat = path.stat()
        identity.update(size=stat.st_size, modified_ns=stat.st_mtime_ns)
    return identity


def _idempotency_key(excel_path, model_path, output_dir, open_result):
    value = {
        "workflow_id": "excel_to_blender",
        "excel": _file_identity(excel_path),
        "model": _file_identity(model_path),
        "output_dir": str(Path(output_dir).resolve()),
        "open_result": bool(open_result),
    }
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _existing_job(key):
    pointer = WORKFLOW_ROOT / "idempotency" / (key + ".json")
    if not pointer.is_file():
        return None
    try:
        job = get_bom_pipeline_job(read_json(pointer)["job_id"])
    except (FileNotFoundError, KeyError, ValueError):
        pointer.unlink(missing_ok=True)
        return None
    if job.get("status") in (
        "queued",
        "running",
        "exporting",
        "applying",
        "verifying",
        "completed",
    ):
        return {**job, "reused_job": True}
    return None


def _http_operation(operation, body):
    target = endpoint(CONFIG, operation)
    headers = {}
    token_env = target.get("token_env", "")
    if token_env:
        token = os.environ.get(token_env)
        if not token:
            raise RuntimeError("Missing environment variable: " + token_env)
        headers["Authorization"] = "Bearer " + token
    with httpx.Client(timeout=210, trust_env=False, follow_redirects=False) as client:
        response = client.post(target["url"], json=body, headers=headers)
    try:
        result = response.json()
    except ValueError as exc:
        raise RuntimeError(f"{operation} provider returned invalid JSON") from exc
    if response.is_error or response.is_redirect:
        detail = (
            result.get("error", result.get("detail", result))
            if isinstance(result, dict)
            else result
        )
        raise RuntimeError(f"{operation} provider failed: {detail}")
    if not isinstance(result, dict) or not result.get("ok"):
        raise RuntimeError(f"{operation} provider did not return ok=true")
    return result


def _export(excel_path, output_dir):
    if CONFIG["workflow"]["export"]["provider"] == "local":
        return export_excel(excel_path, output_dir)
    return _http_operation(
        "export", {"excel_path": excel_path, "output_dir": output_dir}
    )


def _apply(vbom_path, model_path, open_result):
    if CONFIG["workflow"]["apply"]["provider"] == "local":
        return apply_vbom(vbom_path, model_path, open_result)
    return _http_operation(
        "apply",
        {
            "vbom_path": vbom_path,
            "model_path": model_path,
            "open_window": open_result,
        },
    )


def run_bom_pipeline(
    excel_path, model_path="", output_dir="", open_result=True, force_new=False
):
    excel_path = str(excel_path)
    if (
        CONFIG["workflow"]["export"]["provider"] == "local"
        and "/" not in excel_path
        and "\\" not in excel_path
    ):
        excel_path = str(INPUTS / excel_path)
    model_path = str(model_path or DEFAULT_MODEL)
    output_dir = str(output_dir or RUNS)
    key = _idempotency_key(excel_path, model_path, output_dir, open_result)
    with _workflow_lock:
        if not force_new:
            existing = _existing_job(key)
            if existing:
                log(
                    "run_bom_pipeline",
                    {
                        "arguments": {
                            "excel_path": excel_path,
                            "model_path": model_path,
                            "output_dir": output_dir,
                            "open_result": bool(open_result),
                            "force_new": False,
                        },
                        "result": existing,
                    },
                )
                return existing
        job_id = uuid.uuid4().hex
        job = {
            "ok": True,
            "job_id": job_id,
            "workflow_id": "excel_to_blender",
            "status": "queued",
            "created_at": _now(),
            "current_step": None,
            "idempotency_key": key,
            "input": {
                "excel_path": excel_path,
                "model_path": model_path,
                "output_dir": output_dir,
                "open_result": bool(open_result),
                "force_new": bool(force_new),
            },
            "steps": [],
        }
        _save(job)
        write_json(WORKFLOW_ROOT / "idempotency" / (key + ".json"), {"job_id": job_id})
    try:
        _save(job, status="exporting", current_step="export_vbom", started_at=_now())
        exported = _export(excel_path, output_dir)
        if not exported.get("vbom_path"):
            raise RuntimeError("Export provider did not return vbom_path")
        job["steps"].append(
            {"id": "export_vbom", "status": "completed", "result": exported}
        )
        _save(job, status="applying", current_step="apply_and_verify")
        applied = _apply(exported["vbom_path"], model_path, bool(open_result))
        if applied.get("status") != "completed":
            raise RuntimeError("Apply provider did not return status=completed")
        job["steps"].append(
            {"id": "apply_and_verify", "status": "completed", "result": applied}
        )
        output_path = applied.get("output") or applied.get("output_path")
        _save(
            job,
            ok=True,
            status="completed",
            current_step=None,
            finished_at=_now(),
            run_id=exported.get("run_id"),
            output={
                "vbom_path": exported["vbom_path"],
                "model_path": output_path,
                "preview": applied.get("preview"),
            },
        )
    except Exception as exc:
        job["steps"].append(
            {"id": job.get("current_step"), "status": "failed", "error": str(exc)}
        )
        _save(
            job,
            ok=False,
            status="failed",
            finished_at=_now(),
            error=str(exc),
        )
    log("run_bom_pipeline", {"arguments": job["input"], "result": job})
    return job
