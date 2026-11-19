"""Trusted Blender-side operation invoked by the official MCP extension."""

import hashlib
import json

import bpy


def _operator_subclasses():
    seen = set()
    pending = list(bpy.types.Operator.__subclasses__())
    while pending:
        cls = pending.pop()
        if cls in seen:
            continue
        seen.add(cls)
        yield cls
        pending.extend(cls.__subclasses__())


def _matching_module(class_module, modules):
    parts = class_module.split(".")
    for module in modules:
        if class_module == module or class_module.startswith(module + "."):
            return module
        if module in parts or module.rsplit(".", 1)[-1] in parts:
            return module
    return None


def _json_value(value):
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)) or type(value).__name__ == "bpy_prop_array":
        return [_json_value(item) for item in value]
    raise TypeError("Value is not JSON serializable")


def discover(payload):
    """Discover RNA metadata for operators belonging to explicitly requested modules."""
    modules = payload["modules"]
    operators = []
    for cls in _operator_subclasses():
        bl_idname = getattr(cls, "bl_idname", "")
        module = _matching_module(getattr(cls, "__module__", ""), modules)
        if not bl_idname or not module or "." not in bl_idname:
            continue
        category, name = bl_idname.split(".", 1)
        try:
            operation = getattr(getattr(bpy.ops, category), name)
            properties = operation.get_rna_type().properties
        except (AttributeError, RuntimeError):
            continue
        parameters = []
        for prop in properties:
            if prop.identifier == "rna_type" or getattr(prop, "is_hidden", False):
                continue
            parameter = {
                "identifier": prop.identifier,
                "type": prop.type,
                "subtype": getattr(prop, "subtype", ""),
                "description": getattr(prop, "description", ""),
                "is_required": bool(getattr(prop, "is_required", False)),
                "array_length": int(getattr(prop, "array_length", 0)),
            }
            if prop.type in ("POINTER", "COLLECTION"):
                parameter["supported"] = False
            try:
                default_attribute = "default_array" if parameter["array_length"] else "default"
                parameter["default"] = _json_value(getattr(prop, default_attribute))
            except (AttributeError, TypeError, ValueError):
                pass
            if prop.type in ("INT", "FLOAT"):
                for source, destination in (("hard_min", "hard_min"), ("hard_max", "hard_max")):
                    value = getattr(prop, source, None)
                    if value is not None:
                        parameter[destination] = value
            if prop.type == "ENUM":
                parameter["enum"] = [item.identifier for item in getattr(prop, "enum_items", [])]
            parameters.append(parameter)
        try:
            poll_default = bool(operation.poll())
        except Exception:
            poll_default = None
        operators.append(
            {
                "addon_module": module,
                "class_module": getattr(cls, "__module__", ""),
                "bl_idname": bl_idname,
                "bl_label": getattr(cls, "bl_label", ""),
                "bl_description": getattr(cls, "bl_description", ""),
                "bl_options": sorted(getattr(cls, "bl_options", set())),
                "params": parameters,
                "poll_default": poll_default,
            }
        )
    operators.sort(key=lambda item: item["bl_idname"])
    report = {
        "run_id": payload["run_id"],
        "modules": modules,
        "operator_count": len(operators),
        "operator_ids": [item["bl_idname"] for item in operators],
        "operators": operators,
    }
    with open(payload["report_path"], "w", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    return {
        "run_id": report["run_id"],
        "modules": modules,
        "operator_count": report["operator_count"],
        "operator_ids": report["operator_ids"],
        "report_path": payload["report_path"],
    }


def _snapshot():
    objects = {}
    for obj in sorted(bpy.data.objects, key=lambda item: item.name):
        entry = {
            "type": obj.type,
            "location": [round(value, 6) for value in obj.location],
            "rotation": [round(value, 6) for value in obj.rotation_euler],
            "scale": [round(value, 6) for value in obj.scale],
            "materials": [slot.name for slot in obj.material_slots],
            "modifiers": [modifier.name for modifier in obj.modifiers],
        }
        if obj.type == "MESH":
            entry["vertices"] = len(obj.data.vertices)
            entry["faces"] = len(obj.data.polygons)
        objects[obj.name] = entry
    return {
        "objects": objects,
        "materials": sorted(
            material.name for material in bpy.data.materials if material.users > 0
        ),
        "collections": sorted(
            collection.name for collection in bpy.data.collections if collection.users > 0
        ),
    }


def _diff(before, after):
    result = {}
    for group in ("objects", "materials", "collections"):
        before_values = before[group]
        after_values = after[group]
        before_keys = set(before_values if isinstance(before_values, dict) else before_values)
        after_keys = set(after_values if isinstance(after_values, dict) else after_values)
        changed = []
        if isinstance(before_values, dict):
            changed = sorted(
                key
                for key in before_keys & after_keys
                if before_values[key] != after_values[key]
            )
        result[group] = {
            "added": sorted(after_keys - before_keys),
            "removed": sorted(before_keys - after_keys),
            "changed": changed,
        }
    return result


def _validate_operator_params(operation, params):
    properties = {
        prop.identifier: prop
        for prop in operation.get_rna_type().properties
        if prop.identifier != "rna_type" and not getattr(prop, "is_hidden", False)
    }
    unknown = sorted(set(params) - set(properties))
    if unknown:
        raise ValueError("Unknown operator parameter(s): " + ", ".join(unknown))
    for name, value in params.items():
        prop = properties[name]
        expected = prop.type
        array_length = int(getattr(prop, "array_length", 0))
        if expected in ("POINTER", "COLLECTION"):
            raise ValueError(f"Operator parameter '{name}' is not supported")
        if array_length:
            if not isinstance(value, (list, tuple)) or len(value) != array_length:
                raise ValueError(f"Operator parameter '{name}' must have {array_length} values")
            values = value
        else:
            values = [value]
        for item in values:
            valid = (
                (expected == "BOOLEAN" and type(item) is bool)
                or (expected == "INT" and type(item) is int)
                or (expected == "FLOAT" and type(item) in (int, float))
                or (expected in ("STRING", "ENUM") and isinstance(item, str))
            )
            if not valid:
                raise ValueError(f"Operator parameter '{name}' has the wrong type")
        if expected == "ENUM":
            allowed = {item.identifier for item in getattr(prop, "enum_items", [])}
            if value not in allowed:
                raise ValueError(f"Operator parameter '{name}' has an invalid enum value")


def run_operator(payload):
    """Run one allowlisted operator payload, persist the scene, and verify the result."""
    operator_name = payload["operator"]
    try:
        category, name = operator_name.split(".", 1)
        operation = getattr(getattr(bpy.ops, category), name)
    except (AttributeError, ValueError) as exc:
        raise RuntimeError("Blender operator does not exist: " + operator_name) from exc
    params = payload["params"]
    _validate_operator_params(operation, params)
    try:
        poll_result = operation.poll()
    except Exception as exc:
        raise RuntimeError("Operator poll failed in headless context: " + str(exc)) from exc
    if not poll_result:
        raise RuntimeError("Operator poll failed in headless context")

    before = _snapshot()
    try:
        status = operation("EXEC_DEFAULT", **params)
    except RuntimeError:
        raise
    if status != {"FINISHED"}:
        raise RuntimeError("Add-on operator did not finish: " + str(status))
    after = _snapshot()
    difference = _diff(before, after)

    bpy.ops.wm.save_as_mainfile(filepath=payload["output_path"], check_existing=False)
    bpy.ops.wm.open_mainfile(filepath=payload["output_path"], load_ui=False)
    reopened = _snapshot()
    if reopened != after:
        raise RuntimeError(
            "Saved Blender scene differs after reopen: "
            + json.dumps(_diff(after, reopened), sort_keys=True)
        )

    with open(payload["output_path"], "rb") as stream:
        output_hash = hashlib.sha256(stream.read()).hexdigest()
    report = {
        "ok": True,
        "producer": "ollama3d-generic-operator",
        "run_id": payload["run_id"],
        "operator": operator_name,
        "diff": difference,
        "output_sha256": output_hash,
        "verified_after_reopen": True,
        "transport": "official-blender-mcp",
    }
    with open(payload["report_path"], "w", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    return report


def _check_postconditions(postconditions):
    for condition in postconditions:
        kind = condition["type"]
        if kind == "all_mesh_objects_have_material":
            meshes = [obj for obj in bpy.data.objects if obj.type == "MESH"]
            if not meshes or any(not obj.material_slots for obj in meshes):
                raise RuntimeError("Postcondition failed: all mesh objects must have a material")
        elif kind == "object_exists":
            if bpy.data.objects.get(condition["name"]) is None:
                raise RuntimeError("Postcondition failed: object does not exist: " + condition["name"])
        elif kind == "object_count_at_least":
            if len(bpy.data.objects) < condition["count"]:
                raise RuntimeError(
                    "Postcondition failed: object count is below " + str(condition["count"])
                )
        else:
            raise RuntimeError("Unsupported postcondition: " + str(kind))


def run_steps(payload):
    """Execute fixed operator steps in one Blender process and save only after all succeed."""
    previous = _snapshot()
    step_reports = []
    for step in payload["steps"]:
        operator_name = step["operator"]
        try:
            category, name = operator_name.split(".", 1)
            operation = getattr(getattr(bpy.ops, category), name)
            _validate_operator_params(operation, step["params"])
            if not operation.poll():
                raise RuntimeError("Operator poll failed in headless context")
            status = operation("EXEC_DEFAULT", **step["params"])
            if status != {"FINISHED"}:
                raise RuntimeError("Add-on operator did not finish: " + str(status))
        except Exception as exc:
            raise RuntimeError(f"Workflow step {step['id']} failed: {exc}") from exc
        current = _snapshot()
        step_reports.append(
            {
                "id": step["id"],
                "capability_id": step["capability_id"],
                "operator": operator_name,
                "diff": _diff(previous, current),
            }
        )
        previous = current

    bpy.ops.wm.save_as_mainfile(filepath=payload["output_path"], check_existing=False)
    bpy.ops.wm.open_mainfile(filepath=payload["output_path"], load_ui=False)
    reopened = _snapshot()
    if reopened != previous:
        raise RuntimeError(
            "Saved Blender workflow scene differs after reopen: "
            + json.dumps(_diff(previous, reopened), sort_keys=True)
        )
    _check_postconditions(payload.get("postconditions", []))
    with open(payload["output_path"], "rb") as stream:
        output_hash = hashlib.sha256(stream.read()).hexdigest()
    report = {
        "ok": True,
        "producer": "ollama3d-generic-workflow",
        "workflow_id": payload["workflow_id"],
        "run_id": payload["run_id"],
        "steps": step_reports,
        "output_sha256": output_hash,
        "verified_after_reopen": True,
        "transport": "official-blender-mcp",
    }
    with open(payload["report_path"], "w", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    return report


def _hex_rgba(value):
    return tuple(int(value[index : index + 2], 16) / 255 for index in (1, 3, 5)) + (1.0,)


def create_colored_primitive(payload):
    """Create one allowlisted Blender primitive, save it, reopen it, and verify it."""
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)

    primitive = payload["primitive"]
    size = payload["size"]
    if primitive == "cube":
        bpy.ops.mesh.primitive_cube_add(size=size)
    elif primitive == "uv_sphere":
        bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, radius=size / 2)
    elif primitive == "cylinder":
        bpy.ops.mesh.primitive_cylinder_add(vertices=32, radius=size / 2, depth=size)
    else:
        raise ValueError("Unsupported primitive: " + primitive)

    obj = bpy.context.active_object
    obj.name = payload["object_name"]
    obj["ollama3d_run_id"] = payload["run_id"]
    obj["ollama3d_color_hex"] = payload["color_hex"]
    material = bpy.data.materials.new(payload["object_name"] + " Material")
    material.diffuse_color = _hex_rgba(payload["color_hex"])
    obj.data.materials.append(material)

    bpy.ops.wm.save_as_mainfile(filepath=payload["output_path"], check_existing=False)
    bpy.ops.wm.open_mainfile(filepath=payload["output_path"], load_ui=False)
    persisted = bpy.data.objects.get(payload["object_name"])
    if persisted is None:
        raise RuntimeError("Created object was not persisted")
    if persisted.get("ollama3d_run_id") != payload["run_id"]:
        raise RuntimeError("Created object has the wrong run_id")
    if persisted.get("ollama3d_color_hex") != payload["color_hex"]:
        raise RuntimeError("Created object has the wrong color proof")
    if persisted.active_material is None:
        raise RuntimeError("Created object material was not persisted")

    with open(payload["output_path"], "rb") as stream:
        output_hash = hashlib.sha256(stream.read()).hexdigest()
    report = {
        "ok": True,
        "status": "completed",
        "run_id": payload["run_id"],
        "operation": "create_colored_primitive",
        "primitive": primitive,
        "object_name": payload["object_name"],
        "color_hex": payload["color_hex"],
        "size": size,
        "output_path": payload["output_path"],
        "output_sha256": output_hash,
        "verified_after_reopen": True,
        "transport": "official-blender-mcp",
    }
    with open(payload["report_path"], "w", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    report["proof_path"] = payload["report_path"]
    return report


def apply_vbom(payload):
    operator_name = payload["operator"]
    group_name, action_name = operator_name.split(".", 1)
    operator = getattr(getattr(bpy.ops, group_name), action_name)
    status = operator(filepath=payload["vbom_path"], run_id=payload["run_id"])
    if status != {"FINISHED"}:
        raise RuntimeError("Add-on did not finish: " + str(status))

    report = json.loads(bpy.context.scene["ollama3d_proof_report"])
    bpy.ops.wm.save_as_mainfile(filepath=payload["output_path"], check_existing=False)
    bpy.ops.wm.open_mainfile(filepath=payload["output_path"], load_ui=False)

    persisted = json.loads(bpy.context.scene["ollama3d_proof_report"])
    if persisted["run_id"] != payload["run_id"]:
        raise RuntimeError("Saved scene has the wrong run_id")
    for item in persisted["applied"]:
        obj = bpy.data.objects[item["object"]]
        if obj.get("ollama3d_run_id") != payload["run_id"] or obj.get("bom_color_hex") != item["color"]:
            raise RuntimeError("Saved object verification failed: " + item["object"])
        if obj.active_material is None or obj.active_material.name != item["material"]:
            raise RuntimeError("Saved material verification failed: " + item["object"])

    with open(payload["output_path"], "rb") as stream:
        output_hash = hashlib.sha256(stream.read()).hexdigest()
    report.update(
        {
            "ok": True,
            "output_path": payload["output_path"],
            "output_sha256": output_hash,
            "verified_after_reopen": True,
            "transport": "official-blender-mcp",
        }
    )
    with open(payload["report_path"], "w", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    return report
