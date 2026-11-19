"""Local MCP surface. Business logic lives in workflows.mcp_workflow."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from mcp.server.mcpserver import MCPServer
from adapters.common import REGISTRY, ROOT

from workflows.mcp_workflow import run_excel_to_blender as execute_workflow
from workflows.mcp_workflow import create_colored_primitive as execute_primitive
from workflows.mcp_workflow import system_status as read_system_status
from workflows.operator_workflow import run_blender_operator as execute_operator
from workflows.blender_workflow import run_blender_workflow as execute_blender_workflow

AUDIT_LOG = Path(__file__).resolve().parent / "logs" / "mcp-tool-calls.jsonl"
PUBLIC_TOOLS = REGISTRY.public_tools()
_registered = set()


def _audit(tool: str, arguments: dict[str, Any], result: dict[str, Any]) -> None:
    """Persist compact evidence that the MCP tool itself was invoked."""
    AUDIT_LOG.parent.mkdir(exist_ok=True)
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tool": tool,
        "arguments": arguments,
        "result": {
            key: result.get(key)
            for key in (
                "ready",
                "status",
                "run_id",
                "output_path",
                "primitive",
                "color_hex",
                "count",
            )
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
        "Use list_blender_capabilities to inspect allowlisted add-on operations. "
        "Use run_blender_operator only with a listed capability id, valid parameters, and absolute paths. "
        "Never invent paths and never report success unless status is completed."
    ),
)


def _public_tool(fn):
    registered = mcp.tool(structured_output=True)(fn)
    _registered.add(fn.__name__)
    return registered


@_public_tool
def system_status() -> dict[str, Any]:
    """Check the real local Qwen model, Excel VBA add-in, and Blender add-on. This tool does not process user files."""
    result = read_system_status()
    _audit("system_status", {}, result)
    return result


@_public_tool
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


@_public_tool
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


def _docs(capability: dict[str, Any]) -> tuple[str, str]:
    relative = capability.get("docs")
    if not relative:
        return "", ""
    path = (ROOT / relative).resolve()
    knowledge = (ROOT / "knowledge").resolve()
    if not path.is_relative_to(knowledge) or not path.is_file():
        return "", ""
    content = path.read_text(encoding="utf-8-sig")
    title = next(
        (line.lstrip("#").strip() for line in content.splitlines() if line.startswith("#")),
        "",
    )
    return title, content[:1500]


@_public_tool
def list_blender_capabilities(query: str = "") -> dict[str, Any]:
    """List enabled allowlisted Blender add-on operations. Use when the user asks what an add-on can do. Never invent a capability id."""
    query_text = query.strip().casefold()
    matches = []
    for capability in REGISTRY.generic_capabilities():
        title, excerpt = _docs(capability)
        searchable = " ".join(
            (capability["id"], capability.get("description", ""), title)
        ).casefold()
        if query_text and query_text not in searchable:
            continue
        matches.append(
            {
                "id": capability["id"],
                "description": capability.get("description", ""),
                "risk": capability["risk"],
                "params": capability["params"],
                "docs_excerpt": excerpt,
                "background_safe": capability.get("background_safe", False),
            }
        )
        if len(matches) == 10:
            break
    result = {"ok": True, "query": query, "count": len(matches), "capabilities": matches}
    _audit("list_blender_capabilities", {"query": query}, result)
    return result


@_public_tool
def run_blender_operator(
    capability_id: str,
    params: dict[str, Any],
    model_path: str,
    output_dir: str,
) -> dict[str, Any]:
    """Run one listed Blender capability. Use only for an explicit request with valid params and absolute model_path and output_dir. Never invent paths or capability ids."""
    arguments = {
        "capability_id": capability_id,
        "params": params,
        "model_path": model_path,
        "output_dir": output_dir,
    }
    result = execute_operator(**arguments)
    _audit("run_blender_operator", arguments, result)
    return result


@_public_tool
def run_blender_workflow(workflow_id: str, inputs: dict[str, Any]) -> dict[str, Any]:
    """Run one registered declarative Blender workflow. Use only with a known workflow_id and complete inputs. Never invent workflow ids or interpolation expressions."""
    arguments = {"workflow_id": workflow_id, "inputs": inputs}
    result = execute_blender_workflow(**arguments)
    _audit("run_blender_workflow", arguments, result)
    return result


if set(PUBLIC_TOOLS) != _registered:
    raise RuntimeError(
        "Enabled registry tools do not match MCP implementations: "
        f"registry={PUBLIC_TOOLS}, implemented={sorted(_registered)}"
    )


mcp_http_app = mcp.streamable_http_app(
    streamable_http_path="/mcp",
    stateless_http=True,
    json_response=True,
    host="127.0.0.1",
)
