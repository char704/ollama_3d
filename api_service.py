"""Local diagnostics and MCP transport for the real proof workflow."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from adapters.common import BLENDER, CONFIG, ROOT
from mcp_server import mcp_http_app
from workflows.mcp_workflow import run_excel_to_blender, system_status


@asynccontextmanager
async def lifespan(_app):
    async with mcp_http_app.router.lifespan_context(mcp_http_app):
        yield


app = FastAPI(
    title="Ollama3D MCP",
    version="5.0.0",
    description="Local MCP transport for real Excel VBA and Blender add-on automation.",
    lifespan=lifespan,
)


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    excel_path: str
    model_path: str
    output_dir: str


@app.exception_handler(ValueError)
async def invalid_input(_request: Request, exc: ValueError):
    return JSONResponse(status_code=400, content={"ok": False, "error": str(exc)})


@app.exception_handler(FileNotFoundError)
async def missing_file(_request: Request, exc: FileNotFoundError):
    return JSONResponse(status_code=404, content={"ok": False, "error": str(exc)})


@app.exception_handler(RuntimeError)
async def execution_error(_request: Request, exc: RuntimeError):
    return JSONResponse(status_code=409, content={"ok": False, "error": str(exc)})


@app.get("/health", tags=["System"])
def health():
    return {
        "ok": True,
        "service": "ollama3d-local-api",
        "version": "5.0.0",
        "project_root": str(ROOT),
        "profile": CONFIG["profile"],
        "blender_available": BLENDER.is_file(),
    }


@app.get("/proof/status", tags=["Diagnostics"])
def proof_status():
    return system_status()


@app.post("/proof/run", tags=["Diagnostics"])
def proof_run(body: RunRequest):
    return run_excel_to_blender(body.excel_path, body.model_path, body.output_dir)


# MCP owns /mcp; REST endpoints above exist only for local diagnostics.
app.mount("/", mcp_http_app)
