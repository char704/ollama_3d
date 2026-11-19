"""Convert Blender RNA discovery data into safe registry parameter schemas."""

import re
from copy import deepcopy

from project_config import scoped_path

_SCALAR_TYPES = {
    "BOOLEAN": "boolean",
    "INT": "integer",
    "FLOAT": "number",
    "STRING": "string",
    "ENUM": "string",
}


def to_schema(operator_dict):
    properties = {}
    required = []
    unsupported = []
    for parameter in operator_dict.get("params", []):
        identifier = parameter["identifier"]
        if parameter.get("supported") is False or parameter.get("type") not in _SCALAR_TYPES:
            unsupported.append(identifier)
            continue
        schema = {"type": _SCALAR_TYPES[parameter["type"]]}
        if parameter.get("description"):
            schema["description"] = parameter["description"]
        if parameter.get("type") == "ENUM":
            schema["enum"] = list(parameter.get("enum", []))
        if parameter.get("type") in ("INT", "FLOAT"):
            if parameter.get("hard_min") is not None:
                schema["minimum"] = parameter["hard_min"]
            if parameter.get("hard_max") is not None:
                schema["maximum"] = parameter["hard_max"]
        if parameter.get("subtype") in ("FILE_PATH", "DIR_PATH"):
            schema["x-path"] = True
        array_length = parameter.get("array_length", 0)
        if array_length:
            schema = {
                "type": "array",
                "items": schema,
                "minItems": array_length,
                "maxItems": array_length,
            }
        elif "default" in parameter:
            schema["default"] = deepcopy(parameter["default"])
        properties[identifier] = schema
        if parameter.get("is_required"):
            required.append(identifier)
    result = {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }
    if unsupported:
        result["unsupported"] = unsupported
    return result


def _validate_value(name, schema, value, config):
    expected = schema.get("type")
    valid = {
        "boolean": type(value) is bool,
        "integer": type(value) is int,
        "number": type(value) in (int, float),
        "string": isinstance(value, str),
        "array": isinstance(value, list),
    }.get(expected, False)
    if not valid:
        raise ValueError(f"Parameter '{name}' must be {expected}")
    if expected == "array":
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", len(value)):
            raise ValueError(f"Parameter '{name}' has the wrong array length")
        return [
            _validate_value(f"{name}[{index}]", schema["items"], item, config)
            for index, item in enumerate(value)
        ]
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"Parameter '{name}' must be one of {schema['enum']}")
    if "minimum" in schema and value < schema["minimum"]:
        raise ValueError(f"Parameter '{name}' is below the minimum {schema['minimum']}")
    if "maximum" in schema and value > schema["maximum"]:
        raise ValueError(f"Parameter '{name}' is above the maximum {schema['maximum']}")
    if schema.get("x-path"):
        try:
            return str(scoped_path(config, value))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Parameter '{name}' is outside the configured path scope") from exc
    return value


def validate_params(schema, params, config):
    if not isinstance(params, dict):
        raise ValueError("Parameters must be an object")
    properties = schema.get("properties", {})
    unknown = sorted(set(params) - set(properties))
    if unknown:
        raise ValueError("Unknown parameter(s): " + ", ".join(unknown))
    missing = [name for name in schema.get("required", []) if name not in params]
    if missing:
        raise ValueError("Missing required parameter(s): " + ", ".join(missing))
    return {
        name: _validate_value(name, properties[name], value, config)
        for name, value in params.items()
    }


def _safe_name(value):
    value = re.sub(r"[^a-z0-9_]+", "_", value.casefold()).strip("_")
    if not value or not value[0].isalpha():
        value = "operator_" + value
    return value


def propose_entries(discovered, registry):
    existing_targets = {item["target"] for item in registry.items(enabled_only=False)}
    proposals = []
    for operator in discovered.get("operators", []):
        target = operator["bl_idname"]
        if target in existing_targets:
            continue
        module = operator.get("addon_module") or operator.get("module")
        if not module:
            raise ValueError(f"Discovered operator {target} does not identify its add-on module")
        schema = to_schema(operator)
        module_id = ".".join(_safe_name(part) for part in module.split("."))
        description = operator.get("bl_description") or operator.get("bl_label") or target
        proposals.append(
            {
                "id": f"blender.{module_id}.{_safe_name(target.split('.', 1)[1])}",
                "provider": "blender_operator",
                "handler": "generic_operator",
                "target": target,
                "addon_module": module,
                "description": description,
                "risk": "filesystem"
                if any(value.get("x-path") for value in schema["properties"].values())
                else "mutating",
                "params": schema,
                "expose": "generic",
                "background_safe": operator.get("poll_default") is True,
                "enabled": False,
            }
        )
    return proposals
