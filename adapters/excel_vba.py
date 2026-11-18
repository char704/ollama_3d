"""Real Excel VBA adapter executed in a timeout-controlled child process."""

import hashlib
import subprocess
import sys
import uuid
from pathlib import Path

import psutil

from .common import CONFIG, ROOT, read_json
from project_config import resolve


class ExcelVbaAdapter:
    def __init__(self):
        settings = CONFIG["excel_vba"]
        self.executable = Path(settings["executable"])
        self.addin_path = resolve(CONFIG, settings["addin_path"])
        self.ping_macro = settings["ping_macro"]
        self.export_macro = settings["export_macro"]
        self.timeout = settings["timeout_seconds"]

    @staticmethod
    def _terminate_excel(control_path):
        if not control_path.is_file():
            return
        try:
            pid = int(read_json(control_path)["excel_pid"])
            process = psutil.Process(pid)
            if process.name().casefold() == "excel.exe":
                process.terminate()
                process.wait(timeout=10)
        except (KeyError, ValueError, psutil.Error):
            pass

    def _invoke(self, mode, macro, arguments=()):
        if not self.executable.is_file():
            raise FileNotFoundError("Excel executable not found: " + str(self.executable))
        if not self.addin_path.is_file():
            raise FileNotFoundError("Excel VBA add-in not found: " + str(self.addin_path))
        worker_directory = ROOT / "runtime" / "excel-workers" / uuid.uuid4().hex
        worker_directory.mkdir(parents=True)
        result_path = worker_directory / "result.json"
        control_path = worker_directory / "control.json"
        command = [
            sys.executable,
            str(ROOT / "scripts" / "excel_vba_worker.py"),
            mode,
            str(self.executable),
            str(self.addin_path),
            macro,
            str(result_path),
            str(control_path),
            *[str(value) for value in arguments],
        ]
        try:
            completed = subprocess.run(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=self.timeout,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except subprocess.TimeoutExpired as exc:
            self._terminate_excel(control_path)
            raise RuntimeError(
                f"Excel VBA timed out after {self.timeout} seconds"
            ) from exc
        if not result_path.is_file():
            self._terminate_excel(control_path)
            raise RuntimeError("Excel worker exited without a result")
        result = read_json(result_path)
        if completed.returncode or not result.get("ok"):
            self._terminate_excel(control_path)
            raise RuntimeError(result.get("error", "Excel VBA worker failed"))
        return result

    def status(self):
        result = self._invoke("status", self.ping_macro)
        value = str(result["value"])
        if not value.startswith("ollama3d-proof|"):
            raise RuntimeError("Unexpected VBA add-in identity: " + value)
        return {
            "installed": True,
            "com_ready": True,
            "addin_loaded": True,
            "macro_callable": True,
            "addin_version": value.split("|", 1)[1],
            "executable": str(self.executable),
            "addin_path": str(self.addin_path),
            "excel_pid": result["excel_pid"],
        }

    def export(self, source, run_directory, run_id):
        source = Path(source)
        run_directory = Path(run_directory)
        result = self._invoke(
            "export", self.export_macro, (source, run_directory, run_id)
        )
        vbom_path = Path(result["value"]).resolve()
        proof_path = run_directory / "excel-proof.json"
        if vbom_path != (run_directory / "materials.vbom").resolve():
            raise RuntimeError("VBA returned an unexpected VBOM path: " + str(vbom_path))
        if not vbom_path.is_file() or not proof_path.is_file():
            raise RuntimeError("VBA did not create materials.vbom and excel-proof.json")
        proof = read_json(proof_path)
        if proof.get("producer") != "ollama3d-vba" or proof.get("run_id") != run_id:
            raise RuntimeError("Excel proof does not match the current run")
        if Path(proof.get("vbom_path", "")).resolve() != vbom_path:
            raise RuntimeError("Excel proof contains a different VBOM path")
        return {
            "ok": True,
            "status": "exported",
            "producer": proof["producer"],
            "addin_version": proof["addin_version"],
            "excel_pid": result["excel_pid"],
            "source_excel": str(source),
            "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "vbom_path": str(vbom_path),
            "vbom_sha256": hashlib.sha256(vbom_path.read_bytes()).hexdigest(),
            "proof_path": str(proof_path),
            "items": proof["items"],
        }
