"""Fixed test helper that records persisted footwear material state."""

import json
import sys

import bpy

result_path = sys.argv[sys.argv.index("--") + 1]
result = {
    name: {
        "material": bpy.data.objects[name].active_material.name,
        "color_hex": bpy.data.objects[name].get("bom_color_hex"),
        "diffuse_color": [
            round(value, 6)
            for value in bpy.data.objects[name].active_material.diffuse_color
        ],
    }
    for name in ("Upper", "Sole", "Laces")
}
with open(result_path, "w", encoding="utf-8") as stream:
    json.dump(result, stream, ensure_ascii=False, indent=2)
