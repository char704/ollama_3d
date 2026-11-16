"""Windows lifecycle and WebUI registration. Run via the .cmd entry points."""

import argparse
import hashlib
import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

import httpx
import psutil
from project_config import ROOT, CONFIG_FILE, load, resolve, data_path, service_url

PYTHON = ROOT / ".venv/Scripts/python.exe"
STATE = ROOT / "runtime/services.json"
FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)
MODEL_ID = "excel-blender-demo"
TOOL_ID = "excel_blender_demo"


def say(message):
    print(message, flush=True)


def request(url, body=None, token=None, timeout=5):
    with httpx.Client(timeout=timeout, trust_env=False) as client:
        response = client.request(
            "GET" if body is None else "POST",
            url,
            json=body,
            headers={"Authorization": "Bearer " + token} if token else {},
        )
        response.raise_for_status()
        return response.json()


def owned(service):
    result = []
    for process in psutil.process_iter(["exe", "cmdline", "cwd"]):
        try:
            info = process.info
            if not info["exe"] or not Path(info["exe"]).resolve().is_relative_to(ROOT):
                continue
            args = info["cmdline"] or []
            if service == "api":
                match = (
                    "uvicorn" in args
                    and "api_service:app" in args
                    and Path(info["cwd"]).resolve() == ROOT
                )
            else:
                match = (
                    any(Path(a).name.lower() == "open-webui.exe" for a in args)
                    and "serve" in args
                )
            if match:
                result.append(process)
        except (psutil.Error, OSError, TypeError):
            continue
    return result


def assert_idle():
    script = str(ROOT / "blender/apply_vbom.py").casefold()
    for process in psutil.process_iter(["cmdline"]):
        if any(a.casefold() == script for a in (process.info["cmdline"] or [])):
            raise RuntimeError(
                "Blender is processing a run. Wait for completion before stopping/restarting."
            )


def stop_service(service):
    processes = owned(service)
    if not processes:
        return
    assert_idle()
    for process in reversed(processes):
        try:
            process.terminate()
        except psutil.NoSuchProcess:
            pass
    _, alive = psutil.wait_procs(processes, timeout=10)
    if alive:
        raise RuntimeError(
            f"{service} did not stop; inspect Status.cmd and logs before retrying"
        )
    say(f"Stopped {service}.")


def port_owner(port):
    for connection in psutil.net_connections(kind="tcp"):
        if connection.status == psutil.CONN_LISTEN and connection.laddr.port == port:
            return connection.pid or -1
    return None


def state():
    return json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}


def fingerprint(service):
    paths = [
        CONFIG_FILE,
        ROOT / "manage.py",
        ROOT / "project_config.py",
        ROOT / "tool_registry.py",
        ROOT / "webui_tool.py",
        *sorted((ROOT / "tool-library").rglob("*.json")),
    ]
    if service == "api":
        paths += [
            ROOT / "api_service.py",
            ROOT / "contracts.py",
            *sorted((ROOT / "adapters").glob("*.py")),
            *sorted((ROOT / "workflows").rglob("*.py")),
            *sorted((ROOT / "workflows" / "definitions").glob("*.json")),
            *sorted((ROOT / "schemas").glob("*.json")),
        ]
    return hashlib.sha256(b"".join(p.read_bytes() for p in paths)).hexdigest()


def save_state(service):
    value = state()
    value[service] = {
        "fingerprint": fingerprint(service),
        "pids": [p.pid for p in owned(service)],
    }
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(value, indent=2), encoding="utf-8")


def environment(config):
    return {
        **os.environ,
        "DATA_DIR": str(ROOT / "webui-data"),
        "OLLAMA_BASE_URL": service_url(config, "ollama"),
        "OLLAMA_BASE_URLS": service_url(config, "ollama"),
        "WEBUI_AUTH": "False",
        "ENABLE_SIGNUP": "False",
        "ENABLE_OPENAI_API": "False",
        "OFFLINE_MODE": "True",
        "HF_HUB_OFFLINE": "1",
        "ANONYMIZED_TELEMETRY": "False",
        "DO_NOT_TRACK": "1",
        "RAG_EMBEDDING_ENGINE": "ollama",
        "ENABLE_VERSION_UPDATE_CHECK": "False",
        "ENABLE_EVALUATION_ARENA_MODELS": "False",
        "DEFAULT_MODELS": MODEL_ID,
        "PYTHONIOENCODING": "utf-8",
        "SCARF_NO_ANALYTICS": "true",
    }


