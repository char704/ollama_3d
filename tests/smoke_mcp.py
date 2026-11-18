"""Real MCP protocol smoke test against the running local API."""

import asyncio
from pathlib import Path

from mcp import Client

ROOT = Path(__file__).resolve().parents[1]


async def main():
    async with Client("http://127.0.0.1:8090/mcp") as client:
        tools = await client.list_tools()
        names = [tool.name for tool in tools.tools]
        assert names == ["system_status", "run_excel_to_blender", "create_colored_primitive"], names
        status = await client.call_tool("system_status", {})
        status_payload = status.structured_content
        print(f"tools={names}; ready={status_payload['ready']}")
        assert status_payload["ready"] is True

        result = await client.call_tool(
            "run_excel_to_blender",
            {
                "excel_path": str((ROOT / "inputs" / "Footwear_BOM.xlsx").resolve()),
                "model_path": str((ROOT / "inputs" / "Sneaker_Unassigned.blend").resolve()),
                "output_dir": str((ROOT / "outputs").resolve()),
            },
        )
        payload = result.structured_content
        print(
            f"run_id={payload['run_id']}; status={payload['status']}; "
            f"output={payload['output_path']}"
        )
        assert payload["status"] == "completed"
        assert Path(payload["output_path"]).is_file()

        primitive = await client.call_tool(
            "create_colored_primitive",
            {
                "primitive": "cube",
                "color_hex": "#7C3AED",
                "output_dir": str((ROOT / "outputs").resolve()),
                "size": 2.5,
                "object_name": "QwenPurpleCube",
            },
        )
        primitive_payload = primitive.structured_content
        print(
            f"primitive={primitive_payload['primitive']}; color={primitive_payload['color_hex']}; "
            f"output={primitive_payload['output_path']}"
        )
        assert primitive_payload["status"] == "completed"
        assert primitive_payload["verified_after_reopen"] is True
        assert Path(primitive_payload["output_path"]).is_file()


if __name__ == "__main__":
    asyncio.run(main())
