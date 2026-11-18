"""Trusted Blender-side operation invoked by the official MCP extension."""

import hashlib
import json

import bpy


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
