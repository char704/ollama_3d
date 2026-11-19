"""Install, validate, and inspect the direct Ollama3D integrations."""

import argparse
import importlib.metadata
import json
import os
import re
import shutil
import subprocess
import time
import zipfile
from pathlib import Path

import httpx
import psutil

from project_config import ROOT, data_path, load, resolve, service_url

FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def say(message):
    print(message, flush=True)


def request(url, timeout=5):
    with httpx.Client(timeout=timeout, trust_env=False) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.json()


def port_owner(port):
    for connection in psutil.net_connections(kind="tcp"):
        if connection.status == psutil.CONN_LISTEN and connection.laddr.port == port:
            return connection.pid or -1
    return None


def environment(config):
    return {
        **os.environ,
        "PYTHONIOENCODING": "utf-8",
        "OLLAMA_MODELS": str(resolve(config, config["ollama"]["models_directory"])),
    }


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


def ollama_executable(config):
    configured = config["ollama"]["executable"]
    return str(resolve(config, configured)) if configured else (
        shutil.which("ollama")
        or str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Ollama/ollama.exe")
    )


def _wait_for_ollama(url, process, seconds=45):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            value = request(url + "/api/tags", timeout=2)
            if isinstance(value.get("models"), list):
                return value
        except (httpx.HTTPError, ValueError):
            pass
        if process.poll() is not None:
            raise RuntimeError(
                f"Ollama exited ({process.returncode}); read logs/ollama-error.log"
            )
        time.sleep(0.5)
    raise RuntimeError("Ollama readiness timed out; read logs/ollama-error.log")


def ensure_ollama(config, pull=False):
    url = service_url(config, "ollama")
    try:
        tags = request(url + "/api/tags")
    except httpx.HTTPError:
        from urllib.parse import urlparse

        if port_owner(urlparse(url).port or 80):
            raise RuntimeError("Configured Ollama port is occupied by another service")
        executable = ollama_executable(config)
        if not Path(executable).is_file():
            raise FileNotFoundError("Ollama is not installed; run Install.cmd")
        ollama_env = environment(config)
        ollama_env["OLLAMA_HOST"] = url
        tags = _wait_for_ollama(
            url, launch([executable, "serve"], "ollama", ollama_env)
        )

    installed = {item["name"] for item in tags.get("models", [])}
    configured = list(
        dict.fromkeys(
            config["ollama"][key]
            for key in ("model", "router_model", "utility_model")
        )
    )
    for model in configured:
        if model in installed or model + ":latest" in installed:
            continue
        if not pull:
            raise RuntimeError(f"Model {model} is missing; run Install.cmd")
        say(f"Downloading Ollama model {model}...")
        subprocess.run(
            [ollama_executable(config), "pull", model],
            env={**environment(config), "OLLAMA_HOST": url},
            check=True,
        )
    say("Ollama ready: " + ", ".join(configured))


def ensure_integrations(config):
    from adapters.blender import BlenderAdapter
    from adapters.excel_vba import ExcelVbaAdapter

    excel = ExcelVbaAdapter().status()
    say(f"Excel VBA add-in ready: {excel['addin_version']} (macro callable)")
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
    probe_directory = ROOT / "runtime/probes"
    probe_directory.mkdir(parents=True, exist_ok=True)
    blender = BlenderAdapter().status(probe_directory)
    say(
        f"Blender add-on ready through {blender['transport']} "
        f"(operator callable: {blender['operator']})"
    )


def check(config):
    from capability_registry import load_registry

    for line in (ROOT / "requirements.txt").read_text().splitlines():
        if not line or line.startswith("#"):
            continue
        package, required_version = line.split("==")
        actual = importlib.metadata.version(package)
        if actual != required_version:
            raise RuntimeError(
                f"{package}: expected {required_version}, found {actual}"
            )
    required = {
        "input directory": data_path(config, "inputs"),
        "default model": data_path(config, "default_model"),
        "Blender executable": data_path(config, "blender_exe"),
        "Excel executable": Path(config["excel_vba"]["executable"]),
        "Excel VBA add-in": resolve(config, config["excel_vba"]["addin_path"]),
        "capability registry": resolve(config, config["capability_registry"]),
        "Blender add-on source": ROOT
        / "blender"
        / config["blender_addon"]["module"]
        / "__init__.py",
        "Blender trusted runner": ROOT / "blender/blender_runner.py",
        "Blender subprocess entry": ROOT / "blender/job_entry.py",
    }
    for label, path in required.items():
        if not path.exists():
            raise FileNotFoundError(f"{label} does not exist: {path}")
    registry = load_registry(resolve(config, config["capability_registry"]))
    for capability_id in (
        "system.status",
        "workflow.excel_to_blender",
        "blender.create_colored_primitive",
    ):
        registry.require(capability_id)
    data_path(config, "outputs").mkdir(parents=True, exist_ok=True)
    say("Configuration, dependencies, Excel add-in, and Blender add-on files: OK")


def discover_addons(config, requested_modules, write_proposals=False):
    from adapters.blender import BlenderAdapter
    from capability_discovery import propose_entries
    from capability_registry import load_registry

    registry = load_registry(resolve(config, config["capability_registry"]))
    modules = requested_modules or registry.addon_modules()
    configured_module = config["blender_addon"]["module"]
    if configured_module not in modules:
        modules.append(configured_module)
    modules = list(dict.fromkeys(modules))
    directory = ROOT / "runtime/discovered"
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
    from workflows.core_workflow import system_status

    result = system_status()
    say(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ready") else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action", choices=("status", "check", "install", "discover", "addon")
    )
    parser.add_argument("addon_action", nargs="?")
    parser.add_argument("addon_module", nargs="?")
    parser.add_argument("addon_operators", nargs="*")
    parser.add_argument("--module", action="append", default=[])
    parser.add_argument("--write-proposals", action="store_true")
    args = parser.parse_args()
    config = load()
    check(config)
    if args.action == "check":
        return 0
    if args.action == "status":
        return status(config)
    if args.action == "discover":
        return discover_addons(config, args.module, args.write_proposals)
    if args.action == "addon":
        if not args.addon_action or not args.addon_module:
            raise ValueError(
                "Usage: manage.py addon <add|enable|disable> <module> [operator ...]"
            )
        return addon_command(
            config, args.addon_action, args.addon_module, args.addon_operators
        )
    ensure_integrations(config)
    ensure_ollama(config, pull=True)
    say("READY: run .venv\\Scripts\\python.exe -m agent.run \"your request\"")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        say(f"ERROR: {exc}")
        raise SystemExit(1)