def launch(command, name, env):
    logs = ROOT / "logs"
    logs.mkdir(exist_ok=True)
    with (logs / (name + ".log")).open("a", encoding="utf-8") as out, (
        logs / (name + "-error.log")
    ).open("a", encoding="utf-8") as err:
        return subprocess.Popen(
            command,
            cwd=ROOT,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=err,
            creationflags=FLAGS,
        )


def wait_ready(url, predicate, process, name, seconds=150):
    deadline = time.monotonic() + seconds
    next_notice = 0
    while time.monotonic() < deadline:
        try:
            if predicate(request(url, timeout=2)):
                return
        except (httpx.HTTPError, ValueError):
            pass
        if process.poll() is not None:
            raise RuntimeError(
                f"{name} exited ({process.returncode}). Read logs/{name}-error.log"
            )
        if time.monotonic() >= next_notice:
            say(f"Waiting for {name}...")
            next_notice = time.monotonic() + 15
        time.sleep(1)
    raise RuntimeError(
        f"{name} readiness timed out. Read logs/{name}-error.log; use Status.cmd."
    )


def ensure_service(config, service):
    running = owned(service)
    url = service_url(config, service) + "/health"
    if running and state().get(service, {}).get("fingerprint") == fingerprint(service):
        try:
            health = request(url)
            owner = port_owner(config["services"][service + "_port"])
            if owner in [p.pid for p in running] and (
                health.get("ok") if service == "api" else health.get("status")
            ):
                say(f"{service} ready: {url[:-7]}")
                return
        except (httpx.HTTPError, ValueError):
            pass
    if running:
        stop_service(service)
    port = config["services"][service + "_port"]
    if port_owner(port):
        raise RuntimeError(
            f"Port {port} belongs to another process. Change config.json; that process was left running."
        )
    command = (
        [str(PYTHON), "-m", "uvicorn", "api_service:app", "--workers", "1"]
        if service == "api"
        else [str(ROOT / ".venv/Scripts/open-webui.exe"), "serve"]
    )
    process = launch(
        command + ["--host", "127.0.0.1", "--port", str(port)],
        service,
        environment(config),
    )
    predicate = (
        (
            lambda h: h.get("service") == "excel-blender-demo-api"
            and h.get("project_root") == str(ROOT)
        )
        if service == "api"
        else (lambda h: h.get("status") is True)
    )
    wait_ready(url, predicate, process, service)
    save_state(service)
    say(f"{service} ready: {url[:-7]}")


def ollama_executable(config):
    configured = config["ollama"].get("executable", "")
    if configured:
        return str(resolve(config, configured))
    return shutil.which("ollama") or str(
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Ollama/ollama.exe"
    )


def ensure_ollama(config, pull=False):
    url = service_url(config, "ollama")
    try:
        tags = request(url + "/api/tags")
    except httpx.HTTPError:
        from urllib.parse import urlparse

        parsed = urlparse(url)
        if port_owner(parsed.port or 80):
            raise RuntimeError(
                "Configured Ollama port is occupied by an unresponsive or different service"
            )
        executable = ollama_executable(config)
        if not Path(executable).is_file():
            raise FileNotFoundError("Ollama not installed. Run Install.cmd.")
        process = launch(
            [executable, "serve"], "ollama", {**os.environ, "OLLAMA_HOST": url}
        )
        wait_ready(
            url + "/api/tags",
            lambda h: isinstance(h.get("models"), list),
            process,
            "ollama",
            45,
        )
        tags = request(url + "/api/tags")
    name = config["ollama"]["model"]
    names = [m["name"] for m in tags.get("models", [])]
    if name not in names and name + ":latest" not in names:
        if not pull:
            raise RuntimeError(
                f"Model {name} is missing. Run Install.cmd to download it."
            )
        say(f"Downloading Ollama model {name} (may take several minutes)...")
        subprocess.run(
            [ollama_executable(config), "pull", name],
            env={**os.environ, "OLLAMA_HOST": url},
            check=True,
        )
    say(f"Ollama ready: {name}")


