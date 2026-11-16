"""
title: Excel to Blender
author: Local prototype
description: Configurable HTTP clients for Excel and Blender APIs.
version: 3.0.0
"""

import importlib.util
import json
import os
import re
import sys
from pathlib import Path
import httpx

_CONFIG_FILE = "__PROJECT_CONFIG_FILE__"


class Tools:
    def __init__(self):
        self.citation = False
        path = (
            Path(_CONFIG_FILE)
            if _CONFIG_FILE != "__PROJECT_" + "CONFIG_FILE__"
            else Path(__file__).with_name("config.json")
        )
        project_directory = str(path.resolve().parent)
        if project_directory not in sys.path:
            sys.path.insert(0, project_directory)
        spec = importlib.util.spec_from_file_location(
            "_excel_blender_config", path.with_name("project_config.py")
        )
        self._config = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self._config)
        self._config_file = path

    async def _request(
        self, operation, method, body=None, params=None, run_id=None, emitter=None
    ):
        if emitter:
            await emitter(
                {
                    "type": "status",
                    "data": {"description": f"Calling {operation} API", "done": False},
                }
            )
        try:
            config = self._config.load(self._config_file)
            endpoint = self._config.endpoint(config, operation)
            url = endpoint["url"].replace("{run_id}", run_id or "")
            headers = {}
            token_env = endpoint.get("token_env", "")
            if token_env:
                token = os.environ.get(token_env)
                if not token:
                    raise ValueError(
                        f"Missing environment variable: {token_env}. Set it, then restart Open WebUI."
                    )
                headers["Authorization"] = "Bearer " + token
            defaults = {
                "input_dir": "inputs",
                "output_dir": "outputs",
                "model_path": "default_model",
            }
            for values in (body, params):
                if values is not None:
                    for key, setting in defaults.items():
                        if key in values and not values[key]:
                            values[key] = str(self._config.data_path(config, setting))
            async with httpx.AsyncClient(
                timeout=210, trust_env=False, follow_redirects=False
            ) as client:
                response = await client.request(
                    method, url, json=body, params=params, headers=headers
                )
                result = response.json()
                if response.is_error or response.is_redirect:
                    detail = (
                        result.get("error", result.get("detail", result))
                        if isinstance(result, dict)
                        else result
                    )
                    result = {
                        "ok": False,
                        "http_status": response.status_code,
                        "error": detail,
                    }
                elif not isinstance(result, dict) or "ok" not in result:
                    result = {
                        "ok": False,
                        "error": "API response must be a JSON object containing ok; check the API contract.",
                    }
        except httpx.TimeoutException:
            result = {
                "ok": False,
                "error": "API timed out; inspect the relevant workflow or Blender job before retrying. Do not enable force_new blindly.",
            }
        except Exception as exc:
            result = {
                "ok": False,
                "error": str(exc),
                "help": "Check config.json and Status.cmd. Restart with Open-WebUI.cmd after configuration changes.",
            }
        if emitter:
            await emitter(
                {
                    "type": "status",
                    "data": {
                        "description": (
                            "Finished: " if result.get("ok") else "Failed: "
                        )
                        + operation,
                        "done": True,
                    },
                }
            )
        return json.dumps(result, ensure_ascii=False)

    async def list_demo_files(self, input_dir: str = "", __event_emitter__=None) -> str:
        """Find Excel and Blender files. Call first; use the returned full paths.
        :param input_dir: User-requested input directory. Empty uses inputs from config.json.
        """
        return await self._request(
            "files", "GET", params={"input_dir": input_dir}, emitter=__event_emitter__
        )

    async def run_bom_pipeline(
        self,
        excel_path: str,
        model_path: str = "",
        output_dir: str = "",
        open_result: bool = True,
        force_new: bool = False,
        __event_emitter__=None,
    ) -> str:
        """Run the complete deterministic Excel -> VBOM -> Blender -> verify workflow. Prefer this for a normal end-to-end request.
        :param excel_path: Exact Excel path returned by list_demo_files.
        :param model_path: Exact Blender model path, or empty for the configured default.
        :param output_dir: Requested output directory, or empty for the configured default.
        :param open_result: True to open the completed Blender model.
        :param force_new: False reuses an identical active/completed workflow; true runs it again only when the user explicitly asks.
        """
        return await self._request(
            "bom_pipeline",
            "POST",
            body={
                "excel_path": excel_path,
                "model_path": model_path,
                "output_dir": output_dir,
                "open_result": open_result,
                "force_new": force_new,
            },
            emitter=__event_emitter__,
        )

    async def get_bom_pipeline_job(self, job_id: str, __event_emitter__=None) -> str:
        """Read a previous BOM workflow state without executing it again.
        :param job_id: Exact 32-character workflow job_id returned by run_bom_pipeline.
        """
        if not re.fullmatch(r"[a-f0-9]{32}", job_id):
            return json.dumps({"ok": False, "error": "Invalid workflow job_id"})
        return await self._request(
            "bom_pipeline_job", "GET", run_id=job_id, emitter=__event_emitter__
        )

    async def _export_excel_to_vbom(
        self, excel_path: str, output_dir: str = "", __event_emitter__=None
    ) -> str:
        """Call the Excel API to export VBOM. Wait for ok=true before applying; returns vbom_path and run_id.
        :param excel_path: Exact Excel path from list_demo_files, matching the requested filename.
        :param output_dir: User-requested output directory. Empty uses outputs from config.json. Demo creates a unique run subfolder.
        """
        return await self._request(
            "export",
            "POST",
            body={"excel_path": excel_path, "output_dir": output_dir},
            emitter=__event_emitter__,
        )

    async def _apply_vbom_in_blender(
        self,
        vbom_path: str,
        model_path: str = "",
        open_window: bool = True,
        __event_emitter__=None,
    ) -> str:
        """Call the Blender API to import VBOM, apply materials and colors, save and verify. Demo saves next to the VBOM.
        :param vbom_path: Exact vbom_path from a successful export. Never invent this path.
        :param model_path: Full model path from list_demo_files. Empty uses default_model from config.json.
        :param open_window: True to open the result in Blender; false for background processing.
        """
        return await self._request(
            "apply",
            "POST",
            body={
                "vbom_path": vbom_path,
                "model_path": model_path,
                "open_window": open_window,
            },
            emitter=__event_emitter__,
        )

    async def list_blender_addons(self, __event_emitter__=None) -> str:
        """List the approved Blender add-ons/operators, what each one does, and its accepted parameters. Call this before choosing an optional company add-on."""
        return await self._request("operators", "GET", emitter=__event_emitter__)

    async def run_blender_addon(
        self,
        operator_id: str,
        parameters_json: str = "{}",
        model_path: str = "",
        __event_emitter__=None,
    ) -> str:
        """Run one approved Blender add-on/operator selected from list_blender_addons. Never invent an id or parameter.
        :param operator_id: Exact id returned by list_blender_addons.
        :param parameters_json: JSON object containing only the documented parameters, for example {"server_port":55555}. Use {} for defaults.
        :param model_path: Blender model path only when the selected entry says load_model=true; otherwise leave empty.
        """
        try:
            parameters = json.loads(parameters_json)
            if not isinstance(parameters, dict):
                raise ValueError("parameters_json must contain a JSON object")
        except (json.JSONDecodeError, ValueError) as exc:
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
        return await self._request(
            "run_operator",
            "POST",
            body={
                "operator_id": operator_id,
                "parameters": parameters,
                "model_path": model_path,
                "wait_for_completion": True,
            },
            emitter=__event_emitter__,
        )

    async def get_blender_job(self, job_id: str, __event_emitter__=None) -> str:
        """Read the current state and result of a queued Blender Agent job after a timeout.
        :param job_id: Exact 32-character job_id returned by run_blender_addon.
        """
        if not re.fullmatch(r"[a-f0-9]{32}", job_id):
            return json.dumps({"ok": False, "error": "Invalid Blender Agent job_id"})
        return await self._request(
            "agent_job", "GET", run_id=job_id, emitter=__event_emitter__
        )

    async def cancel_blender_job(self, job_id: str, __event_emitter__=None) -> str:
        """Cancel a queued Blender Agent job. A running or completed job cannot be cancelled.
        :param job_id: Exact 32-character job_id returned by run_blender_addon.
        """
        if not re.fullmatch(r"[a-f0-9]{32}", job_id):
            return json.dumps({"ok": False, "error": "Invalid Blender Agent job_id"})
        return await self._request(
            "cancel_agent_job", "POST", run_id=job_id, emitter=__event_emitter__
        )

    async def _get_run_result(self, run_id: str, __event_emitter__=None) -> str:
        """Read previous export/apply status without running again. Use after timeouts.
        :param run_id: Exact run_id from export_excel_to_vbom.
        """
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", run_id):
            return json.dumps({"ok": False, "error": "Invalid run_id"})
        return await self._request(
            "result", "GET", run_id=run_id, emitter=__event_emitter__
        )
