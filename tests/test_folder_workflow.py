import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from project_config import ROOT
from workflows import folder_workflow


class FolderWorkflowTests(unittest.TestCase):
    def _relative(self, path):
        return Path(path).resolve().relative_to(ROOT).as_posix()

    @patch.object(folder_workflow, "execute_jhv")
    def test_unique_excel_and_blend_run_with_relative_folders(self, execute):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            input_dir = Path(folder) / "inputs"
            input_dir.mkdir()
            excel = input_dir / "Footwear_BOM.xlsx"
            model = input_dir / "Shoe.blend"
            excel.write_bytes(b"xlsx")
            model.write_bytes(b"blend")
            (input_dir / "reference.png").write_bytes(b"png")
            output = Path(folder) / "outputs"
            execute.return_value = {"ok": True, "status": "completed"}

            result = folder_workflow.process_folder(
                self._relative(input_dir), self._relative(output)
            )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(
            result["folder_selection"]["workflow"], "workflow.jhv_excel_to_articles"
        )
        execute.assert_called_once_with(excel.resolve(), output.resolve(), model_path=model.resolve())

    @patch.object(folder_workflow, "apply_jhv_vbom")
    def test_unique_vbom_and_blend_calls_jhv(self, execute):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            input_dir = Path(folder) / "inputs"
            input_dir.mkdir()
            vbom = input_dir / "order.vbom"
            model = input_dir / "Shoe.blend"
            vbom.write_text('<VBOM/>', encoding="utf-8")
            model.write_bytes(b"blend")
            output = Path(folder) / "outputs"
            execute.return_value = {"ok": True, "status": "completed"}

            result = folder_workflow.process_folder(
                self._relative(input_dir), self._relative(output)
            )

        self.assertEqual(
            result["folder_selection"]["workflow"],
            "blender.jhv_dpc.run_dpc_automation",
        )
        execute.assert_called_once_with(
            vbom.resolve(),
            model.resolve(),
            output.resolve(),
        )

    @patch.object(folder_workflow, "execute_jhv")
    @patch.object(folder_workflow, "apply_jhv_vbom")
    def test_ambiguous_folder_asks_instead_of_guessing(self, operator, excel):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            input_dir = Path(folder) / "inputs"
            input_dir.mkdir()
            (input_dir / "one.xlsx").write_bytes(b"xlsx")
            (input_dir / "two.xlsx").write_bytes(b"xlsx")
            (input_dir / "model.blend").write_bytes(b"blend")
            result = folder_workflow.process_folder(
                self._relative(input_dir), self._relative(Path(folder) / "outputs")
            )
        self.assertEqual(result["status"], "needs_input")
        self.assertEqual(len(result["inventory"]["spreadsheets"]), 2)
        excel.assert_not_called()
        operator.assert_not_called()

    def test_folder_must_stay_in_scoped_roots(self):
        with self.assertRaises(ValueError):
            folder_workflow.process_folder("../outside", "outputs")


if __name__ == "__main__":
    unittest.main()
