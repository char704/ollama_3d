"""Isolated Excel COM reader for JHV V26-compatible exporter (Windows only)."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def write(path, payload):
    Path(path).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def main():
    _, source, target, sheet_name, result_path, control_path = sys.argv[1:]
    import pythoncom
    import win32com.client
    import win32process
    from adapters.jhv_vbom import render_vbom
    pythoncom.CoInitialize()
    excel = workbook = None
    try:
        excel = win32com.client.DispatchEx("Excel.Application")
        excel.Visible = False
        excel.DisplayAlerts = False
        excel.EnableEvents = False
        write(control_path, {"excel_pid": win32process.GetWindowThreadProcessId(excel.Hwnd)[1]})
        workbook = excel.Workbooks.Open(str(Path(source).resolve()), UpdateLinks=0,
                                         ReadOnly=True, AddToMru=False)
        sheet = workbook.Worksheets(sheet_name) if sheet_name else workbook.ActiveSheet
        # UsedRange may begin after A1; explicitly read A1:last active cell to
        # preserve VBA's absolute worksheet indices.
        used = sheet.UsedRange
        last_row = used.Row + used.Rows.Count - 1
        last_col = used.Column + used.Columns.Count - 1
        values = sheet.Range(sheet.Cells(1, 1), sheet.Cells(last_row, last_col)).Value2
        if last_row == 1 and last_col == 1:
            values = ((values,),)
        elif last_row == 1:
            values = tuple(values) if isinstance(values[0], (tuple, list)) else (tuple(values),)
        elif last_col == 1:
            values = tuple(values) if isinstance(values[0], (tuple, list)) else tuple((item,) for item in values)
        xml, stats = render_vbom(values, sheet.Name)
        # Exclusive-create avoids replacing a file created between validation and write.
        with open(target, "xb") as output:
            output.write(xml)
        write(result_path, {"ok": True, **stats})
    except Exception as exc:
        write(result_path, {"ok": False, "error": f"{type(exc).__name__}: {exc}"})
        raise
    finally:
        try:
            if workbook is not None:
                workbook.Close(SaveChanges=False)
        finally:
            if excel is not None:
                excel.Quit()
            pythoncom.CoUninitialize()


if __name__ == "__main__":
    main()
