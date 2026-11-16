"""Shared configuration for the API, launcher and registered WebUI tool."""

import json
import os
import re
from pathlib import Path
from urllib.parse import urlparse

from tool_registry import load_catalog

ROOT = Path(__file__).resolve().parent
CONFIG_FILE = ROOT / "config.json"
ROUTES = {
    "files": "/files",
    "export": "/excel/export-vbom",
    "apply": "/blender/apply-vbom",
    "result": "/results/{run_id}",
}
WORKFLOW_OPERATIONS = tuple(ROUTES)
LOCAL_ROUTES = {
    "operators": "/blender/operators",
    "run_operator": "/blender/operators/run",
    "agent": "/blender/agent",
    "agent_job": "/blender/jobs/{run_id}",
    "cancel_agent_job": "/blender/jobs/{run_id}/cancel",
    "bom_pipeline": "/workflows/bom",
    "bom_pipeline_job": "/workflows/bom/{run_id}",
}


def _validate_blender_agent(config):
    agent = config.get("blender_agent", {})
    if not isinstance(agent, dict) or type(agent.get("enabled")) is not bool:
        raise ValueError("config.json: blender_agent.enabled must be boolean")
    integer_ranges = {
        "startup_timeout_seconds": (5, 300),
        "job_timeout_seconds": (5, 3600),
        "hung_grace_seconds": (1, 300),
        "max_queued_jobs": (1, 1000),
    }
    for key, limits in integer_ranges.items():
        value = agent.get(key)
        if type(value) is not int or not limits[0] <= value <= limits[1]:
            raise ValueError(f"config.json: blender_agent.{key} is invalid")
    for key in ("poll_interval_seconds", "heartbeat_interval_seconds"):
        value = agent.get(key)
        if type(value) not in (int, float) or not 0.05 <= value <= 10:
            raise ValueError(f"config.json: blender_agent.{key} is invalid")
    if type(agent.get("auto_restart_hung")) is not bool:
        raise ValueError("config.json: blender_agent.auto_restart_hung must be boolean")


def _validate_blender_operators(config):
    operators = config.get("blender_operators", [])
    if not isinstance(operators, list):
        raise ValueError("config.json: blender_operators must be a list")
    seen = set()
    supported_types = {"string", "integer", "number", "boolean"}
    for index, item in enumerate(operators):
        prefix = f"config.json: blender_operators[{index}]"
        if not isinstance(item, dict):
            raise ValueError(prefix + " must be an object")
        operator_id = item.get("id", "")
        if not re.fullmatch(r"[a-z][a-z0-9_]{1,63}", operator_id):
            raise ValueError(prefix + ".id is invalid")
        if operator_id in seen:
            raise ValueError(prefix + ".id is duplicated")
        seen.add(operator_id)
        if not isinstance(item.get("name"), str) or not item["name"].strip():
            raise ValueError(prefix + ".name is required")
        if (
            not isinstance(item.get("description"), str)
            or not item["description"].strip()
        ):
            raise ValueError(prefix + ".description is required")
        if not re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*", item.get("operator", "")
        ):
            raise ValueError(prefix + ".operator must have the form group.name")
        if item.get("execution_mode") not in ("one_shot", "persistent"):
            raise ValueError(prefix + ".execution_mode must be one_shot or persistent")
        for key in ("enabled", "load_model", "save_after"):
            if key in item and type(item[key]) is not bool:
                raise ValueError(prefix + f".{key} must be boolean")
        if "exposed_to_model" in item and type(item["exposed_to_model"]) is not bool:
            raise ValueError(prefix + ".exposed_to_model must be boolean")
        timeout = item.get("timeout_seconds", 30)
        if type(timeout) is not int or not 1 <= timeout <= 300:
            raise ValueError(prefix + ".timeout_seconds must be from 1 to 300")
        parameters = item.get("parameters", {})
        if not isinstance(parameters, dict):
            raise ValueError(prefix + ".parameters must be an object")
        for name, spec in parameters.items():
            param_prefix = prefix + f".parameters.{name}"
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) or not isinstance(
                spec, dict
            ):
                raise ValueError(param_prefix + " is invalid")
            if spec.get("type") not in supported_types:
                raise ValueError(param_prefix + ".type is invalid")
            if "enum" in spec and (
                not isinstance(spec["enum"], list) or not spec["enum"]
            ):
                raise ValueError(param_prefix + ".enum must be a non-empty list")


