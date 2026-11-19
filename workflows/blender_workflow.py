"""Execute an allowlisted declarative Blender workflow in one Blender session."""

import datetime
import hashlib
import threading
import uuid
from pathlib import Path

from adapters.blender_mcp import BlenderMcpAdapter
from adapters.common import CONFIG, REGISTRY, ROOT, log, write_json
from capability_discovery import validate_params
from project_config import data_path, scoped_path
from workflow_definitions import interpolate_definition, load_definition

_workflow_lock = threading.Lock()
DEFINITIONS = ROOT / "workflows" / "definitions"


def _now():
    return datetime.datetime.now().astimezone().isoformat()


def run_blender_workflow(workflow_id, inputs):
    definition = load_definition(DEFINITIONS, workflow_id)
    normalized_inputs = dict(inputs)
    for name, kind in definition["inputs"].items():
        if kind == "path" and name in normalized_inputs:
            normalized_inputs[name] = str(scoped_path(CONFIG, normalized_inputs[name]))
    definition = interpolate_definition(definition, normalized_inputs)
    if "model_path" not in normalized_inputs or "output_dir" not in normalized_inputs:
        raise ValueError("Workflow inputs must include model_path and output_dir")
    model_path = Path(normalized_inputs["model_path"])
    output_dir = Path(normalized_inputs["output_dir"] or data_path(CONFIG, "outputs"))
    if model_path.suffix.lower() != ".blend" or not model_path.is_file():
        raise ValueError("model_path must be an existing scoped .blend file")
    output_dir.mkdir(parents=True, exist_ok=True)

    resolved_steps = []
    for step in definition["steps"]:
        capability = REGISTRY.require(step["capability"], provider="blender_operator")
        params = validate_params(capability["params"], step.get("params", {}), CONFIG)
        resolved_steps.append({"id": step["id"], "capability": capability, "params": params})

    if not _workflow_lock.acquire(blocking=False):
        raise RuntimeError("A declarative Blender workflow is already running")
    run_id = uuid.uuid4().hex
    run_directory = output_dir / run_id
    run_directory.mkdir()
    state_path = run_directory / "workflow.json"
    state = {
        "ok": True,
        "status": "running",
        "workflow_id": workflow_id,
        "run_id": run_id,
        "created_at": _now(),
        "input": normalized_inputs,
        "steps": [],
    }
    write_json(state_path, state)
    try:
        output_path = run_directory / "result.blend"
        report_path = run_directory / "blender-workflow-proof.json"
        result = BlenderMcpAdapter().run_workflow(
            workflow_id,
            resolved_steps,
            definition.get("postconditions", []),
            model_path,
            output_path,
            report_path,
            run_id,
        )
        state["steps"] = [
            {"id": item["id"], "status": "completed", "result": item}
            for item in result["steps"]
        ]
        verification_path = run_directory / "verification.json"
        write_json(
            verification_path,
            {
                "ok": True,
                "workflow_id": workflow_id,
                "run_id": run_id,
                "output_sha256": hashlib.sha256(output_path.read_bytes()).hexdigest(),
                "verified_after_reopen": result["verified_after_reopen"],
                "transport": result["transport"],
            },
        )
        state.update(
            ok=True,
            status="completed",
            finished_at=_now(),
            output_path=str(output_path),
            evidence={"blender": str(report_path), "verification": str(verification_path)},
        )
    except Exception as exc:
        state.update(
            ok=False,
            status="failed",
            error_code="BLENDER_EXECUTION_FAILED",
            error=str(exc),
            finished_at=_now(),
        )
    finally:
        write_json(state_path, state)
        _workflow_lock.release()
    log("run_blender_workflow", {"arguments": normalized_inputs, "result": state})
    return state
