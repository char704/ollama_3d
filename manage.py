"""Windows lifecycle and Open WebUI direct-REST registration."""

import argparse
import hashlib
import importlib.metadata
import json
import os
import re
import shutil
import subprocess
import sys
import time
import webbrowser
import zipfile
from pathlib import Path

import httpx
import psutil

from project_config import CONFIG_FILE, ROOT, data_path, load, resolve, service_url

PYTHON = ROOT / ".venv/Scripts/python.exe"
STATE = ROOT / "runtime/services.json"
FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)
MODEL_ID = "ollama3d-direct"
LOCAL_API_KEY = "ollama3d-local"


def say(message):
    print(message, flush=True)


def request(url, body=None, token=None, timeout=5, method=None):
    with httpx.Client(timeout=timeout, trust_env=False) as client:
        response = client.request(
            method or ("GET" if body is None else "POST"),
            url,
            json=body,
            headers={"Authorization": "Bearer " + token} if token else {},
        )
        response.raise_for_status()
        return response.json()


def owned(service):
    result = []
    for process in psutil.process_iter(["cmdline", "cwd"]):
        try:
            info = process.info
            if not info["cwd"] or Path(info["cwd"]).resolve() != ROOT:
                continue
            arguments = info["cmdline"] or []
            if service == "api":
                match = "uvicorn" in " ".join(arguments) and "api_service:app" in arguments
            else:
                match = any(
                    Path(argument).name.casefold() == "open-webui.exe"
                    for argument in arguments
                ) and "serve" in arguments
            if match:
                result.append(process)
        except (psutil.Error, OSError, TypeError):
            continue
    return result


def stop_service(service):
    processes = owned(service)
    for process in reversed(processes):
        try:
            process.terminate()
        except psutil.NoSuchProcess:
            pass
    _, alive = psutil.wait_procs(processes, timeout=10)
    if alive:
        raise RuntimeError(f"{service} did not stop; inspect logs before retrying")
    if processes:
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
        ROOT / "capabilities.json",
        ROOT / "capability_registry.py",
        ROOT / "manage.py",
        ROOT / "project_config.py",
    ]
    if service == "api":
        paths.extend(
            [
                ROOT / "api_service.py",
                *sorted((ROOT / "adapters").glob("*.py")),
                *sorted((ROOT / "workflows").glob("*.py")),
                ROOT / "blender/blender_runner.py",
            ]
        )
    return hashlib.sha256(b"".join(path.read_bytes() for path in paths)).hexdigest()


def save_state(service):
    value = state()
    value[service] = {
        "fingerprint": fingerprint(service),
        "pids": [process.pid for process in owned(service)],
    }
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(value, indent=2), encoding="utf-8")


def environment(config):
    result = {
        **os.environ,
        "DATA_DIR": str(ROOT / "webui-data"),
        "OLLAMA_BASE_URL": service_url(config, "ollama"),
        "OLLAMA_BASE_URLS": service_url(config, "ollama"),
        "WEBUI_AUTH": "False",
        "ENABLE_SIGNUP": "False",
        "ENABLE_OPENAI_API": "True",
        "OPENAI_API_BASE_URL": service_url(config, "api") + "/v1",
        "OPENAI_API_KEY": LOCAL_API_KEY,
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
        "OLLAMA_MODELS": str(resolve(config, config["ollama"]["models_directory"])),
    }
    return result


def launch(command, name, env):
    logs = ROOT / "logs"
    logs.mkdir(exist_ok=True)
    with (logs / f"{name}.log").open("a", encoding="utf-8") as output, (
        logs / f"{name}-error.log"
    ).open("a", encoding="utf-8") as error:
        return subprocess.Popen(
            command,
            cwd=ROOT,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=error,
            creationflags=FLAGS,
        )


def wait_ready(url, predicate, process, name, seconds=150):
    deadline = time.monotonic() + seconds
    next_notice = 0.0
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
    raise RuntimeError(f"{name} readiness timed out. Read logs/{name}-error.log")


def ensure_service(config, service):
    processes = owned(service)
    url = service_url(config, service) + "/health"
    if processes and state().get(service, {}).get("fingerprint") == fingerprint(service):
        try:
            health = request(url)
            owner = port_owner(config["services"][service + "_port"])
            valid = (
                health.get("service") == "ollama3d-local-api"
                and health.get("project_root") == str(ROOT)
                if service == "api"
                else health.get("status") is True
            )
            if owner in [process.pid for process in processes] and valid:
                say(f"{service} ready: {url[:-7]}")
                return
        except (httpx.HTTPError, ValueError):
            pass
    if processes:
        stop_service(service)
    port = config["services"][service + "_port"]
    if port_owner(port):
        raise RuntimeError(f"Port {port} belongs to another process")
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
    if service == "api":
        predicate = lambda value: (
            value.get("service") == "ollama3d-local-api"
            and value.get("project_root") == str(ROOT)
        )
    else:
        predicate = lambda value: value.get("status") is True
    wait_ready(url, predicate, process, service)
    save_state(service)
    say(f"{service} ready: {url[:-7]}")


