"""Safe client for Blender's official MCP add-on TCP bridge."""

import base64
import hashlib
import json
import os
import socket
import subprocess
import threading
import time
import uuid
from pathlib import Path

from .common import BLENDER, CONFIG, REGISTRY, ROOT

_lock = threading.Lock()
_MAX_RESPONSE_BYTES = 10 * 1024 * 1024


def _b64(value):
    return base64.b64encode(value.encode("utf-8")).decode("ascii")


class BlenderMcpAdapter:
    """Run approved operations through the official local Blender MCP bridge."""

    def __init__(self):
        addon = CONFIG["blender_addon"]
        bridge = CONFIG["official_blender_mcp"]
        self.module = addon["module"]
        self.operator = REGISTRY.require(
            "blender.apply_vbom", provider="blender_addon", handler="apply_vbom"
        )["target"]
        self.timeout = addon.get("timeout_seconds", 180)
        self.host = bridge["host"]
        self.extension_version = bridge["version"]

    @staticmethod
    def _free_port(host):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind((host, 0))
            return listener.getsockname()[1]

    def _command(self, port, model_path=None, modules=None):
        command = [str(BLENDER), "--background", "--online-mode"]
        if model_path is not None:
            command.append(str(model_path))
        addon_modules = modules if modules is not None else [self.module]
        command.extend(
            [
                "--addons",
                ",".join(addon_modules),
                "--command",
                "blender_mcp",
                "--host",
                self.host,
                "--port",
                str(port),
            ]
        )
        return command

    @staticmethod
    def _request(host, port, code, process, timeout):
        payload = json.dumps(
            {"type": "execute", "code": code, "strict_json": True}, ensure_ascii=True
        ).encode("utf-8") + b"\0"
        deadline = time.monotonic() + timeout
        connection = None
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"Blender MCP exited with code {process.returncode}")
            try:
                connection = socket.create_connection((host, port), timeout=1)
                break
            except OSError:
                time.sleep(0.1)
        if connection is None:
            raise TimeoutError("Blender MCP did not start before the timeout")
        with connection:
            connection.settimeout(max(1, deadline - time.monotonic()))
            connection.sendall(payload)
            response = bytearray()
            while b"\0" not in response:
                chunk = connection.recv(65536)
                if not chunk:
                    raise RuntimeError("Blender MCP closed without a complete response")
                response.extend(chunk)
                if len(response) > _MAX_RESPONSE_BYTES:
                    raise RuntimeError("Blender MCP response exceeds the 10 MiB limit")
        result = json.loads(bytes(response[: response.index(b"\0")]))
        if result.get("status") != "ok":
            raise RuntimeError(result.get("message", "Blender MCP execution failed"))
        return result.get("result")

    def _execute(self, code, log_path, model_path=None, timeout=None, modules=None):
        timeout = timeout or self.timeout
        port = self._free_port(self.host)
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        with Path(log_path).open("w", encoding="utf-8") as stream:
            process = subprocess.Popen(
                self._command(port, model_path, modules),
                stdout=stream,
                stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                env=os.environ.copy(),
            )
            try:
                return self._request(self.host, port, code, process, timeout)
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)

    def discover(self, modules, directory):
        if not modules:
            raise ValueError("At least one Blender add-on module is required")
        modules = list(dict.fromkeys(modules))
        directory = Path(directory).resolve()
        directory.mkdir(parents=True, exist_ok=True)
        if not _lock.acquire(blocking=False):
            raise RuntimeError("Blender is busy; wait for the active job to finish")
        try:
            run_id = str(uuid.uuid4())
            report_path = directory / "discovery.json"
            payload = {
                "modules": modules,
                "report_path": str(report_path),
                "run_id": run_id,
            }
            encoded_payload = _b64(json.dumps(payload, ensure_ascii=False))
            runner_directory = _b64(str((ROOT / "blender").resolve()))
            code = (
                "import base64, json, sys\n"
                f"sys.path.insert(0, base64.b64decode('{runner_directory}').decode('utf-8'))\n"
                "from lab_mcp_runner import discover\n"
                f"result = discover(json.loads(base64.b64decode('{encoded_payload}').decode('utf-8')))"
            )
            result = self._execute(
                code,
                directory / "blender-mcp-discovery.log",
                timeout=self.timeout,
                modules=modules,
            )
            if not report_path.is_file():
                raise RuntimeError("Blender MCP did not create the discovery report")
            report = json.loads(report_path.read_text(encoding="utf-8"))
            if result.get("run_id") != run_id or report.get("run_id") != run_id:
                raise RuntimeError("Blender MCP discovery report does not match the current run")
            return report
        finally:
            _lock.release()

    def status(self, directory):
        directory = Path(directory)
        group, action = self.operator.split(".", 1)
        code = (
            "import bpy\n"
            f"result={{'blender_version': bpy.app.version_string, "
            f"'operator_callable': hasattr(bpy.ops.{group}, '{action}')}}"
        )
        result = self._execute(code, directory / "blender-mcp-status.log", timeout=60)
        if not result.get("operator_callable"):
            raise RuntimeError(f"Blender operator is not callable: {self.operator}")
        return {
            "installed": True,
            "addon_loaded": True,
            "official_mcp_callable": True,
            "transport": "official-blender-mcp",
            "mcp_extension_version": self.extension_version,
            "operator": self.operator,
            "executable": str(BLENDER),
            **result,
        }

    def apply(self, vbom_path, model_path, output_path, report_path, run_id):
        if not _lock.acquire(blocking=False):
            raise RuntimeError("Blender is busy; wait for the active job to finish")
        try:
            payload = {
                "vbom_path": str(Path(vbom_path).resolve()),
                "output_path": str(Path(output_path).resolve()),
                "report_path": str(Path(report_path).resolve()),
                "run_id": run_id,
                "operator": self.operator,
            }
            encoded_payload = _b64(json.dumps(payload, ensure_ascii=False))
            runner_directory = _b64(str((ROOT / "blender").resolve()))
            code = (
                "import base64, json, sys\n"
                f"sys.path.insert(0, base64.b64decode('{runner_directory}').decode('utf-8'))\n"
                "from lab_mcp_runner import apply_vbom\n"
                f"result = apply_vbom(json.loads(base64.b64decode('{encoded_payload}').decode('utf-8')))"
            )
            result = self._execute(
                code, Path(report_path).with_name("blender-mcp.log"), model_path=model_path
            )
            if not Path(output_path).is_file() or not Path(report_path).is_file():
                raise RuntimeError("Blender MCP did not create the model and proof report")
            if (
                not result.get("ok")
                or result.get("producer") != "ollama3d-blender-addon"
                or result.get("run_id") != run_id
                or result.get("operator") != self.operator
                or not result.get("verified_after_reopen")
                or result.get("output_sha256")
                != hashlib.sha256(Path(output_path).read_bytes()).hexdigest()
            ):
                raise RuntimeError("Blender MCP proof does not match the current run")
            return result
        finally:
            _lock.release()

    def run_operator(
        self, capability, params, model_path, output_path, report_path, run_id
    ):
        if not _lock.acquire(blocking=False):
            raise RuntimeError("Blender is busy; wait for the active job to finish")
        try:
            modules = REGISTRY.addon_modules()
            for module in (capability["addon_module"], self.module):
                if module not in modules:
                    modules.append(module)
            payload = {
                "operator": capability["target"],
                "params": params,
                "output_path": str(Path(output_path).resolve()),
                "report_path": str(Path(report_path).resolve()),
                "run_id": run_id,
            }
            encoded_payload = _b64(json.dumps(payload, ensure_ascii=False))
            runner_directory = _b64(str((ROOT / "blender").resolve()))
            code = (
                "import base64, json, sys\n"
                f"sys.path.insert(0, base64.b64decode('{runner_directory}').decode('utf-8'))\n"
                "from lab_mcp_runner import run_operator\n"
                f"result = run_operator(json.loads(base64.b64decode('{encoded_payload}').decode('utf-8')))"
            )
            result = self._execute(
                code,
                Path(report_path).with_name("blender-mcp.log"),
                model_path=model_path,
                modules=modules,
            )
            output_path = Path(output_path)
            report_path = Path(report_path)
            if not output_path.is_file() or not report_path.is_file():
                raise RuntimeError("Blender MCP did not create the model and operator report")
            report = json.loads(report_path.read_text(encoding="utf-8"))
            expected_hash = hashlib.sha256(output_path.read_bytes()).hexdigest()
            for proof in (result, report):
                if (
                    not proof.get("ok")
                    or proof.get("producer") != "ollama3d-generic-operator"
                    or proof.get("run_id") != run_id
                    or proof.get("operator") != capability["target"]
                    or not proof.get("verified_after_reopen")
                    or proof.get("transport") != "official-blender-mcp"
                    or proof.get("output_sha256") != expected_hash
                ):
                    raise RuntimeError("Blender MCP operator proof does not match the current run")
            return result
        finally:
            _lock.release()

    def run_workflow(
        self, workflow_id, steps, postconditions, model_path, output_path, report_path, run_id
    ):
        if not _lock.acquire(blocking=False):
            raise RuntimeError("Blender is busy; wait for the active job to finish")
        try:
            modules = []
            for step in steps:
                module = step["capability"]["addon_module"]
                if module not in modules:
                    modules.append(module)
            if self.module not in modules:
                modules.append(self.module)
            runner_steps = [
                {
                    "id": step["id"],
                    "capability_id": step["capability"]["id"],
                    "operator": step["capability"]["target"],
                    "params": step["params"],
                }
                for step in steps
            ]
            payload = {
                "workflow_id": workflow_id,
                "steps": runner_steps,
                "postconditions": postconditions,
                "output_path": str(Path(output_path).resolve()),
                "report_path": str(Path(report_path).resolve()),
                "run_id": run_id,
            }
            encoded_payload = _b64(json.dumps(payload, ensure_ascii=False))
            runner_directory = _b64(str((ROOT / "blender").resolve()))
            code = (
                "import base64, json, sys\n"
                f"sys.path.insert(0, base64.b64decode('{runner_directory}').decode('utf-8'))\n"
                "from lab_mcp_runner import run_steps\n"
                f"result = run_steps(json.loads(base64.b64decode('{encoded_payload}').decode('utf-8')))"
            )
            result = self._execute(
                code,
                Path(report_path).with_name("blender-mcp.log"),
                model_path=model_path,
                modules=modules,
            )
            output_path = Path(output_path)
            report_path = Path(report_path)
            if not output_path.is_file() or not report_path.is_file():
                raise RuntimeError("Blender MCP did not create the workflow model and report")
            report = json.loads(report_path.read_text(encoding="utf-8"))
            expected_hash = hashlib.sha256(output_path.read_bytes()).hexdigest()
            for proof in (result, report):
                if (
                    not proof.get("ok")
                    or proof.get("producer") != "ollama3d-generic-workflow"
                    or proof.get("workflow_id") != workflow_id
                    or proof.get("run_id") != run_id
                    or not proof.get("verified_after_reopen")
                    or proof.get("transport") != "official-blender-mcp"
                    or proof.get("output_sha256") != expected_hash
                ):
                    raise RuntimeError("Blender MCP workflow proof does not match the current run")
            return result
        finally:
            _lock.release()

    def create_colored_primitive(
        self, primitive, color_hex, size, object_name, output_path, report_path, run_id
    ):
        if not _lock.acquire(blocking=False):
            raise RuntimeError("Blender is busy; wait for the active job to finish")
        try:
            payload = {
                "primitive": primitive,
                "color_hex": color_hex,
                "size": size,
                "object_name": object_name,
                "output_path": str(Path(output_path).resolve()),
                "report_path": str(Path(report_path).resolve()),
                "run_id": run_id,
            }
            encoded_payload = _b64(json.dumps(payload, ensure_ascii=False))
            runner_directory = _b64(str((ROOT / "blender").resolve()))
            code = (
                "import base64, json, sys\n"
                f"sys.path.insert(0, base64.b64decode('{runner_directory}').decode('utf-8'))\n"
                "from lab_mcp_runner import create_colored_primitive\n"
                f"result = create_colored_primitive(json.loads(base64.b64decode('{encoded_payload}').decode('utf-8')))"
            )
            result = self._execute(
                code, Path(report_path).with_name("blender-mcp.log"), timeout=self.timeout
            )
            if not Path(output_path).is_file() or not Path(report_path).is_file():
                raise RuntimeError("Blender MCP did not create the primitive and proof report")
            if (
                not result.get("ok")
                or result.get("run_id") != run_id
                or result.get("primitive") != primitive
                or result.get("color_hex") != color_hex
                or not result.get("verified_after_reopen")
                or result.get("transport") != "official-blender-mcp"
                or result.get("output_sha256")
                != hashlib.sha256(Path(output_path).read_bytes()).hexdigest()
            ):
                raise RuntimeError("Blender primitive proof does not match the current run")
            return result
        finally:
            _lock.release()