def sync_webui(config):
    base = service_url(config, "webui")
    token = request(
        base + "/api/v1/auths/signin",
        {"email": "admin@localhost", "password": "admin"},
        timeout=30,
    )["token"]

    def api(path, body=None):
        return request(base + path, body, token, timeout=60)

    # Open WebUI persists provider URLs in its database; updating env alone is insufficient.
    api(
        "/ollama/config/update",
        {
            "ENABLE_OLLAMA_API": True,
            "OLLAMA_BASE_URLS": [service_url(config, "ollama")],
            "OLLAMA_API_CONFIGS": {},
        },
    )
    content = (ROOT / "webui_tool.py").read_text(encoding="utf-8-sig")
    config_literal = repr(str(CONFIG_FILE))
    content = content.replace("'__PROJECT_CONFIG_FILE__'", config_literal)
    content = content.replace('"__PROJECT_CONFIG_FILE__"', config_literal)
    if "__PROJECT_CONFIG_FILE__" in content:
        raise RuntimeError(
            "Could not inject the project config path into webui_tool.py"
        )
    tool_body = {
        "id": TOOL_ID,
        "name": "Excel to Blender",
        "content": content,
        "meta": {
            "description": "Excel export and Blender apply through configured HTTP APIs."
        },
        "access_grants": [],
    }
    existing = api("/api/v1/tools/")
    route = (
        f"/api/v1/tools/id/{TOOL_ID}/update"
        if any(t["id"] == TOOL_ID for t in existing)
        else "/api/v1/tools/create"
    )
    registered = api(route, tool_body)
    expected = {
        "list_demo_files",
        "run_bom_pipeline",
        "get_bom_pipeline_job",
        "list_blender_addons",
        "run_blender_addon",
        "get_blender_job",
        "cancel_blender_job",
    }
    if {s["name"] for s in registered.get("specs", [])} != expected:
        raise RuntimeError("Registered tool schema differs from the expected tools")
    system = (
        "Execute Excel-to-Blender requests using the supplied tools. First call list_demo_files, using the user input_dir or empty for the configured default. "
        "Select the exact requested Excel filename. If none was specified and multiple files are present, ask which one. "
        "For every end-to-end Excel to Blender request, call run_bom_pipeline exactly once with the selected full paths; Python enforces export, apply and verification in order. Preserve the requested directory spelling. Use open_result=true unless the user requests background processing. "
        "Use get_bom_pipeline_job to inspect a workflow without rerunning it. Never invent paths, ignore errors, or report completion unless status=completed. "
        "When the user asks for an optional company add-on or Rhino Server, first call list_blender_addons. Choose only an entry whose description matches the request, then call run_blender_addon using its exact id and documented parameters. Never invent operator ids or parameters. "
        "One-shot Blender operators run through a queue in a long-running Blender Agent. If a tool returns a wait timeout, use get_blender_job with its exact job_id before deciding whether to retry. "
        "Only call cancel_blender_job when the user explicitly asks to cancel a queued Blender job. "
        "Include the actual output path. Respond briefly in Vietnamese. "
    )
    local_operations = sorted(
        name for name, item in config["workflow"].items() if item["provider"] == "local"
    )
    http_operations = sorted(
        name for name, item in config["workflow"].items() if item["provider"] == "http"
    )
    system += (
        "Workflow providers are selected independently. Local operations: "
        + (", ".join(local_operations) or "none")
        + ". HTTP operations: "
        + (", ".join(http_operations) or "none")
        + ". Follow each provider response and never assume all steps use the same backend. "
    )
    profile = config["profile"].strip()
    body = {
        "id": MODEL_ID,
        "base_model_id": config["ollama"]["model"],
        "name": "Excel → Blender " + profile.title(),
        "meta": {
            "toolIds": [TOOL_ID],
            "description": "Local Ollama with configured Excel and Blender APIs.",
            "capabilities": {
                k: False
                for k in (
                    "vision",
                    "file_upload",
                    "web_search",
                    "image_generation",
                    "code_interpreter",
                    "builtin_tools",
                )
            },
            "suggestion_prompts": (
                [
                    {
                        "content": "Dùng Footwear_BOM.xlsx, xuất VBOM rồi áp vật liệu và màu vào model mặc định. Mở kết quả."
                    }
                ]
                if profile.casefold() == "demo"
                else []
            ),
        },
        "params": {
            "function_calling": "native",
            "temperature": 0,
            "num_ctx": 8192,
            "num_predict": 1200,
            "system": system,
        },
        "access_grants": [],
        "is_active": True,
    }
    models = api("/api/v1/models/all")
    items = (
        models
        if isinstance(models, list)
        else models.get("items", models.get("data", []))
    )
    api(
        (
            "/api/v1/models/model/update?id=" + MODEL_ID
            if any(m["id"] == MODEL_ID for m in items)
            else "/api/v1/models/create"
        ),
        body,
    )
    say("Synced Excel, Blender and approved add-on tools in Open WebUI.")


