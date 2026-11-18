import bpy
import hashlib
import json
import sys

arguments = sys.argv[sys.argv.index("--") + 1:]
vbom_path, output_path, report_path, run_id, operator_name = arguments

group_name, action_name = operator_name.split(".", 1)
operator = getattr(getattr(bpy.ops, group_name), action_name)
status = operator(filepath=vbom_path, run_id=run_id)
if status != {"FINISHED"}:
    raise RuntimeError("Add-on did not finish: " + str(status))

report = json.loads(bpy.context.scene["ollama3d_proof_report"])
bpy.ops.wm.save_as_mainfile(filepath=output_path, check_existing=False)
bpy.ops.wm.open_mainfile(filepath=output_path, load_ui=False)

persisted = json.loads(bpy.context.scene["ollama3d_proof_report"])
if persisted["run_id"] != run_id:
    raise RuntimeError("Saved scene has the wrong run_id")
for item in persisted["applied"]:
    obj = bpy.data.objects[item["object"]]
    if obj.get("ollama3d_run_id") != run_id or obj.get("bom_color_hex") != item["color"]:
        raise RuntimeError("Saved object verification failed: " + item["object"])
    if obj.active_material is None or obj.active_material.name != item["material"]:
        raise RuntimeError("Saved material verification failed: " + item["object"])

with open(output_path, "rb") as stream:
    output_hash = hashlib.sha256(stream.read()).hexdigest()
report.update({
    "ok": True,
    "output_path": output_path,
    "output_sha256": output_hash,
    "verified_after_reopen": True,
})
with open(report_path, "w", encoding="utf-8") as stream:
    json.dump(report, stream, ensure_ascii=False, indent=2)
