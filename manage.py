"""Windows lifecycle, integration installation, and Open WebUI MCP registration."""

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
import zipfile
from pathlib import Path

import httpx
import psutil

from project_config import CONFIG_FILE, ROOT, data_path, load, resolve, service_url

PYTHON = ROOT / ".venv/Scripts/python.exe"
STATE = ROOT / "runtime/services.json"
FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)
MODEL_ID = "excel-blender-mcp-proof"
LEGACY_MODEL_ID = "excel-blender-demo"
LEGACY_TOOL_ID = "excel_blender_demo"


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
                ROOT / "mcp_server.py",
                *sorted((ROOT / "adapters").glob("*.py")),
                *sorted((ROOT / "workflows").glob("*.py")),
                ROOT / "blender/lab_mcp_runner.py",
                *sorted((ROOT / "blender" / "ollama3d_proof_addon").glob("*.py")),
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
    from adapters.blender_mcp import BlenderMcpAdapter
    from adapters.excel_vba import ExcelVbaAdapter

    excel = ExcelVbaAdapter().status()
    say(f"Excel VBA ready: {excel['addin_version']} (macro callable)")
    bridge = config["official_blender_mcp"]
    bridge_package = resolve(config, bridge["package"])
    if not bridge_package.is_file():
        say(f"Downloading official Blender MCP {bridge['version']}...")
        bridge_package.parent.mkdir(parents=True, exist_ok=True)
        try:
            response = httpx.get(
                bridge["download_url"],
                follow_redirects=True,
                timeout=60,
                headers={"User-Agent": "Mozilla/5.0 Ollama3D-Installer/1.0"},
            )
            response.raise_for_status()
            downloaded = response.content
            if hashlib.sha256(downloaded).hexdigest() != bridge["sha256"]:
                raise RuntimeError("downloaded package SHA-256 does not match")
            temporary = bridge_package.with_suffix(".download")
            temporary.write_bytes(downloaded)
            temporary.replace(bridge_package)
        except Exception as exc:
            raise RuntimeError(
                "Could not download official Blender MCP. Download it from "
                f"{bridge['download_url']} and save it as {bridge_package}. Error: {exc}"
            ) from exc
    actual_hash = hashlib.sha256(bridge_package.read_bytes()).hexdigest()
    if actual_hash != bridge["sha256"]:
        raise RuntimeError(
            f"Official Blender MCP {bridge['version']} package has an unexpected SHA-256"
        )
    settings = config["blender_addon"]
    package = resolve(config, settings["package"])
    source = ROOT / "blender" / settings["module"]
    package.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                archive.write(path, path.relative_to(source.parent).as_posix())
    report = ROOT / "runtime/install-blender-addon.json"
    report.parent.mkdir(exist_ok=True)
    subprocess.run(
        [
            str(data_path(config, "blender_exe")),
            "--background",
            "--python-exit-code",
            "1",
            "--python",
            str(ROOT / "blender/install_proof_addon.py"),
            "--",
            str(package),
            settings["module"],
            str(report),
        ],
        check=True,
        creationflags=FLAGS,
        timeout=settings["timeout_seconds"],
    )
    # Install/reinstall last with -e. The legacy add-on installer saves Blender
    # preferences, so this ordering guarantees the extension remains enabled.
    subprocess.run(
        [
            str(data_path(config, "blender_exe")),
            "--command",
            "extension",
            "install-file",
            "-r",
            "user_default",
            "-e",
            str(bridge_package),
        ],
        creationflags=FLAGS,
        timeout=120,
        check=True,
    )
    say(f"Official Blender MCP ready: {bridge['version']} (localhost only)")
    probe_directory = ROOT / "runtime/probes"
    probe_directory.mkdir(parents=True, exist_ok=True)
    blender = BlenderMcpAdapter().status(probe_directory)
    say(
        f"Blender add-on ready through official MCP "
        f"(operator callable: {blender['operator']})"
    )


