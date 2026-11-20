import json
import sys
import tempfile
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

    def chat(self, model, messages):
        self.calls.append({"role": "chat", "model": model, "messages": messages})
        value = self.responses.pop(0)
        return value["answer"], {"role": "chat", "model": model, "format": "text"}


class AgentTests(unittest.TestCase):
    def test_full_pipeline_requires_model(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            directory = Path(folder)
            (directory / "BOM.xlsx").touch()
            client = FakeClient({"intent": "full_pipeline", "input_dir": folder})
            with patch.object(agent_run, "execute_jhv") as execute:
                result = agent_run.Agent(client).handle(f'Xử lý BOM trong "{folder}"')
            self.assertEqual(result["missing"], ["model_path"])
            execute.assert_not_called()

    def test_export_only_ignores_blend_and_respects_paths(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            source = Path(folder) / "BOM.xlsx"
            source.touch()
            (Path(folder) / "Shoe.blend").touch()
            output = Path(folder) / "output"
            client = FakeClient({
                "intent": "export_only", "input_dir": folder, "output_dir": str(output)
            })
            done = {"ok": True, "status": "completed", "output_path": "result.vbom"}
            with patch.object(agent_run, "execute_jhv", return_value=done) as execute:
                result = agent_run.Agent(client).handle(
                    f'Chỉ xuất VBOM từ thư mục "{folder}" vào "{output}"'
                )
            self.assertTrue(result["ok"])
            execute.assert_called_once_with(str(source), output, model_path=None, sheet_name="")

    def test_excel_then_apply_corrects_misclassified_intent_using_file_types(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            excel = Path(folder) / "BOM.xlsx"
            model = Path(folder) / "Shoe.blend"
            excel.touch()
            model.touch()
            client = FakeClient({"intent": "apply_vbom", "vbom_path": str(model)})
            done = {"ok": True, "status": "completed_with_warnings", "output_path": "result.blend",
                    "warnings": ["PART_NOT_FOUND: example"]}
            with patch.object(agent_run, "execute_jhv", return_value=done) as execute:
                result = agent_run.Agent(client).handle(f'Xuất "{excel}" rồi áp lên "{model}"')
            self.assertEqual(result["status"], "completed_with_warnings")
            self.assertIn("PART_NOT_FOUND", result["message"])
            self.assertEqual(execute.call_args.kwargs["model_path"], str(model))

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

    def test_pending_code_keeps_previous_selection_and_is_single_use(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            directory = Path(folder)
            for name in ("one.xlsx", "two.xlsx", "one.blend", "two.blend"):
                (directory / name).touch()
            client = FakeClient({"intent": "full_pipeline", "input_dir": folder})
            agent = agent_run.Agent(client)
            done = {"ok": True, "status": "completed", "output_path": "result.blend"}
            with patch.object(agent_run, "execute_jhv", return_value=done) as execute:
                first = agent.handle(f'Xử lý BOM trong "{folder}"')
                second = agent.handle(first["continuation_code"] + " two.xlsx")
                self.assertEqual(second["missing"], ["model_path"])
                reply = second["continuation_code"] + " one.blend"
                self.assertTrue(agent.handle(reply)["ok"])
                self.assertFalse(agent.handle(reply)["ok"])
            execute.assert_called_once()
            self.assertEqual(execute.call_args.args[0], str(directory / "two.xlsx"))
            self.assertEqual(execute.call_args.kwargs["model_path"], str(directory / "one.blend"))

    def test_assistant_history_does_not_authorize_execution(self):
        agent = agent_run.Agent(FakeClient({"intent": "chat"}, {"answer": "Giải thích"}))
        history = [{"role": "assistant", "content": "Tôi đã kiểm tra thư mục `inputs`:"}]
        with patch.object(agent_run, "execute_jhv") as execute:
            result = agent.handle("Giải thích cách tạo file BOM", history)
        self.assertEqual(result["status"], "chat")
        execute.assert_not_called()

    def test_small_model_cannot_route_or_select_blender_work(self):
        self.assertEqual(
            agent_run.CONFIG["ollama"]["router_model"],
            agent_run.CONFIG["ollama"]["model"],
        )
        self.assertEqual(
            agent_run.CONFIG["ollama"]["utility_model"],
            agent_run.CONFIG["ollama"]["model"],
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

    def test_agent_source_uses_direct_workflows(self):
        source = Path(agent_run.__file__).read_text(encoding="utf-8")
        self.assertIn("from workflows.core_workflow import", source)


if __name__ == "__main__":
    unittest.main()
