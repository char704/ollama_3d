import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from capability_registry import CapabilityRegistry, load_registry
from project_config import ROOT, load, scoped_path
from workflows import core_workflow


class ConfigurationTests(unittest.TestCase):
    def test_current_config_is_direct_and_reserves_runtime(self):
        config = load()
        self.assertEqual(config["profile"], "direct-automation")
        self.assertNotIn("mcp", config)
        self.assertNotIn("official_blender_mcp", config)
        registry = load_registry(ROOT / config["capability_registry"])
        self.assertEqual(
            registry.require("excel.export_vbom", provider="excel_vba")["target"],
            "'Ollama3DProof.xlam'!ExportVBOM",
        )
        with self.assertRaises(ValueError):
            scoped_path(config, ROOT / "runtime" / "secret.xlsx")

    def test_registry_rejects_duplicates_and_disabled_dependencies(self):
        document = {
            "schema_version": 1,
            "capabilities": [
                {
                    "id": "excel.export",
                    "provider": "excel_vba",
                    "handler": "export",
                    "target": "Macro",
                    "enabled": False,
                },
                {
                    "id": "workflow.run",
                    "provider": "workflow",
                    "handler": "run",
                    "target": "workflow.run",
                    "dependencies": ["excel.export"],
                    "enabled": True,
                },
            ],
        }
        registry = CapabilityRegistry(ROOT / "test-capabilities.json", document)
        with self.assertRaisesRegex(RuntimeError, "disabled"):
            registry.require("workflow.run")
        document["capabilities"][1]["id"] = "excel.export"
        with self.assertRaisesRegex(ValueError, "duplicate"):
            CapabilityRegistry(ROOT / "test-capabilities.json", document)

    def test_registry_rejects_dependency_cycles(self):
        document = {
            "schema_version": 1,
            "capabilities": [
                {
                    "id": "workflow.one",
                    "provider": "workflow",
                    "handler": "one",
                    "target": "one",
                    "dependencies": ["workflow.two"],
                    "enabled": True,
                },
                {
                    "id": "workflow.two",
                    "provider": "workflow",
                    "handler": "two",
                    "target": "two",
                    "dependencies": ["workflow.one"],
                    "enabled": True,
                },
            ],
        }
        with self.assertRaisesRegex(ValueError, "cycle"):
            CapabilityRegistry(ROOT / "test-capabilities.json", document)


class WorkflowTests(unittest.TestCase):
    @patch.object(core_workflow, "log")
    @patch.object(core_workflow.BlenderAdapter, "create_colored_primitive")
    def test_colored_primitive_is_validated_and_verified(self, create, _log):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            output = Path(folder)

            def create_result(primitive, color, size, name, output_path, report_path, run_id):
                Path(output_path).write_bytes(b"blend")
                Path(report_path).write_text("{}", encoding="utf-8")
                return {
                    "ok": True,
                    "status": "completed",
                    "run_id": run_id,
                    "primitive": primitive,
                    "color_hex": color,
                    "size": size,
                    "object_name": name,
                    "output_path": str(output_path),
                    "proof_path": str(report_path),
                    "verified_after_reopen": True,
                    "transport": "blender-subprocess",
                }

            create.side_effect = create_result
            result = core_workflow.create_colored_primitive(
                "cube", "#7c3aed", output, 2.5, "QwenPurpleCube"
            )
            self.assertEqual(result["color_hex"], "#7C3AED")
            self.assertTrue(Path(result["output_path"]).is_file())
            with self.assertRaises(ValueError):
                core_workflow.create_colored_primitive("monkey", "#FFFFFF", output)
            with self.assertRaises(ValueError):
                core_workflow.create_colored_primitive("cube", "purple", output)

    @patch.object(core_workflow, "log")
    @patch.object(core_workflow.BlenderAdapter, "apply")
    @patch.object(core_workflow.ExcelVbaAdapter, "export")
    @patch.object(core_workflow, "scoped_path")
    def test_excel_addin_to_blender_addon_contract(self, scoped, export, apply, _log):
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
                    "transport": "blender-subprocess",
                    "run_id": run_id,
                    "verified_after_reopen": True,
                }

            export.side_effect = export_result
            apply.side_effect = apply_result
            result = core_workflow.run_excel_to_blender(excel, model, output)
            self.assertEqual(result["status"], "completed")
            self.assertEqual(
                [step["id"] for step in result["steps"]],
                ["export_vbom_with_vba", "apply_vbom_with_addon"],
            )
            self.assertTrue(Path(result["output_path"]).is_file())
            self.assertTrue(Path(result["evidence"]["verification"]).is_file())

    @patch.object(core_workflow, "log")
    @patch.object(core_workflow.BlenderAdapter, "status")
    @patch.object(core_workflow.ExcelVbaAdapter, "status")
    @patch.object(core_workflow.httpx, "get")
    def test_status_requires_models_excel_and_blender(
        self, get, excel_status, blender_status, _log
    ):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "models": [{"name": core_workflow.CONFIG["ollama"]["model"]}]
        }
        get.return_value = response
        excel_status.return_value = {"macro_callable": True}
        blender_status.return_value = {
            "operator_callable": True,
            "transport_callable": True,
        }
        self.assertTrue(core_workflow.system_status()["ready"])


if __name__ == "__main__":
    unittest.main()
