import bpy
import json
import sys

arguments = sys.argv[sys.argv.index("--") + 1:]
package_path, module_name, report_path = arguments

try:
    bpy.ops.preferences.addon_install(
        filepath=package_path,
        overwrite=True,
        enable_on_install=True,
    )
    if module_name not in bpy.context.preferences.addons:
        bpy.ops.preferences.addon_enable(module=module_name)
    bpy.ops.wm.save_userpref()
    result = {"ok": True, "module": module_name, "package": package_path}
except Exception as exc:
    result = {"ok": False, "module": module_name, "error": str(exc)}

with open(report_path, "w", encoding="utf-8") as stream:
    json.dump(result, stream, ensure_ascii=False, indent=2)
if not result["ok"]:
    raise RuntimeError(result["error"])