def load(path=None):
    path = Path(path or CONFIG_FILE).resolve()
    config = json.loads(path.read_text(encoding="utf-8-sig"))
    profile = config.get("profile", "custom")
    if not isinstance(profile, str) or not profile.strip():
        raise ValueError("config.json: profile must be a non-empty string")
    config["profile"] = profile.strip()
    workflow = config.get("workflow")
    if not isinstance(workflow, dict):
        raise ValueError("config.json: workflow must be an object")
    if set(workflow) != set(WORKFLOW_OPERATIONS):
        raise ValueError(
            "config.json: workflow must define files, export, apply and result"
        )
    for key in ("api_port", "webui_port"):
        value = config["services"][key]
        if type(value) is not int or not 1024 <= value <= 65535:
            raise ValueError(f"config.json: invalid {key}")
    if config["services"]["api_port"] == config["services"]["webui_port"]:
        raise ValueError("API and WebUI ports must be different")
    parsed = urlparse(config["services"]["ollama_url"])
    if parsed.scheme != "http" or parsed.hostname not in (
        "127.0.0.1",
        "localhost",
        "::1",
    ):
        raise ValueError("This local prototype requires a local Ollama HTTP URL")
    if (
        parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
    ):
        raise ValueError("ollama_url must be a base URL without credentials or a path")
    if (parsed.port or 80) in (
        config["services"]["api_port"],
        config["services"]["webui_port"],
    ):
        raise ValueError("Ollama, API and WebUI must use different ports")
    if not config["ollama"]["model"].strip():
        raise ValueError("config.json: ollama.model is required")
    _validate_blender_agent(config)
    catalog = load_catalog(path.parent, config.get("tool_library"))
    config["_tool_catalog"] = catalog
    config["blender_operators"] = catalog["blender_operators"]
    _validate_blender_operators(config)
    for key in ("inputs", "outputs", "default_model"):
        if (
            not isinstance(config["paths"][key], str)
            or not config["paths"][key].strip()
        ):
            raise ValueError(f"config.json: paths.{key} is required")
    config["_root"] = path.parent
    for operation in WORKFLOW_OPERATIONS:
        endpoint(config, operation)
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


def endpoint(config, operation):
    if operation in LOCAL_ROUTES:
        return {
            "url": service_url(config, "api") + LOCAL_ROUTES[operation],
            "token_env": "",
        }
    if operation not in WORKFLOW_OPERATIONS:
        raise ValueError("Unknown workflow operation: " + operation)
    item = config["workflow"].get(operation, {})
    if not isinstance(item, dict):
        raise ValueError(f"config.json: workflow.{operation} must be an object")
    provider = item.get("provider")
    if provider == "local":
        return {"url": service_url(config, "api") + ROUTES[operation], "token_env": ""}
    if provider != "http":
        raise ValueError(
            f"config.json: workflow.{operation}.provider must be local or http"
        )
    url = item.get("url", "")
    parsed = urlparse(url)
    if (
        parsed.scheme not in ("http", "https")
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise ValueError(
            f"config.json: workflow.{operation}.url must be an HTTP(S) URL without credentials"
        )
    if operation == "result" and "{run_id}" not in url:
        raise ValueError("workflow.result.url must contain {run_id}")
    token_env = item.get("token_env", "")
    if not isinstance(token_env, str):
        raise ValueError(
            f"config.json: workflow.{operation}.token_env must be a string"
        )
    return {"url": url, "token_env": token_env}


def scoped_path(config, value, default=None):
    path = resolve(config, str(value or default))
    root = config["_root"].resolve()
    allowed = [
        root,
        data_path(config, "inputs"),
        data_path(config, "outputs"),
        *[resolve(config, p) for p in config["paths"].get("allowed_roots", [])],
    ]
    if path != data_path(config, "default_model") and not any(
        path.is_relative_to(p) for p in allowed
    ):
        raise ValueError(
            "Path must be inside the project or a configured input/output/allowed directory"
        )
    if path.is_relative_to(root):
        if any(
            p.startswith(".")
            or p.casefold() in ("webui-data", "runtime", "archive", "logs")
            for p in path.relative_to(root).parts
        ):
            raise ValueError("This directory is reserved for application data")
    return path
