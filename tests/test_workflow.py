"""Deterministic BOM workflow state transitions."""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from workflows import bom_pipeline


class BomWorkflowTests(unittest.TestCase):
    def test_successful_pipeline_persists_each_result(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(
            bom_pipeline, "WORKFLOW_ROOT", Path(folder)
        ), patch.object(
            bom_pipeline,
            "_export",
            return_value={
                "ok": True,
                "status": "exported",
                "run_id": "run-1",
                "vbom_path": "C:/output/materials.vbom",
            },
        ), patch.object(
            bom_pipeline,
            "_apply",
            return_value={
                "ok": True,
                "status": "completed",
                "output": "C:/output/result.blend",
            },
        ), patch.object(
            bom_pipeline, "log"
        ):
            result = bom_pipeline.run_bom_pipeline(
                "C:/input/bom.xlsx", "C:/input/model.blend", "C:/output", False
            )
            stored = bom_pipeline.get_bom_pipeline_job(result["job_id"])
        self.assertTrue(result["ok"])
        self.assertEqual(stored["status"], "completed")
        self.assertEqual(stored["output"]["model_path"], "C:/output/result.blend")
        self.assertEqual(
            [step["status"] for step in stored["steps"]], ["completed", "completed"]
        )

    def test_failed_export_stops_before_apply(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(
            bom_pipeline, "WORKFLOW_ROOT", Path(folder)
        ), patch.object(
            bom_pipeline, "_export", side_effect=RuntimeError("export failed")
        ), patch.object(
            bom_pipeline, "_apply"
        ) as apply_mock, patch.object(
            bom_pipeline, "log"
        ):
            result = bom_pipeline.run_bom_pipeline("C:/input/bom.xlsx")
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "failed")
        self.assertIn("export failed", result["error"])
        apply_mock.assert_not_called()

    def test_identical_completed_workflow_is_reused_unless_forced(self):
        export_result = {
            "ok": True,
            "status": "exported",
            "run_id": "run-1",
            "vbom_path": "C:/output/materials.vbom",
        }
        apply_result = {
            "ok": True,
            "status": "completed",
            "output": "C:/output/result.blend",
        }
        with tempfile.TemporaryDirectory() as folder, patch.object(
            bom_pipeline, "WORKFLOW_ROOT", Path(folder)
        ), patch.object(
            bom_pipeline, "_export", return_value=export_result
        ) as export_mock, patch.object(
            bom_pipeline, "_apply", return_value=apply_result
        ), patch.object(
            bom_pipeline, "log"
        ):
            source = bom_pipeline.INPUTS / "Footwear_BOM.xlsx"
            first = bom_pipeline.run_bom_pipeline(
                str(source), "C:/input/model.blend", "C:/output", False
            )
            reused = bom_pipeline.run_bom_pipeline(
                source.name, "C:/input/model.blend", "C:/output", False
            )
            forced = bom_pipeline.run_bom_pipeline(
                source.name,
                "C:/input/model.blend",
                "C:/output",
                False,
                True,
            )
        self.assertEqual(reused["job_id"], first["job_id"])
        self.assertTrue(reused["reused_job"])
        self.assertNotEqual(forced["job_id"], first["job_id"])
        self.assertEqual(export_mock.call_count, 2)


if __name__ == "__main__":
    unittest.main()
