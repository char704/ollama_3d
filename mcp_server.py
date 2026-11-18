"""Local MCP surface. Business logic lives in workflows.mcp_workflow."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from mcp.server.mcpserver import MCPServer
from adapters.common import REGISTRY

from workflows.mcp_workflow import run_excel_to_blender as execute_workflow
from workflows.mcp_workflow import create_colored_primitive as execute_primitive
from workflows.mcp_workflow import system_status as read_system_status

AUDIT_LOG = Path(__file__).resolve().parent / "logs" / "mcp-tool-calls.jsonl"
PUBLIC_TOOLS = REGISTRY.public_tools()
_IMPLEMENTED_TOOLS = ["system_status", "run_excel_to_blender", "create_colored_primitive"]
if PUBLIC_TOOLS != _IMPLEMENTED_TOOLS:
    raise RuntimeError(
        "Enabled registry tools do not match MCP implementations: "
        f"registry={PUBLIC_TOOLS}, implemented={_IMPLEMENTED_TOOLS}"
    )


def _audit(tool: str, arguments: dict[str, Any], result: dict[str, Any]) -> None:
    """Persist compact evidence that the MCP tool itself was invoked."""
    AUDIT_LOG.parent.mkdir(exist_ok=True)
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tool": tool,
        "arguments": arguments,
        "result": {
            key: result.get(key)
            for key in ("ready", "status", "run_id", "output_path", "primitive", "color_hex")
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
        "Use create_colored_primitive only when the user explicitly asks to create a cube, "
        "UV sphere, or cylinder and provides an absolute output directory. "
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


@mcp.tool(structured_output=True)
def create_colored_primitive(
    primitive: Literal["cube", "uv_sphere", "cylinder"],
    color_hex: str,
    output_dir: str,
    size: float = 2.0,
    object_name: str = "QwenPrimitive",
) -> dict[str, Any]:
    """Create one colored Blender primitive through official Blender MCP, save it, reopen it, and verify it. Use only for an explicit request with an absolute output directory. color_hex must be #RRGGBB."""
    arguments = {
        "primitive": primitive,
        "color_hex": color_hex,
        "output_dir": output_dir,
        "size": size,
        "object_name": object_name,
    }
    result = execute_primitive(**arguments)
    _audit("create_colored_primitive", arguments, result)
    return result


mcp_http_app = mcp.streamable_http_app(
    streamable_http_path="/mcp",
    stateless_http=True,
    json_response=True,
    host="127.0.0.1",
)
