import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

import api_service
from capability_registry import CapabilityRegistry, load_registry
from project_config import ROOT, load, scoped_path
from workflows import core_workflow


class ConfigurationTests(unittest.TestCase):
    def test_current_config_is_rest_direct_and_reserves_runtime(self):
        config = load()
        self.assertEqual(config["profile"], "rest-direct")
        registry = load_registry(ROOT / config["capability_registry"])
        self.assertEqual(
            registry.require("workflow.jhv_export_vbom", provider="workflow")["target"],
            "workflow.jhv_export_vbom",
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
    def setUp(self):
        self.client = TestClient(api_service.app)
        self.headers = {"Authorization": "Bearer " + api_service.LOCAL_API_KEY}

    def test_health_and_models_expose_only_direct_rest_backend(self):
        health = self.client.get("/health").json()
        self.assertEqual(health["service"], "ollama3d-local-api")
        self.assertEqual(health["transport"], "rest-direct")
        self.assertEqual(self.client.get("/v1/models").status_code, 401)
        models = self.client.get("/v1/models", headers=self.headers).json()
        self.assertEqual(models["data"][0]["id"], api_service.MODEL_ID)

    @patch.object(api_service, "handle")
    def test_chat_completions_calls_local_agent(self, handle):
        handle.return_value = {"ok": True, "status": "chat", "message": "Xin chào"}
        response = self.client.post(
            "/v1/chat/completions",
            headers=self.headers,
            json={
                "model": api_service.MODEL_ID,
                "messages": [{"role": "user", "content": "Chào bạn"}],
                "stream": False,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["choices"][0]["message"]["content"], "Xin chào")
        handle.assert_called_once_with(
            "Chào bạn", history=[{"role": "user", "content": "Chào bạn"}]
        )


class WorkflowTests(unittest.TestCase):
    @patch.object(core_workflow, "log")
    @patch.object(core_workflow.BlenderAdapter, "status")
    @patch.object(core_workflow.httpx, "get")
    def test_status_requires_registered_jhv_operator(self, get, blender_status, _log):
        get.return_value.json.return_value = {
            "models": [{"name": core_workflow.CONFIG["ollama"]["model"]}]
        }
        blender_status.return_value = {
            "transport_callable": True, "operators": {"jhv.run_dpc_automation": False}
        }
        with patch.object(Path, "is_file", return_value=True):
            self.assertFalse(core_workflow.system_status()["ready"])
            blender_status.return_value["operators"]["jhv.run_dpc_automation"] = True
            self.assertTrue(core_workflow.system_status()["ready"])
