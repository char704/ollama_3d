import bpy, math, os
from mathutils import Vector
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)

def material(name, rgba):
    m=bpy.data.materials.new(name);m.diffuse_color=rgba;m.use_nodes=True
    m.node_tree.nodes.get('Principled BSDF').inputs['Base Color'].default_value=rgba
    return m
gray=material('Unassigned clay',(0.32,0.36,0.32,1))
def ellipsoid(name,location,scale):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=48,ring_count=24,location=location)
    o=bpy.context.object;o.name=name;o.scale=scale
    bpy.ops.object.transform_apply(location=False,rotation=False,scale=True)
    for f in o.data.polygons:f.use_smooth=True
    o.data.materials.append(gray)
    return o

profile=[(-1.4,.03,.02),(-1.25,.36,.48),(-.95,.48,.64),(-.65,.49,.56),(-.3,.50,.45),(.1,.52,.31),(.65,.50,.19),(1.1,.37,.08),(1.4,.02,-.12)]
verts=[];faces=[];rings=80;segments=56
for j in range(rings+1):
    x=-1.4+2.8*j/rings;k=0
    while k<len(profile)-2 and x>profile[k+1][0]: k+=1
    a,b=profile[k:k+2];t=(x-a[0])/(b[0]-a[0]);w=a[1]+(b[1]-a[1])*t;top=a[2]+(b[2]-a[2])*t
    for i in range(segments):
        angle=2*math.pi*i/segments
        verts.append((x,w*math.sin(angle),(top-.22)/2+(top+.22)/2*math.cos(angle)))
for j in range(rings):
    for i in range(segments):
        a=j*segments+i;b=j*segments+(i+1)%segments
        faces.append((a,a+segments,b+segments,b))
mesh=bpy.data.meshes.new('Shoe upper');mesh.from_pydata(verts,[],faces);mesh.update()
upper=bpy.data.objects.new('Upper',mesh);bpy.context.collection.objects.link(upper);upper.data.materials.append(gray)
for p in mesh.polygons:p.use_smooth=True
ellipsoid('Sole',(0,0,-.29),(1.55,.56,.16))
laces=[]
for i in range(6):laces.append(ellipsoid('Cord',(-.53+i*.15,0,.525-i*.044),(.027,.28-i*.012,.025)))
bpy.ops.object.select_all(action='DESELECT')
for o in laces:o.select_set(True)
bpy.context.view_layer.objects.active=laces[0];bpy.ops.object.join();bpy.context.object.name='Laces'
hole=ellipsoid('Collar',(-.95,0,.625),(.23,.22,.035));hole.data.materials.clear();hole.data.materials.append(material('Dark collar',(.025,.035,.03,1)))
bpy.ops.mesh.primitive_plane_add(size=200,location=(0,0,-.46));ground=bpy.context.object;ground.name='Ground';ground.data.materials.append(material('Backdrop',(.78,.81,.75,1)))
bpy.ops.object.camera_add(location=(4,-6,3));camera=bpy.context.object;camera.name='Camera';camera.rotation_euler=(Vector((0,0,0))-camera.location).to_track_quat('-Z','Y').to_euler();camera.data.type='ORTHO';camera.data.ortho_scale=4.6;bpy.context.scene.camera=camera
for location,power,size in [((1,-3,5),650,5),((-3,1,3),400,4)]:
    bpy.ops.object.light_add(type='AREA',location=location);l=bpy.context.object;l.data.energy=power;l.data.shape='DISK';l.data.size=size;l.rotation_euler=(-l.location).to_track_quat('-Z','Y').to_euler()
scene=bpy.context.scene;scene.render.engine='CYCLES';scene.cycles.samples=24
scene.render.resolution_x=1000;scene.render.resolution_y=700;scene.render.resolution_percentage=100
scene.world.color=(.3,.3,.3);scene.view_settings.view_transform='AgX'
for area in bpy.context.screen.areas:
    if area.type=='VIEW_3D':
        area.spaces.active.region_3d.view_perspective='CAMERA'
        area.spaces.active.shading.color_type='MATERIAL'
bpy.ops.object.select_all(action='DESELECT');upper.select_set(True);bpy.context.view_layer.objects.active=upper
bpy.ops.wm.save_as_mainfile(filepath=os.path.join(ROOT,'inputs','Sneaker_Unassigned.blend'))
scene.render.filepath=os.path.join(ROOT,'inputs','before.png');bpy.ops.render.render(write_still=True)