def ollama_executable(config):
    configured = config["ollama"]["executable"]
    return str(resolve(config, configured)) if configured else (
        shutil.which("ollama")
        or str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Ollama/ollama.exe")
    )


def ensure_ollama(config, pull=False):
    url = service_url(config, "ollama")
    try:
        tags = request(url + "/api/tags")
    except httpx.HTTPError:
        from urllib.parse import urlparse

        parsed = urlparse(url)
        if port_owner(parsed.port or 80):
            raise RuntimeError("Configured Ollama port is occupied by another service")
        executable = ollama_executable(config)
        if not Path(executable).is_file():
            raise FileNotFoundError("Ollama not installed. Run Install.cmd")
        ollama_environment = environment(config)
        ollama_environment["OLLAMA_HOST"] = url
        process = launch([executable, "serve"], "ollama", ollama_environment)
        wait_ready(
            url + "/api/tags",
            lambda value: isinstance(value.get("models"), list),
            process,
            "ollama",
            45,
        )
        tags = request(url + "/api/tags")

    name = config["ollama"]["model"]
    names = [item["name"] for item in tags.get("models", [])]
    model_name, _, tag = name.partition(":")
    tag = tag or "latest"
    manifests = resolve(config, config["ollama"]["models_directory"]) / "manifests"
    manifest_exists = any(
        path.parent.name == model_name for path in manifests.rglob(tag) if path.is_file()
    )
    if name not in names and name + ":latest" not in names and pull and manifest_exists:
        from urllib.parse import urlparse

        owner_pid = port_owner(urlparse(url).port or 80)
        owner = psutil.Process(owner_pid) if owner_pid and owner_pid > 0 else None
        if owner is None or owner.name().casefold() != "ollama.exe":
            raise RuntimeError("The Ollama port is not owned by ollama.exe")
        say("Restarting Ollama with the configured local model directory...")
        owner.terminate()
        owner.wait(timeout=10)
        process = launch([ollama_executable(config), "serve"], "ollama", environment(config))
        wait_ready(
            url + "/api/tags",
            lambda value: any(
                item.get("name") in (name, name + ":latest")
                for item in value.get("models", [])
            ),
            process,
            "ollama",
            45,
        )
        tags = request(url + "/api/tags")
        names = [item["name"] for item in tags.get("models", [])]
    if name not in names and name + ":latest" not in names:
        if not pull:
            raise RuntimeError(f"Model {name} is missing. Run Install.cmd")
        say(f"Downloading Ollama model {name}...")
        subprocess.run(
            [ollama_executable(config), "pull", name],
            env={**environment(config), "OLLAMA_HOST": url},
            check=True,
        )
    say(f"Ollama ready: {name}")


def ensure_integrations(config):
    """Probe Blender and Excel executable without installing demo plugins."""
    from adapters.blender import BlenderAdapter
    excel_exe = Path(config["excel"]["executable"])
    if not excel_exe.is_file():
        raise FileNotFoundError(f"Excel executable not found: {excel_exe}")
    say("Excel executable ready (no demo add-in required).")
    probe_directory = ROOT / "runtime" / "probes"
    probe_directory.mkdir(parents=True, exist_ok=True)
    report = BlenderAdapter().status(probe_directory)
    if not report.get("operators", {}).get("jhv.run_dpc_automation"):
        raise RuntimeError("Install and enable jhv_dpc in the configured Blender before running JHV.")
    say(f"Blender subprocess ready ({len(report.get('operators', {}))} registered operators checked).")


