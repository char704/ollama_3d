"""Small shared helpers for the real VBA and Blender integrations."""

import datetime
import json
from pathlib import Path

from project_config import load, resolve, scoped_path as configured_path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = load()
BLENDER = resolve(CONFIG, CONFIG["paths"]["blender_exe"])


def scoped_path(value, default=None):
    return configured_path(CONFIG, value, default)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(path)


def log(action, data):
    folder = ROOT / "logs"
    folder.mkdir(exist_ok=True)
    record = {
        "time": datetime.datetime.now().astimezone().isoformat(),
        "tool": action,
        **data,
    }
    with (folder / "tool-calls.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + "\n")