def check(config):
    for line in (ROOT / "requirements.txt").read_text().splitlines():
        if not line or line.startswith("#"):
            continue
        package, required = line.split("==")
        actual = importlib.metadata.version(package)
        if actual != required:
            raise RuntimeError(
                f"{package}: expected {required}, found {actual}. Run Install.cmd."
            )
    local = {
        name for name, item in config["workflow"].items() if item["provider"] == "local"
    }
    required_paths = set()
    if local.intersection({"files", "export"}):
        required_paths.add("inputs")
    if "apply" in local:
        required_paths.update({"default_model", "blender_exe"})
    if config["blender_agent"]["enabled"] or any(
        item.get("enabled", True) for item in config["blender_operators"]
    ):
        required_paths.add("blender_exe")
    for key in sorted(required_paths):
        if not data_path(config, key).exists():
            raise FileNotFoundError(
                f"config.json paths.{key} does not exist: {data_path(config, key)}"
            )
    data_path(config, "outputs").mkdir(parents=True, exist_ok=True)
    say("Configuration and Python dependencies: OK")


def status(config):
    healthy = True
    for name, path in [
        ("ollama", "/api/tags"),
        ("api", "/health"),
        ("webui", "/health"),
    ]:
        url = service_url(config, name)
        try:
            response = request(url + path)
            valid = (
                isinstance(response.get("models"), list)
                if name == "ollama"
                else (
                    response.get("service") == "excel-blender-demo-api"
                    and response.get("project_root") == str(ROOT)
                    if name == "api"
                    else response.get("status") is True
                )
            )
            if not valid:
                raise ValueError("unexpected health response")
            if name != "ollama" and port_owner(
                config["services"][name + "_port"]
            ) not in [p.pid for p in owned(name)]:
                raise ValueError("port is owned by another project")
            if name == "ollama":
                model = config["ollama"]["model"]
                installed = {m["name"] for m in response["models"]}
                if model not in installed and model + ":latest" not in installed:
                    raise ValueError("configured model is missing; run Install.cmd")
            elif state().get(name, {}).get("fingerprint") != fingerprint(name):
                raise ValueError("configuration/code changed; run Open-WebUI.cmd")
            say(f"{name}: READY  {url}")
        except (httpx.HTTPError, ValueError) as exc:
            healthy = False
            say(f"{name}: NOT READY  {url} ({exc})")
    if config["blender_agent"]["enabled"]:
        from adapters.operators import agent_status

        agent = agent_status()
        if agent.get("ready"):
            say(f'blender-agent: READY  pid={agent["pid"]} status={agent["status"]}')
        else:
            healthy = False
            say("blender-agent: NOT READY")
    providers = ", ".join(
        f'{name}={item["provider"]}' for name, item in config["workflow"].items()
    )
    say(
        f'Profile: {config["profile"]}; model: {config["ollama"]["model"]}; providers: {providers}'
    )
    say(
        f'Inputs: {data_path(config, "inputs")}\nOutputs: {data_path(config, "outputs")}\nLogs: {ROOT / "logs"}'
    )
    return 0 if healthy else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action",
        choices=[
            "start",
            "stop",
            "status",
            "check",
            "install",
            "sync",
            "api",
            "restart-api",
        ],
    )
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if args.action == "stop":
        from adapters.operators import stop_agent

        stopped = stop_agent()
        if stopped.get("pid"):
            say(f'Stopped Blender Agent pid={stopped["pid"]}.')
        stop_service("webui")
        stop_service("api")
        say("Project stopped. Ollama and company service windows remain available.")
        return 0
    config = load()
    if args.action == "status":
        return status(config)
    check(config)
    if args.action == "check":
        return 0
    if args.action == "sync":
        sync_webui(config)
        return 0
    if args.action in ("api", "restart-api"):
        if args.action == "restart-api":
            stop_service("api")
        ensure_service(config, "api")
        return 0
    ensure_ollama(config, pull=args.action == "install")
    ensure_service(config, "api")
    if config["blender_agent"]["enabled"]:
        from adapters.operators import ensure_agent

        agent = ensure_agent()
        say(f'Blender Agent ready: pid={agent["pid"]}')
    ensure_service(config, "webui")
    sync_webui(config)
    say(
        "READY: "
        + service_url(config, "webui")
        + " - choose Excel -> Blender, then start a new chat."
    )
    if not args.no_browser:
        webbrowser.open(service_url(config, "webui"))
    return 0


if __name__ == "__main__":
    # Windows redirected output can default to cp1252; paths may contain Vietnamese.
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    try:
        sys.exit(main())
    except Exception as exc:
        say(f"ERROR: {exc}")
        sys.exit(1)
