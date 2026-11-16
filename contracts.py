"""JSON contract validation used by host-side adapters and tests."""

import json
from functools import lru_cache
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

SCHEMA_ROOT = Path(__file__).resolve().parent / "schemas"


@lru_cache(maxsize=None)
def validator(name):
    path = SCHEMA_ROOT / (name + ".schema.json")
    if not path.is_file():
        raise ValueError("Unknown contract schema: " + name)
    schema = json.loads(path.read_text(encoding="utf-8-sig"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def validate_contract(name, value):
    errors = sorted(
        validator(name).iter_errors(value), key=lambda item: list(item.path)
    )
    if errors:
        error = errors[0]
        location = ".".join(str(part) for part in error.path) or "root"
        raise ValueError(f"{name} contract failed at {location}: {error.message}")
    return value
