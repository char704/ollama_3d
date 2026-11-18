"""Build Ollama3DProof.xlam from the checked-in VBA module using Excel COM.

This is a developer build step. Runtime installation only opens the produced xlam.
Excel must allow programmatic access to the VBA project for this one build.
"""

from pathlib import Path

import pythoncom
import win32com.client

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "vba" / "Ollama3DProof.bas"
OUTPUT = ROOT / "excel" / "Ollama3DProof.xlam"


def main():
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    pythoncom.CoInitialize()
    excel = workbook = None
    try:
        excel = win32com.client.DispatchEx("Excel.Application")
        excel.Visible = False
        excel.DisplayAlerts = False
        workbook = excel.Workbooks.Add()
        workbook.VBProject.VBComponents.Import(str(SOURCE))
        workbook.SaveAs(str(OUTPUT), FileFormat=55)
        print(OUTPUT)
    finally:
        if workbook is not None:
            workbook.Close(SaveChanges=False)
        if excel is not None:
            excel.Quit()
        pythoncom.CoUninitialize()


if __name__ == "__main__":
    main()
