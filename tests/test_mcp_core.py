import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

import api_service
from project_config import ROOT, load, scoped_path
from workflows import mcp_workflow


class ConfigurationTests(unittest.TestCase):
    def test_current_config_is_valid_and_reserves_runtime(self):
        config = load()
        self.assertEqual(config["mcp"]["path"], "/mcp")
        with self.assertRaises(ValueError):
            scoped_path(config, ROOT / "runtime" / "secret.xlsx")


class ApiTests(unittest.TestCase):
    def test_health_exposes_only_current_service(self):
        with TestClient(api_service.app) as client:
            response = client.get("/health")
            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertEqual(body["service"], "ollama3d-local-api")
            self.assertNotIn("blender_agent", body)
            self.assertNotIn("providers", body)


class WorkflowTests(unittest.TestCase):
    @patch.object(mcp_workflow, "log")
    @patch.object(mcp_workflow.BlenderProofAdapter, "apply")
    @patch.object(mcp_workflow.ExcelVbaAdapter, "export")
    @patch.object(mcp_workflow, "scoped_path")
    def test_real_workflow_contract_is_fixed_and_verified(
        self, scoped, export, apply, _log
    ):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            directory = Path(folder)
            excel = directory / "input.xlsx"
            model = directory / "input.blend"
            output = directory / "outputs"
            excel.write_bytes(b"xlsx")
            model.write_bytes(b"blend")
            scoped.side_effect = [excel, model, output]

            def export_result(_source, run_directory, _run_id):
                vbom = run_directory / "materials.vbom"
                vbom.write_bytes(b"vbom")
                proof = run_directory / "excel-proof.json"
                proof.write_text("{}", encoding="utf-8")
                return {
                    "producer": "ollama3d-vba",
                    "source_sha256": "source",
                    "vbom_sha256": "vbom",
                    "vbom_path": str(vbom),
                    "proof_path": str(proof),
                }

            def apply_result(_vbom, _model, output_path, _report, run_id):
                Path(output_path).write_bytes(b"result")
                return {
                    "ok": True,
                    "producer": "ollama3d-blender-addon",
                    "run_id": run_id,
                    "verified_after_reopen": True,
                }

            export.side_effect = export_result
            apply.side_effect = apply_result
            result = mcp_workflow.run_excel_to_blender(excel, model, output)
            self.assertEqual(result["status"], "completed")
            self.assertEqual(
                [step["id"] for step in result["steps"]],
                ["export_vbom_with_vba", "apply_vbom_with_addon"],
            )
            self.assertTrue(Path(result["output_path"]).is_file())
            self.assertTrue(Path(result["evidence"]["verification"]).is_file())

    @patch.object(mcp_workflow, "log")
    @patch.object(mcp_workflow.BlenderProofAdapter, "status")
    @patch.object(mcp_workflow.ExcelVbaAdapter, "status")
    @patch.object(mcp_workflow.httpx, "get")
    def test_status_requires_all_three_real_components(
        self, get, excel_status, blender_status, _log
    ):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"models": [{"name": "qwen3:8b"}]}
        get.return_value = response
        excel_status.return_value = {"macro_callable": True}
        blender_status.return_value = {"operator_callable": True}
        self.assertTrue(mcp_workflow.system_status()["ready"])


if __name__ == "__main__":
    unittest.main()
