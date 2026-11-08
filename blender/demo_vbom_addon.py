bl_info = {'name': 'BOM Demo Importer', 'author': 'Local demo', 'version': (1, 0, 0), 'blender': (4, 0, 0), 'category': 'Import-Export'}
import bpy
import json
import xml.etree.ElementTree as ET
from bpy.props import StringProperty
from bpy_extras.io_utils import ImportHelper

def linear(v):
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4

class DEMO_OT_import_vbom(bpy.types.Operator, ImportHelper):
    bl_idname = 'demo.import_vbom'
    bl_label = 'Import Demo VBOM and Apply Materials'
    bl_options = {'REGISTER', 'UNDO'}
    filename_ext = '.vbom'
    filter_glob: StringProperty(default='*.vbom', options={'HIDDEN'})

    def execute(self, context):
        try:
            root = ET.parse(self.filepath).getroot()
            if root.tag != 'vbom' or root.get('format') != 'demo-v1':
                raise ValueError('Not a demo-v1 VBOM')
            items = list(root.findall('item'))
            names = [i.get('object') for i in items]
            if len(names) != 3 or set(names) != {'Upper', 'Sole', 'Laces'}:
                raise ValueError('VBOM must map Upper, Sole and Laces exactly once')
            for name in names:
                if not bpy.data.objects.get(name) or bpy.data.objects[name].type != 'MESH':
                    raise ValueError('Missing mesh: '+str(name))
            applied = []
            for item in items:
                name, color = item.get('object'), item.get('color')
                rgb = tuple(linear(int(color[i:i+2], 16)/255) for i in (1, 3, 5))
                roughness, metallic = float(item.get('roughness')), float(item.get('metallic'))
                if not 0 <= roughness <= 1 or not 0 <= metallic <= 1:
                    raise ValueError('Invalid material parameters')
                mat = bpy.data.materials.new(item.get('material'))
                mat.use_nodes = True
                bsdf = mat.node_tree.nodes.get('Principled BSDF')
                bsdf.inputs['Base Color'].default_value = (*rgb, 1)
                bsdf.inputs['Roughness'].default_value = roughness
                bsdf.inputs['Metallic'].default_value = metallic
                mat.diffuse_color = (*rgb, 1)
                obj = bpy.data.objects[name]
                obj.data.materials.clear()
                obj.data.materials.append(mat)
                obj['bom_color_hex'] = color
                applied.append({'object':name,'material':mat.name,'color':color,'roughness':roughness,'metallic':metallic})
            context.scene['demo_vbom_report'] = json.dumps({'operator':self.bl_idname,'source':self.filepath,'applied':applied})
            self.report({'INFO'}, 'Applied VBOM to 3 objects')
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}

def menu_import(self, context):
    self.layout.operator(DEMO_OT_import_vbom.bl_idname, text='Demo VBOM (.vbom)')

def register():
    bpy.utils.register_class(DEMO_OT_import_vbom)
    bpy.types.TOPBAR_MT_file_import.append(menu_import)

def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(menu_import)
    bpy.utils.unregister_class(DEMO_OT_import_vbom)

if __name__ == '__main__':
    register()
