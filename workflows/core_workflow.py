"""Non-mutating readiness probe for the local agent."""
from pathlib import Path

import httpx
from adapters.blender import BlenderAdapter
from adapters.common import CONFIG, REGISTRY, ROOT, log
from project_config import service_url


def system_status():
    REGISTRY.require("system.status", provider="system", handler="system_status")
    probe_directory = ROOT / "runtime" / "probes"
    probe_directory.mkdir(parents=True, exist_ok=True)
    status = {"ok": True, "ready": False,
              "service": {"profile": CONFIG["profile"], "registry": REGISTRY.summary()},
              "excel": {"executable": CONFIG["excel"]["executable"],
                        "available": Path(CONFIG["excel"]["executable"]).is_file(),
                        "addin_required": False}}
    try:
        response = httpx.get(service_url(CONFIG, "ollama") + "/api/tags", timeout=10, trust_env=False)
        response.raise_for_status()
        names = {item["name"] for item in response.json().get("models", [])}
        name = CONFIG["ollama"]["model"]
        status["qwen"] = {"model": name, "available": name in names or name + ":latest" in names}
    except Exception as exc:
        status["qwen"] = {"model": CONFIG["ollama"]["model"], "available": False, "error": str(exc)}
    try:
        status["blender"] = BlenderAdapter().status(probe_directory)
    except Exception as exc:
        status["blender"] = {"ok": False, "error": str(exc), "transport_callable": False}
    status["ready"] = bool(
        status["qwen"]["available"]
        and status["excel"]["available"]
        and status["blender"].get("transport_callable")
        and status["blender"].get("operators", {}).get("jhv.run_dpc_automation")
    )
    status["ok"] = status["ready"]
    log("system_status", {"result": status})
    return status
