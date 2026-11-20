"""JHV V26-compatible VBOM export from values read using Excel COM.

Does not alter or invoke the vendor's ribbon add-in. The output is XML-equivalent,
not guaranteed byte-for-byte equivalent to the vendor ADODB.Stream output.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path


CLEAN = re.compile(r"[^a-zA-Z0-9\-_ \.\/\|]")
ARTICLE = re.compile(r"[A-Z]{2}[0-9]{4}")
REQUIRED = ("Part ID", "Part Name", "Supplier Material ID", "Supplier Material Name")


def _v(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _clean(value):
    return CLEAN.sub("", _v(value)).strip()


def _cell(rows, row, col):
    if row < 0 or row >= len(rows) or col < 0 or col >= len(rows[row]):
        return None
    return rows[row][col]


def render_vbom(rows, sheet_name):
    """Return (XML bytes, stats) from a 2D list of 1-based worksheet values.

    rows[0] is Excel row 1. Strictly validate source format before creating output.
    """
    if not isinstance(rows, (tuple, list)) or not rows:
        raise ValueError("EMPTY_SHEET: No worksheet rows")
    header_at = next(
        (i for i in range(min(100, len(rows))) if _v(_cell(rows, i, 0)).strip() == "Variation"),
        None,
    )
    if header_at is None:
        raise ValueError("BOM_INVALID: 'Variation' not found in column A rows 1-100")
    headers = [_v(x).strip() for x in rows[header_at]]
    columns = {name: next((i for i, value in enumerate(headers) if value == name), None) for name in REQUIRED}
    missing = [key for key, index in columns.items() if index is None]
    color_columns = [i for i, name in enumerate(headers) if name == "Color"]
    if not color_columns:
        missing.append("Color")
    if missing:
        raise ValueError("BOM_MISSING_COLUMNS: " + ", ".join(missing))
    if header_at == 0:
        raise ValueError("BOM_INVALID: Article IDs require a row above Variation")
    part_id_col = columns["Part ID"]
    # VBA End(xlUp) uses last populated Part ID, not the last formatted worksheet row.
    last_part = next((i for i in range(len(rows)-1, header_at, -1)
                      if _cell(rows, i, part_id_col) not in (None, "")), None)
    if last_part is None:
        raise ValueError("BOM_EMPTY: No data rows below Variation")
    vbom = ET.Element("VBOM", {"scene": sheet_name})
    seen_ids = set()
    stats = {"articles": 0, "parts": 0, "article_ids": []}
    for color_col in color_columns:
        raw_id = _v(_cell(rows, header_at - 1, color_col)).strip()
        match = ARTICLE.search(raw_id)
        article_id = match.group() if match else "UNKNOWN"
        if article_id in seen_ids:
            raise ValueError(f"DUPLICATE_ARTICLE: {article_id}; check headings above Color columns")
        if article_id == "UNKNOWN":
            raise ValueError(f"INVALID_ARTICLE: No [A-Z]{{2}}[0-9]{{4}} ID above Color column {color_col + 1}")
        seen_ids.add(article_id)
        ref = ET.SubElement(vbom, "ReferenceParts", {"id": article_id})
        stats["article_ids"].append(article_id)
        for i in range(header_at + 1, last_part + 1):
            part_id = _cell(rows, i, part_id_col)
            part_name = _cell(rows, i, columns["Part Name"])
            full_color = _v(_cell(rows, i, color_col)).strip()
            if part_id in (None, "") or part_name in (None, "") or not full_color or full_color.upper() == "NA":
                continue
            cleaned_id = _clean(part_id)
            cleaned_name = _clean(part_name)
            if not cleaned_id or not cleaned_name:
                continue
            first_id = cleaned_id.split("-", 1)[0]
            # VBA IsNumeric/CLng: for real BOM IDs typically integer. Keep numbers <= 8900.
            try:
                if first_id.isdecimal() and int(first_id) > 8900:
                    continue
            except ValueError:
                pass
            full_color_parts = full_color.split(" ")
            code = _clean(full_color_parts[0])
            name = _clean(full_color[len(full_color_parts[0]) + 1:]) if len(full_color_parts) > 1 else ""
            if not code:
                continue
            part = ET.SubElement(ref, "Part", {"name": f"{cleaned_id}_{cleaned_name}_L|{article_id}"})
            ET.SubElement(part, "VPart", {
                "mat_id": _clean(_cell(rows, i, columns["Supplier Material ID"])),
                "mat_name": _clean(_cell(rows, i, columns["Supplier Material Name"])),
                "color_code": code,
                "color_name": name,
                "comp_code": cleaned_id,
            })
            stats["parts"] += 1
        stats["articles"] += 1
    if not stats["parts"]:
        raise ValueError("BOM_EMPTY: No valid VBOM parts generated")
    data = ET.tostring(vbom, encoding="utf-8", xml_declaration=True)
    ET.fromstring(data)  # XML should be valid even with punctuation in sheet name.
    return data, stats


class JHVBomExporter:
    """Export in a killable Excel COM child process; write a fresh output only."""
    def export(self, excel_path, output_path, sheet_name=""):
        from adapters.common import CONFIG, ROOT
        from project_config import scoped_path
        source = scoped_path(CONFIG, excel_path)
        target = scoped_path(CONFIG, output_path)
        if source.suffix.casefold() not in (".xlsx", ".xlsm", ".xlsb", ".xls") or not source.is_file():
            raise ValueError("BOM input must be an existing Excel workbook in an allowed directory")
        if target.suffix.casefold() != ".vbom" or target.exists():
            raise ValueError("VBOM output must be a NEW .vbom file (no overwrites)")
        if target == source:
            raise ValueError("Input and output must differ")
        target.parent.mkdir(parents=True, exist_ok=True)
        worker_dir = ROOT / "runtime" / "jhv-excel-workers" / uuid.uuid4().hex
        worker_dir.mkdir(parents=True, exist_ok=False)
        result_path = worker_dir / "result.json"
        control_path = worker_dir / "control.json"
        command = [sys.executable, str(ROOT / "scripts" / "jhv_excel_worker.py"),
                   str(CONFIG["excel"]["executable"]), str(source), str(target),
                   sheet_name, str(result_path), str(control_path)]
        try:
            completed = subprocess.run(command, capture_output=True, text=True,
                                       timeout=CONFIG["excel"]["timeout_seconds"],
                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except subprocess.TimeoutExpired as exc:
            try:
                import psutil
                control = json.loads(control_path.read_text(encoding="utf-8")) if control_path.is_file() else {}
                pid = int(control.get("excel_pid", -1))
                if pid > 0:
                    proc = psutil.Process(pid)
                    if proc.name().casefold() == "excel.exe":
                        proc.terminate()
                        proc.wait(timeout=10)
            except (ValueError, OSError, psutil.Error, KeyError):
                pass
            raise RuntimeError("JHV Excel COM worker timed out") from exc
        if not result_path.is_file():
            raise RuntimeError("Excel COM worker failed: " + (completed.stderr or "no result")[-800:])
        result = json.loads(result_path.read_text(encoding="utf-8"))
        if completed.returncode or not result.get("ok"):
            raise RuntimeError("JHV export failed: " + result.get("error", "unknown error"))
        if not target.is_file():
            raise RuntimeError("VBOM export did not create the expected file")
        xml = target.read_bytes()
        ET.fromstring(xml)
        return {"ok": True, "status": "exported", "producer": "jhv-python-v26-compatible",
                "source_excel": str(source), "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "vbom_path": str(target), "vbom_sha256": hashlib.sha256(xml).hexdigest(),
                "article_ids": result["article_ids"], "articles": result["articles"], "parts": result["parts"]}
