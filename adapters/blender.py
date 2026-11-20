"""Safe subprocess adapter for allowlisted Blender add-on operations."""

import hashlib
import json
import os
import subprocess
import threading
import time
import uuid
from pathlib import Path

from .common import BLENDER, CONFIG, REGISTRY, ROOT, write_json

_lock = threading.Lock()


class BlenderJobError(RuntimeError):
    def __init__(self, message, code=None, details=None):
        super().__init__(message)
        self.code = code or "BLENDER_EXECUTION_FAILED"
        self.details = details or {}


class BlenderAdapter:
    """Run approved operations in a short-lived local Blender process."""

    def __init__(self):
        self.timeout = CONFIG["blender"]["timeout_seconds"]

    @property
    def transport_name(self):
        return "blender-subprocess"

    def _subprocess_command(
        self, job_path, result_path, model_path=None, modules=None, factory_startup=False
    ):
        command = [str(BLENDER), "--background"]
        if factory_startup:
            command.append("--factory-startup")
        if model_path is not None:
            command.append(str(model_path))
        addon_modules = modules if modules is not None else REGISTRY.addon_modules()
        if addon_modules:
            command.extend(["--addons", ",".join(addon_modules)])
        command.extend(
            [
                "--python-exit-code",
                "1",
                "--python",
                str(ROOT / "blender" / "job_entry.py"),
                "--",
                str(job_path),
                str(result_path),
            ]
        )
        return command

    def _run_job(
        self, operation, payload, log_path, model_path=None, timeout=None, modules=None
    ):
        timeout = timeout or self.timeout
        payload = dict(payload)
        payload["transport"] = self.transport_name

        job_directory = ROOT / "runtime" / "blender-jobs"
        job_directory.mkdir(parents=True, exist_ok=True)
        job_id = uuid.uuid4().hex
        job_path = job_directory / f"{job_id}.job.json"
        result_path = job_directory / f"{job_id}.result.json"
        job_path.write_text(
            json.dumps({"operation": operation, "payload": payload}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        started = time.perf_counter()
        try:
            with Path(log_path).open("w", encoding="utf-8") as stream:
                completed = subprocess.run(
                    self._subprocess_command(
                        job_path, result_path, model_path=model_path, modules=modules
                    ),
                    stdout=stream,
                    stderr=subprocess.STDOUT,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    env=os.environ.copy(),
                    timeout=timeout,
                    check=False,
                )
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError("Blender subprocess exceeded the timeout") from exc
        if not result_path.is_file():
            raise RuntimeError(f"Blender subprocess exited with code {completed.returncode} without a result")
        envelope = json.loads(result_path.read_text(encoding="utf-8"))
        seconds = round(time.perf_counter() - started, 3)
        with Path(log_path).open("a", encoding="utf-8") as stream:
            stream.write(f"\n[PERF] blender_subprocess_wall: {seconds:.3f}s\n")
        if completed.returncode != 0 or not envelope.get("ok"):
            raise BlenderJobError(
                envelope.get("error", f"Blender subprocess exited with code {completed.returncode}"),
                envelope.get("error_code"), envelope.get("details"),
            )
        result = envelope["result"]
        if operation in ("run_operator", "run_steps") and isinstance(result, dict):
            result.setdefault("timings", {})["blender_subprocess_wall_seconds"] = seconds
        return result

    def refresh_jhv_index(self):
        if not _lock.acquire(blocking=False):
            raise RuntimeError("Blender is busy; wait for the active job to finish")
        try:
            return self._run_job(
                "refresh_jhv_index", {},
                ROOT / "runtime" / "blender-subprocess-jhv-index.log",
                timeout=max(self.timeout, 1800), modules=["jhv_dpc"],
            )
        finally:
            _lock.release()

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
            result = self._run_job(
                "discover",
                payload,
                directory / "blender-subprocess-discovery.log",
                timeout=self.timeout,
                modules=modules,
            )
            if not report_path.is_file():
                raise RuntimeError("Blender job did not create the discovery report")
            report = json.loads(report_path.read_text(encoding="utf-8"))
            if result.get("run_id") != run_id or report.get("run_id") != run_id:
                raise RuntimeError("Blender discovery report does not match the current run")
            return report
        finally:
            _lock.release()
    def status(self, directory):
        directory = Path(directory)
        result = self._run_job(
            "status",
            {"operators": [item["target"] for item in REGISTRY.generic_capabilities()]},
            directory / "blender-subprocess-status.log",
            timeout=60,
        )
        return {
            "installed": True,
            "addon_loaded": any(result.get("operators", {}).values()),
            "transport_callable": True,
            "executable": str(BLENDER),
            **result,
        }

    def run_operator(
        self, capability, params, model_path, output_path, report_path, run_id
    ):
        if not _lock.acquire(blocking=False):
            raise RuntimeError("Blender is busy; wait for the active job to finish")
        try:
            modules = REGISTRY.addon_modules()
            for module in (capability["addon_module"],):
                if module not in modules:
                    modules.append(module)
            payload = {
                "operator": capability["target"],
                "params": params,
                "output_path": str(Path(output_path).resolve()),
                "report_path": str(Path(report_path).resolve()),
                "run_id": run_id,
            }
            result = self._run_job(
                "run_operator",
                payload,
                Path(report_path).with_name("blender-subprocess.log"),
                model_path=model_path,
                modules=modules,
            )
            output_path = Path(output_path)
            report_path = Path(report_path)
            if not output_path.is_file() or not report_path.is_file():
                raise RuntimeError("Blender job did not create the model and operator report")
            report = json.loads(report_path.read_text(encoding="utf-8"))
            expected_hash = hashlib.sha256(output_path.read_bytes()).hexdigest()
            for proof in (result, report):
                if (
                    not proof.get("ok")
                    or proof.get("producer") != "ollama3d-generic-operator"
                    or proof.get("run_id") != run_id
                    or proof.get("operator") != capability["target"]
                    or not proof.get("verified_after_reopen")
                    or proof.get("transport") != self.transport_name
                    or proof.get("output_sha256") != expected_hash
                ):
                    raise RuntimeError("Blender operator proof does not match the current run")
            if "asset_resolver" in report:
                report["timings"]["blender_subprocess_wall_seconds"] = result["timings"]["blender_subprocess_wall_seconds"]
                write_json(report_path, report)
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
            result = self._run_job(
                "run_steps",
                payload,
                Path(report_path).with_name("blender-subprocess.log"),
                model_path=model_path,
                modules=modules,
            )
            output_path = Path(output_path)
            report_path = Path(report_path)
            if not output_path.is_file() or not report_path.is_file():
                raise RuntimeError("Blender job did not create the workflow model and report")
            report = json.loads(report_path.read_text(encoding="utf-8"))
            expected_hash = hashlib.sha256(output_path.read_bytes()).hexdigest()
            for proof in (result, report):
                if (
                    not proof.get("ok")
                    or proof.get("producer") != "ollama3d-generic-workflow"
                    or proof.get("workflow_id") != workflow_id
                    or proof.get("run_id") != run_id
                    or not proof.get("verified_after_reopen")
                    or proof.get("transport") != self.transport_name
                    or proof.get("output_sha256") != expected_hash
                ):
                    raise RuntimeError("Blender workflow proof does not match the current run")
            return result
        finally:
            _lock.release()
