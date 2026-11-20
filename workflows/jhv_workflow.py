"""JHV workbook-to-VBOM / Article workflow (separate from proof workflow)."""
from __future__ import annotations

import datetime
import threading
import uuid

from adapters.common import CONFIG, REGISTRY, log, write_json
from adapters.jhv_vbom import JHVBomExporter
from project_config import data_path, scoped_path
from workflows.operator_workflow import run_blender_operator

_lock = threading.Lock()
CAP_ID = "blender.jhv_dpc.run_dpc_automation"


def apply_jhv_vbom(vbom_path, model_path, output_dir):
    vbom = scoped_path(CONFIG, vbom_path)
    if vbom.suffix.casefold() != ".vbom" or not vbom.is_file():
        raise ValueError("vbom_path must be an existing .vbom in the allowed directories")
    capability = REGISTRY.require(CAP_ID, provider="blender_operator")
    if capability["target"] != "jhv.run_dpc_automation" or not capability.get("background_safe"):
        raise RuntimeError("JHV automation operator is not background-safe or has changed")
    result = run_blender_operator(CAP_ID, {"vbom_path": str(vbom)}, model_path, output_dir)
    return {**result, "vbom_path": str(vbom)}


def execute_jhv(excel_path, output_dir, model_path=None, sheet_name=""):
    """Return state and evidence; never overwrite inputs or invoke unlisted operators."""
    full = model_path is not None
    REGISTRY.require("workflow.jhv_excel_to_articles" if full else "workflow.jhv_export_vbom",
                     provider="workflow")
    excel = scoped_path(CONFIG, excel_path)
    out = scoped_path(CONFIG, output_dir, data_path(CONFIG, "outputs"))
    model = scoped_path(CONFIG, model_path) if full else None
    if full and (model.suffix.casefold() != ".blend" or not model.is_file()):
        raise ValueError("model_path must be an existing .blend in the allowed directories")
    if not _lock.acquire(blocking=False):
        raise RuntimeError("JHV workflow is already running")
    try:
        run_id = uuid.uuid4().hex
        run_dir = out / "jhv" / run_id
        run_dir.mkdir(parents=True, exist_ok=False)
        state_path = run_dir / "workflow.json"
        state = {"status": "running", "ok": False, "run_id": run_id,
                 "excel_path": str(excel), "model_path": str(model) if full else None,
                 "created_at": datetime.datetime.now().astimezone().isoformat(), "steps": []}
        write_json(state_path, state)
        try:
            state["current_step"] = "jhv_export_vbom"
            write_json(state_path, state)
            vbom = JHVBomExporter().export(excel, run_dir / "materials.vbom", sheet_name)
            state["vbom_path"] = vbom["vbom_path"]
            state["steps"].append({"id": "jhv_export_vbom", "status": "completed", "result": vbom})
            if full:
                state["current_step"] = "jhv_generate_articles"
                write_json(state_path, state)
                applied = apply_jhv_vbom(vbom["vbom_path"], model, run_dir)
                state["steps"].append({"id": "jhv_generate_articles", "status": applied["status"], "result": applied})
                for key in ("output_path", "evidence", "warnings", "articles", "error", "error_code", "details"):
                    if key in applied:
                        state[key] = applied[key]
                state.update(status=applied["status"], ok=applied["ok"])
                if not applied["ok"]:
                    state["failed_step"] = state["current_step"]
            else:
                state["output_path"] = vbom["vbom_path"]
                state.update(status="completed", ok=True)
            state["current_step"] = None
        except Exception as exc:
            failed_step = state.get("current_step")
            state.update(
                status="failed", ok=False, error=str(exc), failed_step=failed_step, current_step=None,
                error_code="VBOM_EXPORT_FAILED" if failed_step == "jhv_export_vbom" else "JHV_EXECUTION_FAILED",
            )
        finally:
            state["finished_at"] = datetime.datetime.now().astimezone().isoformat()
            write_json(state_path, state)
            log("jhv_excel_workflow", {"run_id": run_id, "result": state})
        return state
    finally:
        _lock.release()
