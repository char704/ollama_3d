import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

import api_service
import manage
import mcp_server
from capability_registry import CapabilityRegistry, load_registry
from project_config import ROOT, load, scoped_path
from workflows import mcp_workflow


class ConfigurationTests(unittest.TestCase):
    def test_current_config_is_valid_and_reserves_runtime(self):
        config = load()
        self.assertEqual(config["mcp"]["path"], "/mcp")
        registry = load_registry(ROOT / config["capability_registry"])
        self.assertTrue(
            {"system_status", "run_excel_to_blender", "create_colored_primitive"}.issubset(
                registry.public_tools()
            )
        )
        self.assertEqual(set(registry.public_tools()), mcp_server._registered)
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


class ApiTests(unittest.TestCase):
    def test_health_exposes_only_current_service(self):
        with TestClient(api_service.app) as client:
            response = client.get("/health")
            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertEqual(body["service"], "ollama3d-local-api")
            self.assertNotIn("blender_agent", body)
            self.assertNotIn("providers", body)


class McpRegistrationTests(unittest.TestCase):
    def test_every_public_tool_is_implemented_and_prompt_uses_registry_instructions(self):
        config = load()
        registry = load_registry(ROOT / config["capability_registry"])
        self.assertEqual(set(registry.public_tools()), mcp_server._registered)
        prompt = manage.build_system_prompt(registry)
        self.assertNotIn("đúng ba MCP tool", prompt)
        for item in registry.items():
            if item.get("public_tool") and item.get("instructions"):
                self.assertIn(item["instructions"], prompt)

    @patch.object(mcp_server, "_audit")
    @patch.object(mcp_server.REGISTRY, "generic_capabilities")
    def test_list_capabilities_filters_and_reads_bounded_docs(self, generic, _audit):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            root = Path(folder)
            knowledge = root / "knowledge"
            knowledge.mkdir()
            (knowledge / "fixture.md").write_text(
                "# Fixture Tools\n" + "x" * 2000, encoding="utf-8"
            )
            generic.return_value = [
                {
                    "id": "blender.fixture.paint",
                    "description": "Paint the fixture",
                    "risk": "mutating",
                    "params": {"type": "object", "properties": {}},
                    "docs": "knowledge/fixture.md",
                    "background_safe": True,
                }
            ]
            with patch.object(mcp_server, "ROOT", root):
                result = mcp_server.list_blender_capabilities("Fixture Tools")
        self.assertEqual(result["count"], 1)
        self.assertLessEqual(len(result["capabilities"][0]["docs_excerpt"]), 1500)

    @patch.object(mcp_server, "_audit")
    @patch.object(mcp_server, "execute_operator")
    def test_run_operator_tool_delegates_exact_arguments(self, execute, _audit):
        execute.return_value = {"ok": True, "status": "completed"}
        result = mcp_server.run_blender_operator(
            "blender.fixture.paint",
            {"color": "red"},
            "E:/model.blend",
            "E:/outputs",
        )
        self.assertTrue(result["ok"])
        execute.assert_called_once_with(
            capability_id="blender.fixture.paint",
            params={"color": "red"},
            model_path="E:/model.blend",
            output_dir="E:/outputs",
        )

    @patch.object(mcp_server, "_audit")
    @patch.object(mcp_server, "execute_blender_workflow")
    def test_run_workflow_tool_delegates_exact_arguments(self, execute, _audit):
        execute.return_value = {"ok": True, "status": "completed"}
        inputs = {"model_path": "E:/model.blend", "output_dir": "E:/outputs"}
        result = mcp_server.run_blender_workflow("workflow.fixture_generic", inputs)
        self.assertTrue(result["ok"])
        execute.assert_called_once_with(
            workflow_id="workflow.fixture_generic", inputs=inputs
        )


class WorkflowTests(unittest.TestCase):
    @patch.object(mcp_workflow, "log")
    @patch.object(mcp_workflow.BlenderAdapter, "create_colored_primitive")
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
            result = mcp_workflow.create_colored_primitive(
                "cube", "#7c3aed", output, 2.5, "QwenPurpleCube"
            )
            self.assertEqual(result["color_hex"], "#7C3AED")
            self.assertTrue(Path(result["output_path"]).is_file())
            with self.assertRaises(ValueError):
                mcp_workflow.create_colored_primitive("monkey", "#FFFFFF", output)
            with self.assertRaises(ValueError):
                mcp_workflow.create_colored_primitive("cube", "purple", output)

    @patch.object(mcp_workflow, "log")
    @patch.object(mcp_workflow.BlenderAdapter, "apply")
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
                    "transport": "blender-subprocess",
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
            verification = Path(result["evidence"]["verification"]).read_text(encoding="utf-8")
            self.assertIn('"blender_transport": "blender-subprocess"', verification)

    @patch.object(mcp_workflow, "log")
    @patch.object(mcp_workflow.BlenderAdapter, "status")
    @patch.object(mcp_workflow.ExcelVbaAdapter, "status")
    @patch.object(mcp_workflow.httpx, "get")
    def test_status_requires_all_three_real_components(
        self, get, excel_status, blender_status, _log
    ):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"models": [{"name": mcp_workflow.CONFIG["ollama"]["model"]}]}
        get.return_value = response
        excel_status.return_value = {"macro_callable": True}
        blender_status.return_value = {
            "operator_callable": True,
            "transport_callable": True,
        }
        self.assertTrue(mcp_workflow.system_status()["ready"])


if __name__ == "__main__":
    unittest.main()