def sync_webui(config):
    base = service_url(config, "webui")
    token = request(
        base + "/api/v1/auths/signin",
        {"email": "admin@localhost", "password": "admin"},
        timeout=30,
    )["token"]

    def api(path, body=None, method=None):
        return request(base + path, body, token, timeout=60, method=method)

    api(
        "/ollama/config/update",
        {
            "ENABLE_OLLAMA_API": True,
            "OLLAMA_BASE_URLS": [service_url(config, "ollama")],
            "OLLAMA_API_CONFIGS": {},
        },
    )
    api(
        "/openai/config/update",
        {
            "ENABLE_OPENAI_API": True,
            "OPENAI_API_BASE_URLS": [service_url(config, "api") + "/v1"],
            "OPENAI_API_KEYS": [LOCAL_API_KEY],
            "OPENAI_API_CONFIGS": {
                "0": {
                    "enable": True,
                    "connection_type": "local",
                    "model_ids": [MODEL_ID],
                }
            },
        },
    )

    payload = api("/api/v1/configs/tool_servers")
    connections = payload.get("TOOL_SERVER_CONNECTIONS", [])
    if not isinstance(connections, list):
        raise RuntimeError("Open WebUI returned an invalid tool server configuration")
    connections = [
        item for item in connections if item.get("info", {}).get("id") != "ollama3d"
    ]
    api("/api/v1/configs/tool_servers", {"TOOL_SERVER_CONNECTIONS": connections})

    discovered = api("/openai/models")
    model_items = discovered if isinstance(discovered, list) else discovered.get("data", [])
    if not any(item.get("id") == MODEL_ID for item in model_items):
        raise RuntimeError("Open WebUI could not discover the direct Ollama3D REST model")
    say("Synced Open WebUI to the direct Ollama3D REST agent.")


def check(config):
    from capability_registry import load_registry

    for line in (ROOT / "requirements.txt").read_text().splitlines():
        if not line or line.startswith("#"):
            continue
        package, required = line.split("==")
        actual = importlib.metadata.version(package)
        if actual != required:
            raise RuntimeError(f"{package}: expected {required}, found {actual}")
    required = {
        "input directory": data_path(config, "inputs"),
        "Blender executable": data_path(config, "blender_exe"),
        "Excel executable": Path(config["excel"]["executable"]),
        "Capability registry": resolve(config, config["capability_registry"]),
        "Blender trusted runner": ROOT / "blender/blender_runner.py",
        "Blender subprocess entry": ROOT / "blender/job_entry.py",
    }
    for label, path in required.items():
        if not path.exists():
            raise FileNotFoundError(f"{label} does not exist: {path}")
    registry = load_registry(resolve(config, config["capability_registry"]))
    for capability_id in (
        "system.status",
        "workflow.process_folder",
    ):
        registry.require(capability_id)
    data_path(config, "outputs").mkdir(parents=True, exist_ok=True)
    say("Configuration, dependencies, and integration files: OK")


