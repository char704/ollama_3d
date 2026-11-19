import json
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from agent import run as agent_run
from project_config import ROOT


class FakeClient:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def structured(self, model, system, user, schema, role):
        self.calls.append(
            {"model": model, "system": system, "user": user, "schema": schema, "role": role}
        )
        return self.responses.pop(0), {
            "role": role,
            "model": model,
            "stream": False,
            "format": "json_schema",
            "temperature": 0,
            "think": False,
        }


class AgentTests(unittest.TestCase):
    def test_missing_paths_are_requested_without_execution(self):
        client = FakeClient(
            {"intent": "run_operator"},
            {
                "candidate_id": "blender.ollama3d_proof.apply_vbom",
                "params": {"run_id": "TEST-RUN"},
                "model_path": None,
                "output_dir": None,
            },
        )
        with patch.object(agent_run, "run_blender_operator") as execute:
            result = agent_run.Agent(client).handle("Áp VBOM TEST-RUN nhưng chưa có đường dẫn")
        self.assertEqual(result["status"], "needs_input")
        self.assertIn("filepath", result["missing"])
        self.assertIn("model_path", result["missing"])
        execute.assert_not_called()

    def test_operator_selection_is_validated_and_final_answer_is_templated(self):
        vbom = str(ROOT / "tests" / "fixtures" / "proof_v1.vbom.xml")
        model = str(ROOT / "inputs" / "Sneaker_Unassigned.blend")
        output = str(ROOT / "outputs")
        client = FakeClient(
            {"intent": "run_operator"},
            {
                "candidate_id": "blender.ollama3d_proof.apply_vbom",
                "params": {"filepath": vbom, "run_id": "TEST-RUN"},
                "model_path": model,
                "output_dir": output,
            },
        )
        execution = {
            "ok": True,
            "status": "completed",
            "output_path": str(ROOT / "outputs" / "run" / "result.blend"),
        }
        with patch.object(agent_run, "run_blender_operator", return_value=execution) as execute:
            result = agent_run.Agent(client).handle("Áp file VBOM vào mẫu giày")
        self.assertEqual(result["status"], "completed")
        self.assertIn(execution["output_path"], result["message"])
        execute.assert_called_once()
        self.assertEqual([call["role"] for call in client.calls], ["router", "selector"])
        self.assertEqual(
            [call["model"] for call in client.calls],
            [
                agent_run.CONFIG["ollama"]["router_model"],
                agent_run.CONFIG["ollama"]["model"],
            ],
        )

    def test_colored_primitive_calls_direct_blender_workflow(self):
        output = str(ROOT / "outputs")
        client = FakeClient(
            {"intent": "run_operator"},
            {
                "candidate_id": "blender.create_colored_primitive",
                "params": {
                    "primitive": "cube",
                    "color_hex": "#336699",
                    "size": 3.0,
                    "object_name": "DirectCube",
                },
                "model_path": None,
                "output_dir": output,
            },
        )
        completed = {"ok": True, "status": "completed", "output_path": "cube.blend"}
        with patch.object(
            agent_run, "create_colored_primitive", return_value=completed
        ) as execute:
            result = agent_run.Agent(client).handle("Tạo cube màu #336699")
        self.assertEqual(result["status"], "completed")
        execute.assert_called_once_with(
            "cube", "#336699", output, 3.0, "DirectCube"
        )

    def test_excel_addin_workflow_is_called_directly(self):
        excel = str(ROOT / "inputs" / "Footwear_BOM.xlsx")
        model = str(ROOT / "inputs" / "Sneaker_Unassigned.blend")
        output = str(ROOT / "outputs")
        client = FakeClient(
            {"intent": "run_workflow"},
            {
                "candidate_id": "workflow.excel_to_blender",
                "inputs": {
                    "excel_path": excel,
                    "model_path": model,
                    "output_dir": output,
                },
            },
        )
        completed = {"ok": True, "status": "completed", "output_path": "result.blend"}
        with patch.object(
            agent_run, "run_excel_to_blender", return_value=completed
        ) as execute:
            result = agent_run.Agent(client).handle("Chạy Excel BOM sang Blender")
        self.assertEqual(result["status"], "completed")
        execute.assert_called_once_with(excel, model, output)

    def test_chat_uses_router_and_utility_model_without_tools(self):
        client = FakeClient({"intent": "chat"}, {"answer": "VBOM mô tả vật liệu."})
        with patch.object(agent_run, "run_blender_operator") as operator, patch.object(
            agent_run, "run_blender_workflow"
        ) as workflow:
            result = agent_run.Agent(client).handle("VBOM là gì?")
        self.assertEqual(result["status"], "chat")
        self.assertEqual(result["message"], "VBOM mô tả vật liệu.")
        self.assertEqual(
            [call["model"] for call in client.calls],
            [
                agent_run.CONFIG["ollama"]["router_model"],
                agent_run.CONFIG["ollama"]["utility_model"],
            ],
        )
        operator.assert_not_called()
        workflow.assert_not_called()

    def test_small_model_cannot_route_or_select_blender_work(self):
        self.assertEqual(
            agent_run.CONFIG["ollama"]["router_model"],
            agent_run.CONFIG["ollama"]["model"],
        )
        self.assertNotEqual(
            agent_run.CONFIG["ollama"]["utility_model"],
            agent_run.CONFIG["ollama"]["router_model"],
        )

    def test_retrieval_is_limited_to_five_candidates(self):
        capabilities = [
            {
                "id": f"blender.fixture.operation_{index}",
                "description": f"paint shoe {index}",
                "params": {"type": "object", "properties": {}},
                "risk": "read",
            }
            for index in range(8)
        ]
        with patch.object(agent_run.REGISTRY, "generic_capabilities", return_value=capabilities):
            result = agent_run.retrieve_candidates("paint shoe", "run_operator")
        self.assertEqual(len(result), 5)

    def test_ollama_client_uses_schema_and_disables_supported_thinking(self):
        show = Mock()
        show.raise_for_status.return_value = None
        show.json.return_value = {"thinking": {"values": [True, False], "default": True}}
        chat = Mock()
        chat.raise_for_status.return_value = None
        chat.json.return_value = {"message": {"content": '{"intent":"chat"}'}}
        with patch.object(agent_run.httpx, "post", side_effect=[show, chat]) as post:
            value, metadata = agent_run.OllamaClient("http://127.0.0.1:11434").structured(
                "router", "system", "hello", agent_run.ROUTER_SCHEMA, "router"
            )
        self.assertEqual(value["intent"], "chat")
        body = post.call_args_list[1].kwargs["json"]
        self.assertFalse(body["think"])
        self.assertEqual(body["format"], agent_run.ROUTER_SCHEMA)
        self.assertFalse(body["stream"])
        self.assertFalse(metadata["think"])

    def test_agent_source_only_uses_local_workflows(self):
        source = Path(agent_run.__file__).read_text(encoding="utf-8")
        self.assertIn("from workflows.core_workflow import", source)


if __name__ == "__main__":
    unittest.main()
