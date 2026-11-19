"""Registry-controlled workflow for one generic Blender operator."""

import datetime
import hashlib
import threading
import uuid
from pathlib import Path

from adapters.blender import BlenderAdapter
from adapters.common import CONFIG, REGISTRY, log, write_json
from capability_discovery import validate_params
from project_config import data_path, scoped_path

_operator_workflow_lock = threading.Lock()


def _now():
    return datetime.datetime.now().astimezone().isoformat()


class _WorkflowFailure(RuntimeError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def run_blender_operator(capability_id, params, model_path, output_dir):
    model_path = scoped_path(CONFIG, model_path)
    output_dir = scoped_path(CONFIG, output_dir, data_path(CONFIG, "outputs"))
    if model_path.suffix.lower() != ".blend" or not model_path.is_file():
        raise ValueError("model_path must be an existing absolute .blend path")
    output_dir.mkdir(parents=True, exist_ok=True)
    if not _operator_workflow_lock.acquire(blocking=False):
        raise RuntimeError("The Blender operator workflow is already running")

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
            "capability_id": capability_id,
            "params": params,
            "model_path": str(model_path),
            "output_dir": str(output_dir),
        },
        "steps": [],
    }
    write_json(state_path, state)
    try:
        try:
            capability = REGISTRY.require(capability_id, provider="blender_operator")
            if capability.get("expose") != "generic":
                raise RuntimeError("Capability is not exposed through the generic workflow")
        except RuntimeError as exc:
            raise _WorkflowFailure("CAPABILITY_DISABLED", str(exc)) from exc
        try:
            normalized_params = validate_params(capability["params"], params, CONFIG)
        except ValueError as exc:
            raise _WorkflowFailure("PARAMS_INVALID", str(exc)) from exc

        state["current_step"] = "run_blender_operator"
        state["normalized_params"] = normalized_params
        write_json(state_path, state)
        output_path = run_directory / "result.blend"
        report_path = run_directory / "blender-operator-proof.json"
        try:
            result = BlenderAdapter().run_operator(
                capability,
                normalized_params,
                model_path,
                output_path,
                report_path,
                run_id,
            )
        except Exception as exc:
            raise _WorkflowFailure("BLENDER_EXECUTION_FAILED", str(exc)) from exc
        state["steps"].append(
            {"id": state["current_step"], "status": "completed", "result": result}
        )
        verification = {
            "ok": True,
            "run_id": run_id,
            "capability_id": capability_id,
            "operator": capability["target"],
            "transport": result["transport"],
            "output_sha256": hashlib.sha256(output_path.read_bytes()).hexdigest(),
            "verified_after_reopen": result["verified_after_reopen"],
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
                "blender": str(report_path),
                "verification": str(verification_path),
            },
        )
    except _WorkflowFailure as exc:
        failed_step = state.get("current_step") or "validate_capability"
        state["steps"].append(
            {"id": failed_step, "status": "failed", "error": str(exc)}
        )
        state.update(
            ok=False,
            status="failed",
            current_step=None,
            failed_step=failed_step,
            error_code=exc.code,
            error=str(exc),
            finished_at=_now(),
        )
    finally:
        write_json(state_path, state)
        _operator_workflow_lock.release()
    log("run_blender_operator", {"arguments": state["input"], "result": state})
    return state
