"""Validated configuration shared by the MCP server and local launcher."""

import json
import os
import re
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
CONFIG_FILE = ROOT / "config.json"


def load(path=None):
    path = Path(path or CONFIG_FILE).resolve()
    config = json.loads(path.read_text(encoding="utf-8-sig"))
    config["_root"] = path.parent

    if not isinstance(config.get("profile"), str) or not config["profile"].strip():
        raise ValueError("config.json: profile must be a non-empty string")
    if not isinstance(config.get("capability_registry"), str) or not config["capability_registry"].strip():
        raise ValueError("config.json: capability_registry is required")
    for key in ("api_port", "webui_port"):
        value = config.get("services", {}).get(key)
        if type(value) is not int or not 1024 <= value <= 65535:
            raise ValueError(f"config.json: invalid {key}")
    if config["services"]["api_port"] == config["services"]["webui_port"]:
        raise ValueError("API and WebUI ports must be different")

    parsed = urlparse(config["services"].get("ollama_url", ""))
    if (
        parsed.scheme != "http"
        or parsed.hostname not in ("127.0.0.1", "localhost", "::1")
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
    ):
        raise ValueError("ollama_url must be a local HTTP base URL")
    if (parsed.port or 80) in (
        config["services"]["api_port"],
        config["services"]["webui_port"],
    ):
        raise ValueError("Ollama, API and WebUI must use different ports")

    ollama = config.get("ollama", {})
    for key in (
        "model",
        "router_model",
        "utility_model",
        "executable",
        "models_directory",
    ):
        if not isinstance(ollama.get(key), str) or not ollama[key].strip():
            raise ValueError(f"config.json: ollama.{key} is required")

    mcp = config.get("mcp", {})
    if mcp.get("path") != "/mcp" or not re.fullmatch(
        r"[a-z][a-z0-9_-]{1,63}", mcp.get("server_id", "")
    ):
        raise ValueError("config.json: invalid MCP configuration")

    excel = config.get("excel_vba", {})
    for key in ("executable", "addin_path"):
        if not isinstance(excel.get(key), str) or not excel[key].strip():
            raise ValueError(f"config.json: excel_vba.{key} is required")
    if type(excel.get("timeout_seconds")) is not int or not 15 <= excel["timeout_seconds"] <= 600:
        raise ValueError("config.json: excel_vba.timeout_seconds is invalid")

    addon = config.get("blender_addon", {})
    if not isinstance(addon.get("package"), str) or not addon["package"].strip():
        raise ValueError("config.json: blender_addon.package is required")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", addon.get("module", "")):
        raise ValueError("config.json: blender_addon.module is invalid")
    if type(addon.get("timeout_seconds")) is not int or not 30 <= addon["timeout_seconds"] <= 600:
        raise ValueError("config.json: blender_addon.timeout_seconds is invalid")
    if addon.get("transport", "subprocess") not in ("subprocess", "official_mcp"):
        raise ValueError("config.json: blender_addon.transport is invalid")

    bridge = config.get("official_blender_mcp", {})
    if addon.get("transport", "subprocess") == "official_mcp":
        if bridge.get("host") != "127.0.0.1":
            raise ValueError("config.json: official_blender_mcp.host must be 127.0.0.1")
        if not re.fullmatch(r"\d+\.\d+\.\d+", bridge.get("version", "")):
            raise ValueError("config.json: official_blender_mcp.version is invalid")
        if not isinstance(bridge.get("package"), str) or not bridge["package"].strip():
            raise ValueError("config.json: official_blender_mcp.package is required")
        download = urlparse(bridge.get("download_url", ""))
        if download.scheme != "https" or download.hostname != "projects.blender.org":
            raise ValueError("config.json: official_blender_mcp.download_url is invalid")
        if not re.fullmatch(r"[0-9a-f]{64}", bridge.get("sha256", "")):
            raise ValueError("config.json: official_blender_mcp.sha256 is invalid")

    paths = config.get("paths", {})
    for key in ("inputs", "outputs", "default_model", "blender_exe"):
        if not isinstance(paths.get(key), str) or not paths[key].strip():
            raise ValueError(f"config.json: paths.{key} is required")
    if not isinstance(paths.get("allowed_roots", []), list):
        raise ValueError("config.json: paths.allowed_roots must be a list")
    if config.get("workflow", {}).get("max_concurrent_runs") != 1:
        raise ValueError("config.json: workflow.max_concurrent_runs must be 1")
    return config


def resolve(config, value):
    path = Path(os.path.expandvars(value)).expanduser()
    return (path if path.is_absolute() else config["_root"] / path).resolve()


def data_path(config, key):
    return resolve(config, config["paths"][key])


def service_url(config, name):
    if name == "ollama":
        return config["services"]["ollama_url"].rstrip("/")
    return f"http://127.0.0.1:{config['services'][name + '_port']}"


def scoped_path(config, value, default=None):
    path = resolve(config, str(value or default))
    root = config["_root"].resolve()
    allowed = [
        root,
        data_path(config, "inputs"),
        data_path(config, "outputs"),
        *[resolve(config, item) for item in config["paths"].get("allowed_roots", [])],
    ]
    if path != data_path(config, "default_model") and not any(
        path.is_relative_to(item) for item in allowed
    ):
        raise ValueError(
            "Path must be inside the project or a configured input/output/allowed directory"
        )
    if path.is_relative_to(root) and any(
        part.startswith(".")
        or part.casefold() in ("webui-data", "runtime", "archive", "logs")
        for part in path.relative_to(root).parts
    ):
        raise ValueError("This directory is reserved for application data")
    return path
