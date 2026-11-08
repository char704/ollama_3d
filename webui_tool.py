"""
title: Excel to Blender
author: Local prototype
description: Configurable HTTP clients for Excel and Blender APIs.
version: 2.1.0
"""
import importlib.util
import json
import os
import re
from pathlib import Path
import httpx

_CONFIG_FILE = '__PROJECT_CONFIG_FILE__'


class Tools:
    def __init__(self):
        self.citation = False
        path = Path(_CONFIG_FILE) if _CONFIG_FILE != '__PROJECT_' + 'CONFIG_FILE__' else Path(__file__).with_name('config.json')
        spec = importlib.util.spec_from_file_location('_excel_blender_config', path.with_name('project_config.py'))
        self._config = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self._config)
        self._config_file = path

    async def _request(self, operation, method, body=None, params=None, run_id=None, emitter=None):
        if emitter:
            await emitter({'type':'status','data':{'description':f'Calling {operation} API','done':False}})
        try:
            config = self._config.load(self._config_file)
            endpoint = self._config.endpoint(config, operation)
            url = endpoint['url'].replace('{run_id}', run_id or '')
            headers = {}
            token_env = endpoint.get('token_env', '')
            if token_env:
                token = os.environ.get(token_env)
                if not token:
                    raise ValueError(f'Missing environment variable: {token_env}. Set it, then restart Open WebUI.')
                headers['Authorization'] = 'Bearer ' + token
            defaults = {'input_dir':'inputs', 'output_dir':'outputs', 'model_path':'default_model'}
            for values in (body, params):
                if values is not None:
                    for key, setting in defaults.items():
                        if key in values and not values[key]:
                            values[key] = str(self._config.data_path(config, setting))
            async with httpx.AsyncClient(timeout=210, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, url, json=body, params=params, headers=headers)
                result = response.json()
                if response.is_error or response.is_redirect:
                    detail = result.get('error', result.get('detail', result)) if isinstance(result, dict) else result
                    result = {'ok':False, 'http_status':response.status_code, 'error':detail}
                elif not isinstance(result, dict) or 'ok' not in result:
                    result = {'ok':False, 'error':'API response must be a JSON object containing ok; check the API contract.'}
        except httpx.TimeoutException:
            result = {'ok':False,'error':'API timed out; check get_run_result before retrying Blender.'}
        except Exception as exc:
            result = {'ok':False,'error':str(exc),'help':'Check config.json and Status.cmd. Restart with Open-WebUI.cmd after configuration changes.'}
        if emitter:
            await emitter({'type':'status','data':{'description':('Finished: ' if result.get('ok') else 'Failed: ')+operation,'done':True}})
        return json.dumps(result, ensure_ascii=False)

    async def list_demo_files(self, input_dir: str = '', __event_emitter__=None) -> str:
        """Find Excel and Blender files. Call first; use the returned full paths.
        :param input_dir: User-requested input directory. Empty uses inputs from config.json.
        """
        return await self._request('files','GET',params={'input_dir':input_dir},emitter=__event_emitter__)

    async def export_excel_to_vbom(self, excel_path: str, output_dir: str = '', __event_emitter__=None) -> str:
        """Call the Excel API to export VBOM. Wait for ok=true before applying; returns vbom_path and run_id.
        :param excel_path: Exact Excel path from list_demo_files, matching the requested filename.
        :param output_dir: User-requested output directory. Empty uses outputs from config.json. Demo creates a unique run subfolder.
        """
        return await self._request('export','POST',body={'excel_path':excel_path,'output_dir':output_dir},emitter=__event_emitter__)

    async def apply_vbom_in_blender(self, vbom_path: str, model_path: str = '', open_window: bool = True, __event_emitter__=None) -> str:
        """Call the Blender API to import VBOM, apply materials and colors, save and verify. Demo saves next to the VBOM.
        :param vbom_path: Exact vbom_path from a successful export. Never invent this path.
        :param model_path: Full model path from list_demo_files. Empty uses default_model from config.json.
        :param open_window: True to open the result in Blender; false for background processing.
        """
        return await self._request('apply','POST',body={'vbom_path':vbom_path,'model_path':model_path,'open_window':open_window},emitter=__event_emitter__)

    async def get_run_result(self, run_id: str, __event_emitter__=None) -> str:
        """Read previous export/apply status without running again. Use after timeouts.
        :param run_id: Exact run_id from export_excel_to_vbom.
        """
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', run_id):
            return json.dumps({'ok':False,'error':'Invalid run_id'})
        return await self._request('result','GET',run_id=run_id,emitter=__event_emitter__)
