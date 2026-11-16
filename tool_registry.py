"""Load and normalize declarative tool manifests from the project tool library."""

import json
import re
from pathlib import Path

SUPPORTED_EXECUTORS = {
    "blender_operator",
    "http",
    "python",
    "cli",
    "excel_com",
}


def _library_path(root, settings):
    if not isinstance(settings, dict):
        raise ValueError("config.json: tool_library must be an object")
    directory = settings.get("directory")
    if not isinstance(directory, str) or not directory.strip():
        raise ValueError("config.json: tool_library.directory is required")
    root = Path(root).resolve()
    path = (root / directory).resolve()
    if not path.is_relative_to(root):
        raise ValueError(
            "config.json: tool_library.directory must be inside the project"
        )
    if not path.is_dir():
        raise FileNotFoundError("Tool library directory not found: " + str(path))
    return path


def load_catalog(root, settings):
    """Return validated manifests plus executor-specific normalized views."""
    library = _library_path(root, settings)
    manifests = []
    seen = set()
    for path in sorted(library.rglob("*.json")):
        try:
            item = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Invalid tool manifest {path}: {exc}") from exc
        prefix = "Tool manifest " + str(path.relative_to(library))
        if not isinstance(item, dict):
            raise ValueError(prefix + " must contain a JSON object")
        if item.get("schema_version") != 1:
            raise ValueError(prefix + ": schema_version must be 1")
        tool_id = item.get("id", "")
        if not re.fullmatch(r"[a-z][a-z0-9_]{1,63}", tool_id):
            raise ValueError(prefix + ": id is invalid")
        if tool_id in seen:
            raise ValueError(prefix + ": duplicated id " + tool_id)
        seen.add(tool_id)
        executor = item.get("executor")
        if executor not in SUPPORTED_EXECUTORS:
            raise ValueError(prefix + ": unsupported executor " + repr(executor))
        normalized = dict(item)
        normalized["manifest_path"] = str(path)
        manifests.append(normalized)
    if not manifests:
        raise ValueError("Tool library does not contain any JSON manifests")
    return {
        "directory": str(library),
        "manifest_paths": [item["manifest_path"] for item in manifests],
        "tools": manifests,
        "blender_operators": [
            item for item in manifests if item["executor"] == "blender_operator"
        ],
    }
