"""Local HTTP API. Run one worker so Blender operations are serialized."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from adapters.common import BLENDER, ROOT, CONFIG, list_files, get_result
from adapters.excel import export_excel
from adapters.blender import apply_vbom
from adapters.operators import (
    agent_status,
    ensure_agent,
    get_agent_job,
    list_operators,
    run_operator,
    stop_agent,
)

app = FastAPI(
    title="Excel and Blender Demo API",
    version="3.0.0",
    description="Independent Excel export and Blender apply adapters. Demo plugins, not company plugins.",
)


class ExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    excel_path: str
    output_dir: str = ""


class ApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    vbom_path: str
    model_path: str = ""
    open_window: bool = True


class OperatorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operator_id: str
    parameters: dict[str, object] = Field(default_factory=dict)
    model_path: str = ""
    wait_for_completion: bool = True


@app.exception_handler(ValueError)
async def invalid_input(request: Request, exc: ValueError):
    return JSONResponse(status_code=400, content={"ok": False, "error": str(exc)})


@app.exception_handler(FileNotFoundError)
async def missing_file(request: Request, exc: FileNotFoundError):
    return JSONResponse(status_code=404, content={"ok": False, "error": str(exc)})


@app.exception_handler(RuntimeError)
async def execution_error(request: Request, exc: RuntimeError):
    return JSONResponse(status_code=409, content={"ok": False, "error": str(exc)})


@app.exception_handler(Exception)
async def unexpected_error(request: Request, exc: Exception):
    return JSONResponse(status_code=500, content={"ok": False, "error": str(exc)})


@app.get("/health", tags=["System"])
def health():
    return {
        "ok": True,
        "service": "excel-blender-demo-api",
        "version": "3.0.0",
        "project_root": str(ROOT),
        "mode": CONFIG["mode"],
        "blender_available": BLENDER.is_file(),
        "blender_agent": agent_status(),
    }


@app.get("/files", tags=["Files"])
def files(input_dir: str = ""):
    return list_files(input_dir)


@app.post("/excel/export-vbom", tags=["Excel"])
def excel_export(body: ExportRequest):
    return export_excel(body.excel_path, body.output_dir)


@app.post("/blender/apply-vbom", tags=["Blender"])
def blender_apply(body: ApplyRequest):
    return apply_vbom(body.vbom_path, body.model_path, body.open_window)


@app.get("/blender/operators", tags=["Blender"])
def blender_operators():
    return list_operators()


@app.post("/blender/operators/run", tags=["Blender"])
def blender_operator_run(body: OperatorRequest):
    return run_operator(
        body.operator_id, body.parameters, body.model_path, body.wait_for_completion
    )


@app.get("/blender/agent", tags=["Blender Agent"])
def blender_agent_status():
    return agent_status()


@app.post("/blender/agent/start", tags=["Blender Agent"])
def blender_agent_start():
    return ensure_agent()


@app.post("/blender/agent/stop", tags=["Blender Agent"])
def blender_agent_stop():
    return stop_agent()


@app.get("/blender/jobs/{job_id}", tags=["Blender Agent"])
def blender_agent_job(job_id: str):
    return get_agent_job(job_id)


@app.get("/results/{run_id}", tags=["Results"])
def results(run_id: str):
    return get_result(run_id)