def discover_addons(config, requested_modules, write_proposals=False):
    from adapters.blender import BlenderAdapter
    from capability_discovery import propose_entries
    from capability_registry import load_registry

    registry = load_registry(resolve(config, config["capability_registry"]))
    modules = requested_modules or registry.addon_modules()
    modules = list(dict.fromkeys(modules))
    directory = ROOT / "runtime" / "discovered"
    report = BlenderAdapter().discover(modules, directory)
    for module in modules:
        module_report = {
            **report,
            "modules": [module],
            "operators": [
                item for item in report["operators"] if item["addon_module"] == module
            ],
        }
        module_report["operator_count"] = len(module_report["operators"])
        module_report["operator_ids"] = [
            item["bl_idname"] for item in module_report["operators"]
        ]
        path = directory / f"{module}.json"
        path.write_text(
            json.dumps(module_report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        say(f"Discovered {module_report['operator_count']} operators: {path}")
    proposals = propose_entries(report, registry)
    if write_proposals:
        proposal_path = directory / "proposals.json"
        proposal_path.write_text(
            json.dumps(proposals, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        say(f"Wrote {len(proposals)} disabled proposals: {proposal_path}")
    else:
        say(json.dumps(proposals, ensure_ascii=False, indent=2))
    return 0


def _write_addon_json(path, document):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(path)


def addon_add(config, module, root=ROOT):
    from adapters.blender import BlenderAdapter
    from capability_discovery import propose_entries
    from capability_registry import load_registry

    if not re.fullmatch(r"[a-z][a-z0-9_.]*", module):
        raise ValueError("Add-on module name is invalid")
    pack_directory = Path(root) / "addons" / module
    if pack_directory.exists():
        raise FileExistsError(f"Add-on pack already exists: {pack_directory}")
    discovery_directory = Path(root) / "runtime" / "discovered" / module
    report = BlenderAdapter().discover([module], discovery_directory)
    registry = load_registry(
        resolve(config, config["capability_registry"]),
        addon_root=Path(root) / "addons",
        workflow_root=Path(root) / "workflows" / "definitions",
    )
    proposals = propose_entries(report, registry)
    if not proposals:
        raise RuntimeError("Discovery found no new operators for this add-on")
    operators = {}
    for proposal in proposals:
        operators[proposal["target"]] = {
            "id": proposal["id"],
            "enabled": False,
            "risk": proposal["risk"],
            "description": proposal["description"],
            "background_safe": proposal["background_safe"],
            "params": proposal["params"],
        }
    document = {
        "module": module,
        "description": f"Discovered Blender add-on: {module}",
        "operators": operators,
    }
    _write_addon_json(pack_directory / "addon.json", document)
    say(f"Created disabled add-on pack: {pack_directory / 'addon.json'}")
    for operator in operators:
        say(f"  disabled  {operator}")
    return 0


def addon_set_enabled(module, operators, enabled, root=ROOT):
    if not operators:
        raise ValueError("At least one operator idname is required")
    path = Path(root) / "addons" / module / "addon.json"
    if not path.is_file():
        raise FileNotFoundError(f"Add-on pack does not exist: {path}")
    document = json.loads(path.read_text(encoding="utf-8-sig"))
    available = document.get("operators", {})
    unknown = [operator for operator in operators if operator not in available]
    if unknown:
        raise ValueError("Unknown add-on operator(s): " + ", ".join(unknown))
    for operator in operators:
        available[operator]["enabled"] = enabled
    _write_addon_json(path, document)
    action = "Enabled" if enabled else "Disabled"
    say(f"{action} {len(operators)} operator(s) in {module}.")
    return 0


def addon_command(config, action, module, operators, root=ROOT):
    if action == "add":
        if operators:
            raise ValueError("addon add does not accept operator arguments")
        return addon_add(config, module, root)
    if action == "enable":
        return addon_set_enabled(module, operators, True, root)
    if action == "disable":
        return addon_set_enabled(module, operators, False, root)
    raise ValueError("addon action must be add, enable, or disable")


def status(config):
    from capability_registry import load_registry

    healthy = True
    for name, path in (("ollama", "/api/tags"), ("api", "/health"), ("webui", "/health")):
        url = service_url(config, name)
        try:
            response = request(url + path)
            if name == "ollama":
                installed = {item["name"] for item in response.get("models", [])}
                model = config["ollama"]["model"]
                if model not in installed and model + ":latest" not in installed:
                    raise ValueError("configured model is missing")
            else:
                valid = (
                    response.get("service") == "ollama3d-local-api"
                    and response.get("project_root") == str(ROOT)
                    if name == "api"
                    else response.get("status") is True
                )
                if not valid:
                    raise ValueError("unexpected health response")
                if port_owner(config["services"][name + "_port"]) not in [
                    process.pid for process in owned(name)
                ]:
                    raise ValueError("port is owned by another project")
                if state().get(name, {}).get("fingerprint") != fingerprint(name):
                    raise ValueError("configuration/code changed; run Open-WebUI.cmd")
            say(f"{name}: READY  {url}")
        except (httpx.HTTPError, ValueError) as exc:
            healthy = False
            say(f"{name}: NOT READY  {url} ({exc})")
    registry = load_registry(resolve(config, config["capability_registry"]))
    say(
        f"Profile: {config['profile']}; model: {config['ollama']['model']}; "
        f"capabilities: {registry.summary()['enabled']}"
    )
    say(f"Inputs: {data_path(config, 'inputs')}\nOutputs: {data_path(config, 'outputs')}")
    return 0 if healthy else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action",
        choices=(
            "start",
            "stop",
            "status",
            "check",
            "install",
            "sync",
            "api",
            "restart-api",
            "discover",
            "addon",
        ),
    )
    parser.add_argument("addon_action", nargs="?")
    parser.add_argument("addon_module", nargs="?")
    parser.add_argument("addon_operators", nargs="*")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--module", action="append", default=[])
    parser.add_argument("--write-proposals", action="store_true")
    args = parser.parse_args()
    if args.action == "stop":
        stop_service("webui")
        stop_service("api")
        say("Project stopped. Ollama remains available.")
        return 0
    config = load()
    if args.action == "status":
        return status(config)
    check(config)
    if args.action == "check":
        return 0
    if args.action == "discover":
        return discover_addons(config, args.module, args.write_proposals)
    if args.action == "addon":
        if not args.addon_action or not args.addon_module:
            raise ValueError("Usage: manage.py addon <add|enable|disable> <module> [operator ...]")
        return addon_command(
            config,
            args.addon_action,
            args.addon_module,
            args.addon_operators,
        )
    if args.action == "sync":
        sync_webui(config)
        return 0
    if args.action in ("api", "restart-api"):
        if args.action == "restart-api":
            stop_service("api")
        ensure_service(config, "api")
        return 0
    if args.action == "install":
        ensure_integrations(config)
    ensure_ollama(config, pull=args.action == "install")
    ensure_service(config, "api")
    ensure_service(config, "webui")
    sync_webui(config)
    say(f"READY: {service_url(config, 'webui')} - choose {MODEL_ID}")
    if not args.no_browser:
        webbrowser.open(service_url(config, "webui"))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    try:
        sys.exit(main())
    except Exception as exc:
        say(f"ERROR: {exc}")
        sys.exit(1)
