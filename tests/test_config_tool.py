"""Check configurable path boundaries and the real HTTP client contract with mock servers."""

import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from project_config import load, scoped_path, endpoint, data_path
from webui_tool import Tools
from adapters.operators import list_operators, run_operator


class Configuration(unittest.TestCase):
    def test_external_configured_folders_and_traversal(self):
        with tempfile.TemporaryDirectory(prefix="bom config ") as folder:
            config = load()
            config["paths"]["inputs"] = folder + "/input"
            config["paths"]["outputs"] = folder + "/output"
            config["paths"]["default_model"] = folder + "/models/item.blend"
            for path in (
                folder + "/input/a.xlsx",
                folder + "/output/run/a.vbom",
                folder + "/models/item.blend",
            ):
                self.assertEqual(scoped_path(config, path), Path(path).resolve())
            for path in (
                folder + "/input/../private.xlsx",
                folder + "/models/secret.blend",
                "../",
                "webui-data",
                ".venv",
            ):
                with self.assertRaises(ValueError):
                    scoped_path(config, path)

    def test_http_provider_requires_a_valid_url(self):
        config = load()
        config["workflow"]["export"] = {"provider": "http", "url": "", "token_env": ""}
        with self.assertRaisesRegex(ValueError, "workflow.export.url"):
            endpoint(config, "export")

    def test_invalid_config_ports(self):
        with tempfile.TemporaryDirectory() as folder:
            config = load()
            config.pop("_root")
            config["services"]["webui_port"] = config["services"]["api_port"]
            path = Path(folder) / "config.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "different"):
                load(path)

    def test_operator_allowlist_and_parameter_validation(self):
        listed = list_operators()["operators"]
        rhino = next(item for item in listed if item["id"] == "start_rhino_server")
        self.assertEqual(rhino["operator"], "blender_rhino_server.start")
        self.assertEqual(rhino["parameters"]["server_port"]["default"], 55555)
        with self.assertRaisesRegex(ValueError, "Unknown or disabled"):
            run_operator("made_up_operator", {})
        with self.assertRaisesRegex(ValueError, "Unknown parameters"):
            run_operator("start_rhino_server", {"shell_command": "bad"})
        with self.assertRaisesRegex(ValueError, "one of"):
            run_operator("start_rhino_server", {"server_adr": "0.0.0.0"})
        with self.assertRaisesRegex(ValueError, "at most"):
            run_operator("start_rhino_server", {"server_port": 70000})


class ToolRouting(unittest.IsolatedAsyncioTestCase):
    async def test_distinct_company_servers_and_defaults(self):
        tool = Tools()
        config = copy.deepcopy(load())
        for operation, host, route in [
            ("files", "files.test", "/list"),
            ("export", "excel.test", "/export"),
            ("apply", "blender.test", "/apply"),
            ("result", "jobs.test", "/jobs/{run_id}"),
        ]:
            config["workflow"][operation] = {
                "provider": "http",
                "url": "https://" + host + route,
                "token_env": "TEST_BOM_TOKEN" if operation == "export" else "",
            }
        calls = []

        def handle(request):
            calls.append(request)
            return httpx.Response(200, json={"ok": True, "status": "completed"})

        real_client = httpx.AsyncClient

        def client(**kwargs):
            return real_client(transport=httpx.MockTransport(handle), **kwargs)

        with patch.object(tool._config, "load", return_value=config), patch(
            "webui_tool.httpx.AsyncClient", side_effect=client
        ), patch.dict(os.environ, {"TEST_BOM_TOKEN": "test-only"}):
            self.assertTrue(json.loads(await tool.list_demo_files())["ok"])
            self.assertTrue(
                json.loads(await tool._export_excel_to_vbom("C:/data/a.xlsx"))["ok"]
            )
            self.assertTrue(
                json.loads(
                    await tool._apply_vbom_in_blender(
                        "C:/out/a.vbom", open_window=False
                    )
                )["ok"]
            )
            self.assertTrue(
                json.loads(await tool._get_run_result("company-job_42"))["ok"]
            )
        self.assertEqual(
            [r.url.host for r in calls],
            ["files.test", "excel.test", "blender.test", "jobs.test"],
        )
        self.assertEqual(
            calls[0].url.params["input_dir"], str(data_path(config, "inputs"))
        )
        self.assertEqual(
            json.loads(calls[1].content)["output_dir"],
            str(data_path(config, "outputs")),
        )
        self.assertEqual(calls[1].headers["Authorization"], "Bearer test-only")
        self.assertNotIn("Authorization", calls[2].headers)
        self.assertFalse(json.loads(calls[2].content)["open_window"])
        self.assertEqual(calls[3].url.path, "/jobs/company-job_42")

    async def test_mixed_providers_keep_local_blender_tools(self):
        tool = Tools()
        config = copy.deepcopy(load())
        config["profile"] = "mixed-company"
        config["workflow"]["export"] = {
            "provider": "http",
            "url": "https://excel.test/export",
            "token_env": "",
        }
        self.assertEqual(
            endpoint(config, "files")["url"], "http://127.0.0.1:8090/files"
        )
        self.assertEqual(endpoint(config, "export")["url"], "https://excel.test/export")
        self.assertEqual(
            endpoint(config, "operators")["url"],
            "http://127.0.0.1:8090/blender/operators",
        )

    async def test_addon_tools_use_allowlist_api(self):
        tool = Tools()
        calls = []
        real_client = httpx.AsyncClient

        def handle(request):
            calls.append(request)
            return httpx.Response(200, json={"ok": True})

        with patch(
            "webui_tool.httpx.AsyncClient",
            side_effect=lambda **kw: real_client(
                transport=httpx.MockTransport(handle), **kw
            ),
        ):
            self.assertTrue(json.loads(await tool.list_blender_addons())["ok"])
            result = await tool.run_blender_addon(
                "start_rhino_server", '{"server_port":55555}'
            )
            self.assertTrue(json.loads(result)["ok"])
        self.assertEqual(calls[0].url.path, "/blender/operators")
        self.assertEqual(calls[1].url.path, "/blender/operators/run")
        self.assertEqual(
            json.loads(calls[1].content)["parameters"], {"server_port": 55555}
        )
        invalid = json.loads(await tool.run_blender_addon("start_rhino_server", "[]"))
        self.assertFalse(invalid["ok"])

    async def test_errors_and_timeout_are_not_success(self):
        tool = Tools()
        real_client = httpx.AsyncClient
        for response in [
            httpx.Response(500, json={"detail": "broken"}),
            httpx.Response(200, json=["unexpected"]),
            httpx.Response(
                302, json={}, headers={"location": "https://elsewhere.test"}
            ),
        ]:
            with patch(
                "webui_tool.httpx.AsyncClient",
                side_effect=lambda **kw: real_client(
                    transport=httpx.MockTransport(lambda r: response), **kw
                ),
            ):
                self.assertFalse(
                    json.loads(await tool._export_excel_to_vbom("a.xlsx"))["ok"]
                )

        def timeout(request):
            raise httpx.ReadTimeout("test timeout", request=request)

        with patch(
            "webui_tool.httpx.AsyncClient",
            side_effect=lambda **kw: real_client(
                transport=httpx.MockTransport(timeout), **kw
            ),
        ):
            result = json.loads(await tool._apply_vbom_in_blender("a.vbom"))
            self.assertFalse(result["ok"])
        self.assertIn("job", result["error"])
        self.assertIn("force_new", result["error"])


if __name__ == "__main__":
    unittest.main()
