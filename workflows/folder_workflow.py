"""Deterministically choose a safe workflow from a project-relative input folder."""

import xml.etree.ElementTree as ET
from pathlib import Path

from adapters.common import CONFIG, ROOT, log
from project_config import scoped_path
from workflows.mcp_workflow import run_excel_to_blender
from workflows.operator_workflow import run_blender_operator


def _display(path):
    path = Path(path).resolve()
    return path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else str(path)


def _vbom_metadata(path):
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError):
        return None
    if root.tag.casefold() != "vbom" or not root.get("run_id"):
        return None
    return {"path": path, "run_id": root.get("run_id")}


def inspect_folder(input_dir="inputs"):
    directory = scoped_path(CONFIG, input_dir)
    if not directory.is_dir():
        raise ValueError("input_dir must be an existing project-relative directory")
    files = [
        path
        for path in sorted(directory.rglob("*"))
        if path.is_file()
        and not any(part.startswith(".") for part in path.relative_to(directory).parts)
    ]
    spreadsheets = [
        path for path in files if path.suffix.casefold() == ".xlsx" and not path.name.startswith("~$")
    ]
    blends = [path for path in files if path.suffix.casefold() == ".blend"]
    vboms = [metadata for path in files if (metadata := _vbom_metadata(path))]
    return {
        "input_dir": _display(directory),
        "files": [_display(path) for path in files],
        "spreadsheets": [_display(path) for path in spreadsheets],
        "blends": [_display(path) for path in blends],
        "vboms": [
            {"path": _display(item["path"]), "run_id": item["run_id"]}
            for item in vboms
        ],
        "_paths": {
            "spreadsheets": spreadsheets,
            "blends": blends,
            "vboms": vboms,
        },
    }


def _needs_input(inventory, output_dir, reason):
    public_inventory = {key: value for key, value in inventory.items() if key != "_paths"}
    result = {
        "ok": False,
        "status": "needs_input",
        "input_dir": inventory["input_dir"],
        "output_dir": _display(output_dir),
        "reason": reason,
        "message": (
            "Không thể chọn workflow duy nhất từ thư mục. Cần chỉ rõ file hoặc loại xử lý."
        ),
        "inventory": public_inventory,
        "supported_workflows": [
            "one .xlsx + one .blend -> Excel add-in to Blender add-on",
            "one VBOM .xml + one .blend -> apply VBOM Blender operator",
        ],
    }
    log("process_folder_needs_input", {"result": result})
    return result


def process_folder(input_dir="inputs", output_dir="outputs"):
    """Run a workflow only when the supported files identify one unambiguous action."""
    inventory = inspect_folder(input_dir)
    output = scoped_path(CONFIG, output_dir)
    paths = inventory["_paths"]
    spreadsheets = paths["spreadsheets"]
    blends = paths["blends"]
    vboms = paths["vboms"]

    excel_ready = len(spreadsheets) == 1 and len(blends) == 1 and not vboms
    vbom_ready = len(vboms) == 1 and len(blends) == 1 and not spreadsheets
    if excel_ready:
        result = run_excel_to_blender(spreadsheets[0], blends[0], output)
        result["folder_selection"] = {
            "workflow": "workflow.excel_to_blender",
            "input_dir": inventory["input_dir"],
            "files": [_display(spreadsheets[0]), _display(blends[0])],
        }
        return result
    if vbom_ready:
        metadata = vboms[0]
        result = run_blender_operator(
            "blender.ollama3d_proof.apply_vbom",
            {"filepath": str(metadata["path"]), "run_id": metadata["run_id"]},
            blends[0],
            output,
        )
        result["folder_selection"] = {
            "workflow": "blender.ollama3d_proof.apply_vbom",
            "input_dir": inventory["input_dir"],
            "files": [_display(metadata["path"]), _display(blends[0])],
        }
        return result

    counts = {
        "xlsx": len(spreadsheets),
        "blend": len(blends),
        "vbom": len(vboms),
    }
    return _needs_input(inventory, output, "ambiguous_or_incomplete: " + str(counts))
