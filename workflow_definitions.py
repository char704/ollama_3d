"""Load and validate declarative Blender workflow definitions without eval."""

import json
import re
from copy import deepcopy
from pathlib import Path

_ID = re.compile(r"workflow\.[a-z][a-z0-9_]*")
_VERSION = re.compile(r"\d+\.\d+\.\d+")
_REFERENCE = re.compile(r"\$\{inputs\.([a-z][a-z0-9_]*)\}")
_INPUT_TYPES = {"path", "string"}
_POSTCONDITIONS = {
    "all_mesh_objects_have_material",
    "object_exists",
    "object_count_at_least",
}


def validate_definition(document):
    if not isinstance(document, dict) or not _ID.fullmatch(document.get("id", "")):
        raise ValueError("Workflow id must use workflow.<name>")
    if not _VERSION.fullmatch(document.get("version", "")):
        raise ValueError("Workflow version must use semantic x.y.z format")
    inputs = document.get("inputs")
    if not isinstance(inputs, dict) or not inputs:
        raise ValueError("Workflow inputs must be a non-empty object")
    for name, kind in inputs.items():
        if not re.fullmatch(r"[a-z][a-z0-9_]*", name) or kind not in _INPUT_TYPES:
            raise ValueError(f"Workflow input is invalid: {name}")
    steps = document.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ValueError("Workflow steps must be a non-empty list")
    step_ids = set()
    for step in steps:
        if not isinstance(step, dict):
            raise ValueError("Each workflow step must be an object")
        step_id = step.get("id", "")
        if not re.fullmatch(r"[a-z][a-z0-9_]*", step_id) or step_id in step_ids:
            raise ValueError(f"Workflow step id is invalid or duplicate: {step_id}")
        step_ids.add(step_id)
        if not isinstance(step.get("capability"), str) or not step["capability"]:
            raise ValueError(f"Workflow step {step_id} requires a capability")
        if not isinstance(step.get("params", {}), dict):
            raise ValueError(f"Workflow step {step_id} params must be an object")
    postconditions = document.get("postconditions", [])
    if not isinstance(postconditions, list):
        raise ValueError("Workflow postconditions must be a list")
    for condition in postconditions:
        if not isinstance(condition, dict) or condition.get("type") not in _POSTCONDITIONS:
            raise ValueError("Workflow postcondition type is not allowlisted")
        if condition["type"] == "object_exists" and (
            not isinstance(condition.get("name"), str) or not condition["name"]
        ):
            raise ValueError("object_exists postcondition requires a non-empty name")
        if condition["type"] == "object_count_at_least" and (
            type(condition.get("count")) is not int or condition["count"] < 0
        ):
            raise ValueError("object_count_at_least requires a non-negative integer count")
    _interpolate(document, {name: "validation" for name in inputs}, validate_only=True)
    return deepcopy(document)


def load_definition(directory, workflow_id):
    if not _ID.fullmatch(workflow_id):
        raise ValueError("workflow_id is invalid")
    directory = Path(directory).resolve()
    path = (directory / f"{workflow_id}.json").resolve()
    if not path.is_relative_to(directory) or not path.is_file():
        raise ValueError(f"Workflow definition is not registered: {workflow_id}")
    document = json.loads(path.read_text(encoding="utf-8-sig"))
    definition = validate_definition(document)
    if definition["id"] != workflow_id:
        raise ValueError("Workflow definition id does not match its filename")
    return definition


def _interpolate(value, inputs, validate_only=False):
    if isinstance(value, dict):
        return {key: _interpolate(item, inputs, validate_only) for key, item in value.items()}
    if isinstance(value, list):
        return [_interpolate(item, inputs, validate_only) for item in value]
    if isinstance(value, str) and "${" in value:
        match = _REFERENCE.fullmatch(value)
        if not match:
            raise ValueError("Only exact ${inputs.<name>} interpolation is supported")
        name = match.group(1)
        if name not in inputs:
            raise ValueError(f"Workflow references unknown input: {name}")
        return value if validate_only else inputs[name]
    return value


def interpolate_definition(definition, inputs):
    if not isinstance(inputs, dict):
        raise ValueError("Workflow inputs must be an object")
    expected = set(definition["inputs"])
    if set(inputs) != expected:
        missing = sorted(expected - set(inputs))
        unknown = sorted(set(inputs) - expected)
        details = []
        if missing:
            details.append("missing: " + ", ".join(missing))
        if unknown:
            details.append("unknown: " + ", ".join(unknown))
        raise ValueError("Workflow inputs do not match definition (" + "; ".join(details) + ")")
    for name, kind in definition["inputs"].items():
        if kind in ("path", "string") and not isinstance(inputs[name], str):
            raise ValueError(f"Workflow input '{name}' must be a string")
    return _interpolate(definition, inputs)
