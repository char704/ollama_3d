"""Isolated Excel COM worker; the parent enforces a hard timeout."""

import json
import sys
from pathlib import Path

import pythoncom
import win32com.client
import win32process


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def main():
    (
        mode,
        executable,
        addin_path,
        macro,
        result_path,
        control_path,
        *arguments,
    ) = sys.argv[1:]
    if not Path(executable).is_file() or not Path(addin_path).is_file():
        raise FileNotFoundError("Excel executable or VBA add-in is missing")
    pythoncom.CoInitialize()
    excel = addin = None
    try:
        excel = win32com.client.DispatchEx("Excel.Application")
        excel.Visible = False
        excel.DisplayAlerts = False
        excel.EnableEvents = False
        pid = win32process.GetWindowThreadProcessId(excel.Hwnd)[1]
        write(control_path, {"excel_pid": pid})
        addin = excel.Workbooks.Open(
            addin_path, UpdateLinks=0, ReadOnly=True, AddToMru=False
        )
        if mode == "status":
            value = str(excel.Application.Run(macro))
            write(result_path, {"ok": True, "value": value, "excel_pid": pid})
        elif mode == "export":
            value = str(excel.Application.Run(macro, *arguments))
            write(result_path, {"ok": True, "value": value, "excel_pid": pid})
        else:
            raise ValueError("Unknown Excel worker mode: " + mode)
    except Exception as exc:
        write(result_path, {"ok": False, "error": str(exc)})
        raise
    finally:
        try:
            if addin is not None:
                addin.Close(SaveChanges=False)
        finally:
            if excel is not None:
                excel.Quit()
            pythoncom.CoUninitialize()


if __name__ == "__main__":
    main()
