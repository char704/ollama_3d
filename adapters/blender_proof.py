"""Real Blender process adapter for the installed Ollama3D proof add-on."""

import json
import subprocess
import threading
from pathlib import Path

from .common import BLENDER, CONFIG, ROOT, read_json

_lock = threading.Lock()


class BlenderProofAdapter:
    def __init__(self):
        settings = CONFIG["blender_addon"]
        self.module = settings["module"]
        self.operator = settings["operator"]
        self.timeout = settings.get("timeout_seconds", 180)

    @staticmethod
    def _run(command, log_path, timeout):
        with Path(log_path).open("w", encoding="utf-8") as stream:
            process = subprocess.run(
                command,
                stdout=stream,
                stderr=subprocess.STDOUT,
                timeout=timeout,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        if process.returncode:
            raise RuntimeError("Blender failed. See " + str(log_path))

    def status(self, directory):
        directory = Path(directory)
        report = directory / "blender-status.json"
        log_path = directory / "blender-status.log"
        command = [
            str(BLENDER),
            "--background",
            "--factory-startup",
            "--addons",
            self.module,
            "--python-exit-code",
            "1",
            "--python",
            str(ROOT / "blender" / "probe_proof_addon.py"),
            "--",
            str(report),
            self.module,
            self.operator,
        ]
        self._run(command, log_path, 60)
        result = read_json(report)
        if not result.get("ok"):
            raise RuntimeError(result.get("error", "Blender add-on probe failed"))
        return {
            "installed": True,
            "addon_loaded": True,
            **result,
            "executable": str(BLENDER),
        }

    def apply(self, vbom_path, model_path, output_path, report_path, run_id):
        if not _lock.acquire(blocking=False):
            raise RuntimeError("Blender is busy; wait for the active job to finish")
        try:
            log_path = Path(report_path).with_name("blender.log")
            command = [
                str(BLENDER),
                "--background",
                "--factory-startup",
                str(model_path),
                "--addons",
                self.module,
                "--python-exit-code",
                "1",
                "--python",
                str(ROOT / "blender" / "apply_proof_vbom.py"),
                "--",
                str(vbom_path),
                str(output_path),
                str(report_path),
                run_id,
                self.operator,
            ]
            self._run(command, log_path, self.timeout)
            if not Path(output_path).is_file() or not Path(report_path).is_file():
                raise RuntimeError("Blender did not create the model and proof report")
            result = read_json(report_path)
            if (
                not result.get("ok")
                or result.get("producer") != "ollama3d-blender-addon"
                or result.get("run_id") != run_id
                or result.get("operator") != self.operator
                or not result.get("verified_after_reopen")
            ):
                raise RuntimeError("Blender proof does not match the current run")
            return result
        finally:
            _lock.release()