def sync_webui(config):
    from adapters.common import REGISTRY

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

    existing_tools = api("/api/v1/tools/")
    if any(item["id"] == LEGACY_TOOL_ID for item in existing_tools):
        api(f"/api/v1/tools/id/{LEGACY_TOOL_ID}/delete", method="DELETE")

    models = api("/api/v1/models/all")
    items = models if isinstance(models, list) else models.get("items", models.get("data", []))
    if any(item["id"] == LEGACY_MODEL_ID for item in items):
        api("/api/v1/models/model/delete", {"id": LEGACY_MODEL_ID})

    server_id = config["mcp"]["server_id"]
    payload = api("/api/v1/configs/tool_servers")
    connections = payload.get("TOOL_SERVER_CONNECTIONS", [])
    if not isinstance(connections, list):
        raise RuntimeError("Open WebUI returned an invalid MCP server configuration")
    connection = {
        "url": service_url(config, "api") + config["mcp"]["path"],
        "path": config["mcp"]["path"],
        "type": "mcp",
        "auth_type": "none",
        "forward_cookies": False,
        "headers": {},
        "key": "",
        "config": {
            "enable": True,
            "function_name_filter_list": ",".join(REGISTRY.public_tools()),
        },
        "info": {
            "id": server_id,
            "name": "Ollama3D MCP",
            "description": "Real Excel VBA and allowlisted Blender add-on workflow over official Blender MCP.",
        },
    }
    connections = [
        item for item in connections if item.get("info", {}).get("id") != server_id
    ] + [connection]
    api("/api/v1/configs/tool_servers", {"TOOL_SERVER_CONNECTIONS": connections})

    system = (
        "Bạn điều phối đúng ba MCP tool. Dùng system_status chỉ khi người dùng hỏi trạng thái, "
        "phiên bản hoặc khả năng sẵn sàng. Dùng run_excel_to_blender chỉ khi người dùng yêu cầu "
        "chạy xử lý và cung cấp đủ ba đường dẫn tuyệt đối: excel_path (.xlsx), model_path (.blend), "
        "output_dir. Dùng create_colored_primitive khi người dùng yêu cầu tạo cube, UV sphere hoặc "
        "cylinder có màu và đã cung cấp output_dir tuyệt đối. Nếu thiếu đường dẫn, hãy hỏi lại; "
        "không tự đoán. Không gọi tool cho câu hỏi "
        "giải thích. Chỉ báo thành công khi status=completed và luôn nêu output_path. Trả lời ngắn gọn bằng tiếng Việt."
    )
    body = {
        "id": MODEL_ID,
        "base_model_id": config["ollama"]["model"],
        "name": "Excel → Blender MCP",
        "meta": {
            "toolIds": ["server:mcp:" + server_id],
            "description": "Qwen with registry-controlled local MCP tools backed by real VBA and official Blender MCP.",
            "capabilities": {
                key: False
                for key in (
                    "vision",
                    "file_upload",
                    "web_search",
                    "image_generation",
                    "code_interpreter",
                    "builtin_tools",
                )
            },
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
    items = models if isinstance(models, list) else models.get("items", models.get("data", []))
    route = (
        "/api/v1/models/model/update?id=" + MODEL_ID
        if any(item["id"] == MODEL_ID for item in items)
        else "/api/v1/models/create"
    )
    api(route, body)
    specs = api(f"/api/v1/tools/id/server:mcp:{server_id}/specs")["specs"]
    expected_tools = REGISTRY.public_tools()
    if [item["name"] for item in specs] != expected_tools:
        raise RuntimeError("Open WebUI MCP schema differs from the expected three tools")
    say("Synced the three-tool MCP model and removed legacy Open WebUI entries.")


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
        "default model": data_path(config, "default_model"),
        "Blender executable": data_path(config, "blender_exe"),
        "Excel executable": Path(config["excel_vba"]["executable"]),
        "Excel VBA add-in": resolve(config, config["excel_vba"]["addin_path"]),
        "Capability registry": resolve(config, config["capability_registry"]),
        "Blender add-on source": ROOT / "blender" / config["blender_addon"]["module"] / "__init__.py",
        "Blender MCP trusted runner": ROOT / "blender/lab_mcp_runner.py",
    }
    for label, path in required.items():
        if not path.exists():
            raise FileNotFoundError(f"{label} does not exist: {path}")
    registry = load_registry(resolve(config, config["capability_registry"]))
    if registry.public_tools() != [
        "system_status",
        "run_excel_to_blender",
        "create_colored_primitive",
    ]:
        raise RuntimeError("Capability registry public tools do not match this release")
    data_path(config, "outputs").mkdir(parents=True, exist_ok=True)
    say("Configuration, dependencies, and integration files: OK")


def status(config):
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
    say(f"Profile: {config['profile']}; model: {config['ollama']['model']}; MCP tools: 3")
    say(f"Inputs: {data_path(config, 'inputs')}\nOutputs: {data_path(config, 'outputs')}")
    return 0 if healthy else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action",
        choices=("start", "stop", "status", "check", "install", "sync", "api", "restart-api"),
    )
    parser.add_argument("--no-browser", action="store_true")
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
    say(f"READY: {service_url(config, 'webui')} - choose Excel → Blender MCP")
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
