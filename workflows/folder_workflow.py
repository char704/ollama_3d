"""Read-only file inventory and JHV-oriented folder workflow."""
from pathlib import Path
from adapters.common import CONFIG, ROOT, log
from project_config import data_path, scoped_path
from workflows.jhv_workflow import apply_jhv_vbom, execute_jhv


def _display(path):
    path = Path(path).resolve()
    return path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else str(path)


def inspect_folder(input_dir="inputs"):
    directory = scoped_path(CONFIG, input_dir)
    if not directory.is_dir():
        raise ValueError("input_dir must be an existing allowed directory")
    files = [p for p in sorted(directory.rglob("*"))
             if p.is_file() and not any(part.startswith(".") for part in p.relative_to(directory).parts)]
    spreadsheets = [p for p in files if p.suffix.casefold() in (".xlsx", ".xlsm", ".xlsb", ".xls")
                    and not p.name.startswith("~$")]
    blends = [p for p in files if p.suffix.casefold() == ".blend"]
    vboms = [p for p in files if p.suffix.casefold() == ".vbom"]
    return {"input_dir": _display(directory), "files": [_display(p) for p in files],
            "spreadsheets": [_display(p) for p in spreadsheets],
            "blends": [_display(p) for p in blends],
            "vboms": [_display(p) for p in vboms],
            "_paths": {"spreadsheets": spreadsheets, "blends": blends, "vboms": vboms}}


def process_folder(input_dir=None, output_dir=None):
    inventory = inspect_folder(input_dir or data_path(CONFIG, "inputs"))
    output = scoped_path(CONFIG, output_dir, data_path(CONFIG, "outputs"))
    paths = inventory["_paths"]
    spreadsheets, blends, vboms = (paths[k] for k in ("spreadsheets", "blends", "vboms"))
    # An existing VBOM and a new BOM could be different versions: do not guess.
    if len(spreadsheets) == 1 and not vboms and len(blends) == 1:
        result = execute_jhv(spreadsheets[0], output, model_path=blends[0])
        result["folder_selection"] = {"workflow": "workflow.jhv_excel_to_articles"}
        return result
    if len(vboms) == 1 and len(blends) == 1 and not spreadsheets:
        result = apply_jhv_vbom(vboms[0], blends[0], output)
        result["folder_selection"] = {"workflow": "blender.jhv_dpc.run_dpc_automation"}
        return result
    public = {k: v for k, v in inventory.items() if k != "_paths"}
    result = {"ok": False, "status": "needs_input", "input_dir": inventory["input_dir"],
              "output_dir": _display(output), "inventory": public,
              "message": "Thư mục có nhiều hoặc thiếu file phù hợp. Hãy chọn file Excel, VBOM hoặc model Blender cụ thể."}
    log("process_folder_needs_input", {"result": result})
    return result
