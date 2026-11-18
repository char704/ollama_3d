bl_info = {
    "name": "Ollama3D Proof VBOM Importer",
    "author": "Ollama3D",
    "version": (1, 0, 0),
    "blender": (4, 0, 0),
    "category": "Import-Export",
}

import json
import xml.etree.ElementTree as ET

import bpy
from bpy.props import StringProperty


def _linear(value):
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


class OLLAMA3D_PROOF_OT_apply_vbom(bpy.types.Operator):
    bl_idname = "ollama3d_proof.apply_vbom"
    bl_label = "Apply Ollama3D Proof VBOM"
    bl_options = {"REGISTER", "UNDO"}

    filepath: StringProperty(subtype="FILE_PATH")
    run_id: StringProperty()

    def execute(self, context):
        try:
            root = ET.parse(self.filepath).getroot()
            if root.tag != "vbom" or root.get("format") != "proof-v1":
                raise ValueError("Expected proof-v1 VBOM")
            if root.get("run_id") != self.run_id:
                raise ValueError("VBOM run_id does not match the Blender request")
            items = list(root.findall("item"))
            names = [item.get("object") for item in items]
            if len(items) != 3 or set(names) != {"Upper", "Sole", "Laces"}:
                raise ValueError("VBOM must map Upper, Sole and Laces exactly once")
            applied = []
            for item in items:
                name = item.get("object")
                obj = bpy.data.objects.get(name)
                if obj is None or obj.type != "MESH":
                    raise ValueError("Missing mesh: " + str(name))
                color = item.get("color", "")
                if len(color) != 7 or not color.startswith("#"):
                    raise ValueError("Invalid color for " + name)
                rgb = tuple(_linear(int(color[index:index + 2], 16) / 255) for index in (1, 3, 5))
                roughness = float(item.get("roughness"))
                metallic = float(item.get("metallic"))
                if not 0 <= roughness <= 1 or not 0 <= metallic <= 1:
                    raise ValueError("Material values must be between zero and one")
                material = bpy.data.materials.new(item.get("material"))
                material.use_nodes = True
                shader = material.node_tree.nodes.get("Principled BSDF")
                shader.inputs["Base Color"].default_value = (*rgb, 1)
                shader.inputs["Roughness"].default_value = roughness
                shader.inputs["Metallic"].default_value = metallic
                material.diffuse_color = (*rgb, 1)
                obj.data.materials.clear()
                obj.data.materials.append(material)
                obj["ollama3d_run_id"] = self.run_id
                obj["bom_color_hex"] = color
                applied.append({
                    "object": name,
                    "material": material.name,
                    "color": color,
                    "roughness": roughness,
                    "metallic": metallic,
                })
            report = {
                "producer": "ollama3d-blender-addon",
                "addon_version": "1.0.0",
                # Blender exposes the runtime class identifier through self.bl_idname
                # in some versions; keep the public operator contract stable.
                "operator": "ollama3d_proof.apply_vbom",
                "run_id": self.run_id,
                "source_vbom": self.filepath,
                "applied": applied,
            }
            context.scene["ollama3d_proof_report"] = json.dumps(report)
            self.report({"INFO"}, "Applied proof VBOM to three objects")
            return {"FINISHED"}
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}


def register():
    bpy.utils.register_class(OLLAMA3D_PROOF_OT_apply_vbom)


def unregister():
    bpy.utils.unregister_class(OLLAMA3D_PROOF_OT_apply_vbom)


if __name__ == "__main__":
    register()
