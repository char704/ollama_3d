"""Fixed Blender subprocess entry point for trusted Ollama3D jobs."""

import json
import sys
import traceback
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lab_mcp_runner import (
    apply_vbom,
    create_colored_primitive,
    discover,
    run_operator,
    run_steps,
    status,
)

OPERATIONS = {
    "apply_vbom": apply_vbom,
    "create_colored_primitive": create_colored_primitive,
    "discover": discover,
    "run_operator": run_operator,
    "run_steps": run_steps,
    "status": status,
}


def main():
    arguments = sys.argv[sys.argv.index("--") + 1 :]
    if len(arguments) != 2:
        raise RuntimeError("job_entry.py requires job.json and result.json")
    job_path, result_path = arguments
    try:
        with open(job_path, encoding="utf-8-sig") as stream:
            job = json.load(stream)
        operation = job.get("operation")
        if operation not in OPERATIONS:
            raise ValueError("Unsupported Blender job operation: " + str(operation))
        payload = job.get("payload")
        if not isinstance(payload, dict):
            raise ValueError("Blender job payload must be an object")
        payload.setdefault("transport", "blender-subprocess")
        result = {
            "ok": True,
            "operation": operation,
            "blender_version": bpy.app.version_string,
            "result": OPERATIONS[operation](payload),
        }
    except Exception as exc:
        result = {
            "ok": False,
            "blender_version": bpy.app.version_string,
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }
    with open(result_path, "w", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    if not result["ok"]:
        raise RuntimeError(result["error"])


if __name__ == "__main__":
    main()
