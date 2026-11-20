"""Trusted Blender-side operations invoked by the fixed subprocess entry point."""

import hashlib
import json
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import bpy

JHV_OPERATOR = "jhv.run_dpc_automation"


class JobError(RuntimeError):
    def __init__(self, code, message, details=None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


def _jhv_preflight(params):
    try:
        path = Path(params["vbom_path"])
        root = ET.parse(path).getroot()
        article_ids = {
            article.strip()
            for part in root.iter("Part")
            if (article := part.get("name", "").rpartition("|")[2])
            and "|" in part.get("name", "") and article.strip()
            and "MODEL" not in article.upper()
        }
        if root.tag != "VBOM" or not article_ids:
            raise ValueError("Không tìm thấy Article trong VBOM")
    except (KeyError, OSError, ET.ParseError, ValueError) as exc:
        raise JobError("VBOM_INVALID", str(exc)) from exc
    existing = {
        re.sub(r"\.\d{3,}$", "", item.name).casefold()
        for datablocks in (bpy.data.scenes, bpy.data.collections)
        for item in datablocks
    }
    overlap = sorted(article for article in article_ids if article.casefold() in existing)
    if overlap:
        raise JobError(
            "ARTICLE_ALREADY_EXISTS",
            "Model đã có Article " + ", ".join(overlap) + ". Hãy dùng model gốc.",
            {"article_ids": overlap},
        )
    model = bpy.data.scenes.get("Model")
    if model is not None and "jhv_dpc_report" in model:
        del model["jhv_dpc_report"]
    return article_ids


def _jhv_report(expected):
    try:
        model = bpy.data.scenes.get("Model")
        report = json.loads(model["jhv_dpc_report"])
        articles = report["articles"]
        ids = [item["article_id"] for item in articles]
        warnings = report["warnings"]
        if report["ok"] is not True or not isinstance(articles, list):
            raise ValueError("Báo cáo add-on không xác nhận thành công")
        if set(ids) != expected or len(ids) != len(expected) or any(
            bpy.data.scenes.get(article) is None for article in expected
        ):
            raise ValueError("Các Article trong báo cáo hoặc scene không khớp VBOM")
        if not isinstance(warnings, list) or any(not isinstance(item, str) for item in warnings):
            raise ValueError("Danh sách cảnh báo JHV không hợp lệ")
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise JobError("JHV_VERIFICATION_FAILED", f"Không xác minh được báo cáo JHV: {exc}") from exc
    result = {"articles": articles, "warnings": warnings}
    if isinstance(report.get("timings"), dict):
        result["addon_timings"] = report["timings"]
    if isinstance(report.get("asset_cache"), dict):
        result["asset_cache"] = report["asset_cache"]
    if isinstance(report.get("asset_resolver"), dict):
        result["asset_resolver"] = report["asset_resolver"]
    if isinstance(report.get("elapsed_seconds"), (int, float)):
        result["addon_elapsed_seconds"] = report["elapsed_seconds"]
    return result


def refresh_jhv_index(_payload):
    # Fixed JHV entry point. The add-on uses its configured local library paths.
    import jhv_dpc

    return jhv_dpc.refresh_asset_index(
        jhv_dpc.get_blender_cache_path(), jhv_dpc._job_library_folders(jhv_dpc.get_jhv_libs())
    )


def _report_context(payload):
    return {
        "blender_version": bpy.app.version_string,
        "transport": payload.get("transport", "blender-subprocess"),
    }


def status(payload):
    operators = {}
    for operator_name in payload.get("operators", []):
        try:
            category, name = operator_name.split(".", 1)
            getattr(getattr(bpy.ops, category), name).get_rna_type()
            operators[operator_name] = True
        except (AttributeError, KeyError, RuntimeError, ValueError):
            operators[operator_name] = False
    return {
        "ok": True,
        "operators": operators,
        "operator_callable": bool(operators) and all(operators.values()),
        **_report_context(payload),
    }


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
        **_report_context(payload),
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
    """Snapshot data reachable from saved scenes, not temporary/unlinked datablocks.

    Objects/materials created by an add-on but never linked into a scene are not
    expected to persist across save/open and must not cause false failures.
    Scene membership and material-slot assignment are still checked strictly.
    """
    objects = {}
    materials = set()
    collections = set()

    for scene in sorted(bpy.data.scenes, key=lambda item: item.name):
        collections.add("scene:" + scene.name)
        # Include actual scene collection tree; don't use all bpy.data.collections.
        def walk(collection):
            collections.add("scene_collection:" + scene.name + ":" + collection.name)
            for child in collection.children:
                walk(child)
        walk(scene.collection)

        for obj in sorted(scene.objects, key=lambda item: item.name):
            entry = {
                "type": obj.type,
                "location": [round(value, 6) for value in obj.location],
                "rotation": [round(value, 6) for value in obj.rotation_euler],
                "scale": [round(value, 6) for value in obj.scale],
                "materials": [
                    slot.material.name if slot.material else None
                    for slot in obj.material_slots
                ],
                "modifiers": [modifier.name for modifier in obj.modifiers],
            }
            for slot in obj.material_slots:
                if slot.material is not None:
                    materials.add(slot.material.name)
            if obj.type == "MESH":
                entry["vertices"] = len(obj.data.vertices)
                entry["faces"] = len(obj.data.polygons)
            objects[scene.name + "::" + obj.name] = entry
    return {
        "objects": objects,
        "materials": sorted(materials),
        "collections": sorted(collections),
    }


def _perf(name, start):
    seconds = round(time.perf_counter() - start, 3)
    print(f"[PERF] {name}: {seconds:.3f}s", flush=True)
    return seconds


def _verify_after_reopen(expected, payload, prefix):
    """Verify persisted scene content and save full discrepancy beside the report."""
    t0 = time.perf_counter()
    actual = _snapshot()
    elapsed = _perf("snapshot_after_reopen", t0)
    if actual != expected:
        difference = _diff(expected, actual)
        detail_path = Path(payload["report_path"]).with_name("blender-verify-diff.json")
        detail_path.parent.mkdir(parents=True, exist_ok=True)
        detail_path.write_text(
            json.dumps(difference, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        summary = {
            group: {
                kind: len(changes[kind])
                for kind in ("added", "removed", "changed")
            }
            for group, changes in difference.items()
        }
        raise RuntimeError(
            prefix + ": " + json.dumps(summary, sort_keys=True)
            + "; details=" + str(detail_path)
        )
    return elapsed


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
    expected_articles = _jhv_preflight(params) if operator_name == JHV_OPERATOR else None
    try:
        poll_result = operation.poll()
    except Exception as exc:
        raise RuntimeError("Operator poll failed in headless context: " + str(exc)) from exc
    if not poll_result:
        raise RuntimeError("Operator poll failed in headless context")

    total_start = time.perf_counter()
    timings = {}
    t0 = time.perf_counter()
    before = _snapshot()
    timings["snapshot_before_seconds"] = _perf("snapshot_before", t0)
    t0 = time.perf_counter()
    status = operation("EXEC_DEFAULT", **params)
    timings["operator_seconds"] = _perf("operator", t0)
    if status != {"FINISHED"}:
        raise RuntimeError("Add-on operator did not finish: " + str(status))
    if expected_articles is not None:
        _jhv_report(expected_articles)
    t0 = time.perf_counter()
    after = _snapshot()
    timings["snapshot_after_seconds"] = _perf("snapshot_after", t0)
    difference = _diff(before, after)

    t0 = time.perf_counter()
    bpy.ops.wm.save_as_mainfile(filepath=payload["output_path"], check_existing=False)
    timings["save_seconds"] = _perf("save_blend", t0)
    t0 = time.perf_counter()
    bpy.ops.wm.open_mainfile(filepath=payload["output_path"], load_ui=False)
    timings["reopen_seconds"] = _perf("reopen_blend", t0)
    timings["verify_seconds"] = _verify_after_reopen(
        after, payload, "Saved Blender scene differs after reopen"
    )
    jhv_report = _jhv_report(expected_articles) if expected_articles is not None else {}
    timings["total_runner_seconds"] = _perf("runner_total", total_start)

    with open(payload["output_path"], "rb") as stream:
        output_hash = hashlib.sha256(stream.read()).hexdigest()
    report = {
        "ok": True,
        "producer": "ollama3d-generic-operator",
        "run_id": payload["run_id"],
        "operator": operator_name,
        "diff": difference,
        "timings": timings,
        "scene_count": len(bpy.data.scenes),
        "output_sha256": output_hash,
        "verified_after_reopen": True,
        **jhv_report,
        **_report_context(payload),
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
    total_start = time.perf_counter()
    timings = {}
    t0 = time.perf_counter()
    previous = _snapshot()
    timings["snapshot_before_seconds"] = _perf("snapshot_before", t0)
    step_reports = []
    for step in payload["steps"]:
        operator_name = step["operator"]
        try:
            category, name = operator_name.split(".", 1)
            operation = getattr(getattr(bpy.ops, category), name)
            _validate_operator_params(operation, step["params"])
            if not operation.poll():
                raise RuntimeError("Operator poll failed in headless context")
            t0 = time.perf_counter()
            status = operation("EXEC_DEFAULT", **step["params"])
            timings["operator_" + step["id"] + "_seconds"] = _perf("operator:" + step["id"], t0)
            if status != {"FINISHED"}:
                raise RuntimeError("Add-on operator did not finish: " + str(status))
        except Exception as exc:
            raise RuntimeError(f"Workflow step {step['id']} failed: {exc}") from exc
        t0 = time.perf_counter()
        current = _snapshot()
        timings["snapshot_" + step["id"] + "_seconds"] = _perf("snapshot:" + step["id"], t0)
        step_reports.append(
            {
                "id": step["id"],
                "capability_id": step["capability_id"],
                "operator": operator_name,
                "diff": _diff(previous, current),
            }
        )
        previous = current

    t0 = time.perf_counter()
    bpy.ops.wm.save_as_mainfile(filepath=payload["output_path"], check_existing=False)
    timings["save_seconds"] = _perf("save_blend", t0)
    t0 = time.perf_counter()
    bpy.ops.wm.open_mainfile(filepath=payload["output_path"], load_ui=False)
    timings["reopen_seconds"] = _perf("reopen_blend", t0)
    timings["verify_seconds"] = _verify_after_reopen(
        previous, payload, "Saved Blender workflow scene differs after reopen"
    )
    timings["total_runner_seconds"] = _perf("runner_total", total_start)
    _check_postconditions(payload.get("postconditions", []))
    with open(payload["output_path"], "rb") as stream:
        output_hash = hashlib.sha256(stream.read()).hexdigest()
    report = {
        "ok": True,
        "producer": "ollama3d-generic-workflow",
        "workflow_id": payload["workflow_id"],
        "run_id": payload["run_id"],
        "steps": step_reports,
        "timings": timings,
        "scene_count": len(bpy.data.scenes),
        "output_sha256": output_hash,
        "verified_after_reopen": True,
        **_report_context(payload),
    }
    with open(payload["report_path"], "w", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    return report
