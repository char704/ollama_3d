import bpy, os, sys, json
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0,os.path.join(ROOT,'blender'))
import demo_vbom_addon
args=sys.argv[sys.argv.index('--')+1:]
vbom,output,report=args
demo_vbom_addon.register()
status=bpy.ops.demo.import_vbom(filepath=vbom)
if status != {'FINISHED'}: raise RuntimeError('Add-on did not finish: '+str(status))
result=json.loads(bpy.context.scene['demo_vbom_report'])
bpy.ops.wm.save_as_mainfile(filepath=output)
# Reopen the saved file and verify material/color data persisted.
bpy.ops.wm.open_mainfile(filepath=output)
for item in result['applied']:
    obj=bpy.data.objects[item['object']]
    if obj.get('bom_color_hex') != item['color'] or obj.active_material.name != item['material']:
        raise RuntimeError('Saved model verification failed')
    node=obj.active_material.node_tree.nodes.get('Principled BSDF')
    if node is None: raise RuntimeError('Missing material shader')
    expected_rgb=[int(item['color'][i:i+2],16)/255 for i in (1,3,5)]
    expected_linear=[c/12.92 if c<=.04045 else ((c+.055)/1.055)**2.4 for c in expected_rgb]
    if any(abs(a-b)>1e-5 for a,b in zip(node.inputs['Base Color'].default_value[:3],expected_linear)):
        raise RuntimeError('Saved shader color differs from BOM')
    for name,key in [('Roughness','roughness'),('Metallic','metallic')]:
        if abs(node.inputs[name].default_value-item[key])>1e-5:
            raise RuntimeError('Saved shader '+name+' differs from BOM')
result.update(ok=True,verified_after_reopen=True,output=output)
with open(report,'w',encoding='utf8') as f:json.dump(result,f,ensure_ascii=False,indent=2)
bpy.context.scene.render.filepath=os.path.join(os.path.dirname(output),'after.png')
bpy.ops.render.render(write_still=True)
