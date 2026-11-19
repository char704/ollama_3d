"""Proof workflow used by both MCP and the local HTTP diagnostic endpoint."""

import datetime
import hashlib
import json
import re
import threading
import uuid
from pathlib import Path

import httpx

from adapters.blender import BlenderAdapter
from adapters.common import CONFIG, REGISTRY, ROOT, log, write_json
from adapters.excel_vba import ExcelVbaAdapter
from project_config import data_path, scoped_path, service_url

_workflow_lock = threading.Lock()


def _now():
    return datetime.datetime.now().astimezone().isoformat()


def _failure(code, message):
    return {"ok": False, "error_code": code, "error": message}


def system_status():
    REGISTRY.require("system.status", provider="system", handler="system_status")
    probe_directory = ROOT / "runtime" / "probes"
    probe_directory.mkdir(parents=True, exist_ok=True)
    status = {
        "ok": True,
        "ready": False,
        "service": {
            "mcp_path": CONFIG["mcp"]["path"],
            "profile": CONFIG["profile"],
            "registry": REGISTRY.summary(),
        },
    }
    try:
        response = httpx.get(service_url(CONFIG, "ollama") + "/api/tags", timeout=10, trust_env=False)
        response.raise_for_status()
        names = {item["name"] for item in response.json().get("models", [])}
        model = CONFIG["ollama"]["model"]
        status["qwen"] = {"model": model, "available": model in names or model + ":latest" in names}
    except Exception as exc:
        status["qwen"] = {"model": CONFIG["ollama"]["model"], "available": False, "error": str(exc)}
    try:
        status["excel"] = ExcelVbaAdapter().status()
    except Exception as exc:
        status["excel"] = _failure("EXCEL_NOT_READY", str(exc))
    try:
        status["blender"] = BlenderAdapter().status(probe_directory)
    except Exception as exc:
        status["blender"] = _failure("BLENDER_NOT_READY", str(exc))
    status["ready"] = bool(
        status["qwen"].get("available")
        and status["excel"].get("macro_callable")
        and status["blender"].get("operator_callable")
        and status["blender"].get("transport_callable")
    )
    status["ok"] = status["ready"]
    log("mcp_system_status", {"result": status})
    return status


def run_excel_to_blender(excel_path, model_path, output_dir):
    REGISTRY.require(
        "workflow.excel_to_blender", provider="workflow", handler="run_excel_to_blender"
    )
    excel_path = scoped_path(CONFIG, excel_path)
    model_path = scoped_path(CONFIG, model_path)
    output_dir = scoped_path(CONFIG, output_dir, data_path(CONFIG, "outputs"))
    if not excel_path.is_absolute() or excel_path.suffix.lower() != ".xlsx" or not excel_path.is_file():
        raise ValueError("excel_path must be an existing absolute .xlsx path")
    if not model_path.is_absolute() or model_path.suffix.lower() != ".blend" or not model_path.is_file():
        raise ValueError("model_path must be an existing absolute .blend path")
    output_dir.mkdir(parents=True, exist_ok=True)
    if not _workflow_lock.acquire(blocking=False):
        raise RuntimeError("The Excel-to-Blender workflow is already running")
    run_id = uuid.uuid4().hex
    run_directory = output_dir / run_id
    run_directory.mkdir()
    state_path = run_directory / "workflow.json"
    state = {
        "ok": True,
        "status": "running",
        "run_id": run_id,
        "created_at": _now(),
        "input": {
            "excel_path": str(excel_path),
            "model_path": str(model_path),
            "output_dir": str(output_dir),
        },
        "steps": [],
    }
    write_json(state_path, state)
    try:
        state["current_step"] = "export_vbom_with_vba"
        write_json(state_path, state)
        exported = ExcelVbaAdapter().export(excel_path, run_directory, run_id)
        state["steps"].append({"id": state["current_step"], "status": "completed", "result": exported})
        write_json(state_path, state)

        state["current_step"] = "apply_vbom_with_addon"
        write_json(state_path, state)
        output_path = run_directory / "result.blend"
        blender_proof = run_directory / "blender-proof.json"
        applied = BlenderAdapter().apply(
            exported["vbom_path"], model_path, output_path, blender_proof, run_id
        )
        state["steps"].append({"id": state["current_step"], "status": "completed", "result": applied})
        verification = {
            "ok": True,
            "run_id": run_id,
            "excel_producer": exported["producer"],
            "blender_producer": applied["producer"],
            "blender_transport": applied["transport"],
            "source_sha256": exported["source_sha256"],
            "vbom_sha256": exported["vbom_sha256"],
            "output_sha256": hashlib.sha256(output_path.read_bytes()).hexdigest(),
            "verified_after_reopen": applied["verified_after_reopen"],
        }
        verification_path = run_directory / "verification.json"
        write_json(verification_path, verification)
        state.update(
            ok=True,
            status="completed",
            current_step=None,
            finished_at=_now(),
            output_path=str(output_path),
            evidence={
                "excel": exported["proof_path"],
                "blender": str(blender_proof),
                "verification": str(verification_path),
            },
        )
    except Exception as exc:
        failed_step = state.get("current_step")
        state["steps"].append({"id": failed_step, "status": "failed", "error": str(exc)})
        state.update(
            ok=False,
            status="failed",
            current_step=None,
            failed_step=failed_step,
            error_code="EXCEL_EXECUTION_FAILED" if failed_step == "export_vbom_with_vba" else "BLENDER_EXECUTION_FAILED",
            error=str(exc),
            finished_at=_now(),
        )
    finally:
        write_json(state_path, state)
        _workflow_lock.release()
    log("mcp_run_excel_to_blender", {"arguments": state["input"], "result": state})
    return state


def create_colored_primitive(primitive, color_hex, output_dir, size=2.0, object_name="QwenPrimitive"):
    capability = REGISTRY.require(
        "blender.create_colored_primitive",
        provider="blender_builtin",
        handler="create_colored_primitive",
    )
    settings = capability["settings"]
    allowed = settings["primitives"]
    if primitive not in allowed:
        raise ValueError("primitive must be one of: " + ", ".join(allowed))
    if not isinstance(color_hex, str) or not re.fullmatch(r"#[0-9A-Fa-f]{6}", color_hex):
        raise ValueError("color_hex must use the #RRGGBB format")
    color_hex = color_hex.upper()
    minimum = settings["minimum_size"]
    maximum = settings["maximum_size"]
    if isinstance(size, bool) or not isinstance(size, (int, float)) or not minimum <= size <= maximum:
        raise ValueError(f"size must be a number from {minimum} through {maximum}")
    if not isinstance(object_name, str) or not re.fullmatch(r"[A-Za-z0-9 _.-]{1,64}", object_name):
        raise ValueError("object_name may contain letters, numbers, spaces, dot, dash, and underscore")

    output_dir = scoped_path(CONFIG, output_dir, data_path(CONFIG, "outputs"))
    output_dir.mkdir(parents=True, exist_ok=True)
    run_id = uuid.uuid4().hex
    run_directory = output_dir / run_id
    run_directory.mkdir()
    output_path = run_directory / f"{primitive}.blend"
    report_path = run_directory / "primitive-proof.json"
    result = BlenderAdapter().create_colored_primitive(
        primitive,
        color_hex,
        float(size),
        object_name,
        output_path,
        report_path,
        run_id,
    )
    log(
        "mcp_create_colored_primitive",
        {
            "arguments": {
                "primitive": primitive,
                "color_hex": color_hex,
                "output_dir": str(output_dir),
                "size": float(size),
                "object_name": object_name,
            },
            "result": result,
        },
    )
    return result
