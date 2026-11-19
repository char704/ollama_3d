"""Local OpenAI-compatible REST backend for the deterministic Ollama3D agent."""

import json
import time
import uuid
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict

from adapters.common import BLENDER, CONFIG, ROOT
from agent.run import handle
from workflows.folder_workflow import process_folder
from workflows.core_workflow import run_excel_to_blender, system_status

MODEL_ID = "ollama3d-direct"
LOCAL_API_KEY = "ollama3d-local"

app = FastAPI(
    title="Ollama3D Direct Agent",
    version="6.0.0",
    description="Local REST agent backed by Ollama, Excel COM/VBA, and Blender subprocess jobs.",
)


class ChatMessage(BaseModel):
    role: str
    content: Any


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    model: str
    messages: list[ChatMessage]
    stream: bool = False


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    excel_path: str
    model_path: str
    output_dir: str


class FolderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input_dir: str = "inputs"
    output_dir: str = "outputs"


def require_local_key(authorization: str | None = Header(default=None)):
    if authorization != f"Bearer {LOCAL_API_KEY}":
        raise HTTPException(status_code=401, detail="Invalid local API key")


def _message_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            item.get("text", "")
            for item in content
            if isinstance(item, dict) and item.get("type") in ("text", "input_text")
        )
    return str(content or "")


def _latest_user_message(messages):
    for message in reversed(messages):
        if message.role == "user":
            text = _message_text(message.content).strip()
            if text:
                return text
    raise ValueError("A non-empty user message is required")


def _chat_payload(content, completion_id, created):
    return {
        "id": completion_id,
        "object": "chat.completion",
        "created": created,
        "model": MODEL_ID,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


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
        "version": "6.0.0",
        "project_root": str(ROOT),
        "profile": CONFIG["profile"],
        "blender_available": BLENDER.is_file(),
        "transport": "rest-direct",
    }


@app.get("/v1/models", dependencies=[Depends(require_local_key)])
def models():
    return {
        "object": "list",
        "data": [
            {
                "id": MODEL_ID,
                "object": "model",
                "created": 0,
                "owned_by": "ollama3d-local",
            }
        ],
    }


@app.post("/v1/chat/completions", dependencies=[Depends(require_local_key)])
def chat_completions(body: ChatRequest):
    if body.model != MODEL_ID:
        raise HTTPException(status_code=404, detail="Unknown model")
    result = handle(_latest_user_message(body.messages))
    content = result.get("message") or json.dumps(result, ensure_ascii=False)
    completion_id = "chatcmpl-" + uuid.uuid4().hex
    created = int(time.time())
    if not body.stream:
        return _chat_payload(content, completion_id, created)

    def events():
        chunk = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": MODEL_ID,
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant", "content": content},
                    "finish_reason": None,
                }
            ],
        }
        yield "data: " + json.dumps(chunk, ensure_ascii=False) + "\n\n"
        chunk["choices"][0] = {"index": 0, "delta": {}, "finish_reason": "stop"}
        yield "data: " + json.dumps(chunk, ensure_ascii=False) + "\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")


@app.get("/proof/status", tags=["Diagnostics"])
def proof_status():
    return system_status()


@app.post("/proof/run", tags=["Diagnostics"])
def proof_run(body: RunRequest):
    return run_excel_to_blender(body.excel_path, body.model_path, body.output_dir)


@app.post("/proof/process-folder", tags=["Diagnostics"])
def proof_process_folder(body: FolderRequest):
    return process_folder(body.input_dir, body.output_dir)
