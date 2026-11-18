"""Local MCP surface. Business logic lives in workflows.mcp_workflow."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer

from workflows.mcp_workflow import run_excel_to_blender as execute_workflow
from workflows.mcp_workflow import system_status as read_system_status

AUDIT_LOG = Path(__file__).resolve().parent / "logs" / "mcp-tool-calls.jsonl"


def _audit(tool: str, arguments: dict[str, Any], result: dict[str, Any]) -> None:
    """Persist compact evidence that the MCP tool itself was invoked."""
    AUDIT_LOG.parent.mkdir(exist_ok=True)
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tool": tool,
        "arguments": arguments,
        "result": {
            key: result.get(key)
            for key in ("ready", "status", "run_id", "output_path")
            if key in result
        },
    }
    with AUDIT_LOG.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + "\n")


mcp = MCPServer(
    "ollama3d",
    title="Ollama3D Excel and Blender",
    version="1.0.0",
    instructions=(
        "Use system_status only for readiness or version questions. "
        "Use run_excel_to_blender only when the user explicitly requests processing and provides "
        "an absolute .xlsx path, an absolute .blend path, and an absolute output directory. "
        "Never invent paths and never report success unless status is completed."
    ),
)


@mcp.tool(structured_output=True)
def system_status() -> dict[str, Any]:
    """Check the real local Qwen model, Excel VBA add-in, and Blender add-on. This tool does not process user files."""
    result = read_system_status()
    _audit("system_status", {}, result)
    return result


@mcp.tool(structured_output=True)
def run_excel_to_blender(
    excel_path: str, model_path: str, output_dir: str
) -> dict[str, Any]:
    """Run the real Excel VBA to VBOM to Blender add-on workflow. Use only for an explicit processing request with all three absolute paths. Do not use for explanations or status questions."""
    arguments = {
        "excel_path": excel_path,
        "model_path": model_path,
        "output_dir": output_dir,
    }
    result = execute_workflow(**arguments)
    _audit("run_excel_to_blender", arguments, result)
    return result


mcp_http_app = mcp.streamable_http_app(
    streamable_http_path="/mcp",
    stateless_http=True,
    json_response=True,
    host="127.0.0.1",
)
