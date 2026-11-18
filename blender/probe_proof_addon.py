import bpy
import json
import sys

arguments = sys.argv[sys.argv.index("--") + 1:]
report_path = arguments[0]
module_name = arguments[1]
operator_name = arguments[2]

try:
    module = __import__(module_name)
    version = ".".join(str(value) for value in module.bl_info["version"])
    group_name, action_name = operator_name.split(".", 1)
    group = getattr(bpy.ops, group_name, None)
    operator = getattr(group, action_name, None) if group else None
    if operator is None:
        raise RuntimeError("Operator is not registered: bpy.ops." + operator_name)
    result = {
        "ok": True,
        "module": module_name,
        "addon_version": version,
        "operator": operator_name,
        "operator_callable": True,
        "blender_version": bpy.app.version_string,
    }
except Exception as exc:
    result = {"ok": False, "error": str(exc), "module": module_name, "operator": operator_name}

with open(report_path, "w", encoding="utf-8") as stream:
    json.dump(result, stream, ensure_ascii=False, indent=2)
if not result["ok"]:
    raise RuntimeError(result["error"])
