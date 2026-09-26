"""Create a personal-use Mixamo arms derivative in Blender; preserve the source."""
import bpy,bmesh,json,sys,math,hashlib
from pathlib import Path
from mathutils import Vector,Quaternion,Matrix

args=sys.argv[sys.argv.index('--')+1:];source=Path(args[0]);out=Path(args[1]);out.mkdir(parents=True,exist_ok=True)
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.fbx(filepath=str(source),use_anim=False)
scene=bpy.context.scene;scene.unit_settings.system='METRIC';scene.unit_settings.scale_length=1
rig=next(o for o in scene.objects if o.type=='ARMATURE');rig.name='FPS_Arms_Rig'
rig.animation_data_clear()
for p in rig.pose.bones:p.matrix_basis.identity()
bpy.context.view_layer.update()
original_meshes=[o for o in scene.objects if o.type=='MESH']
for original in original_meshes:
 for side,sign in [('Left',1),('Right',-1)]:
  o=original.copy();o.data=original.data.copy();scene.collection.objects.link(o)
  o.name='FPS_'+side+'_Arm'
  bm=bmesh.new();bm.from_mesh(o.data)
  inverse=o.matrix_world.inverted()
  normal=o.matrix_world.to_3x3().transposed()@Vector((sign,0,0))
  bmesh.ops.delete(bm,geom=[v for v in bm.verts if (o.matrix_world@v.co).z<1.2],context='VERTS')
  cut=bmesh.ops.bisect_plane(bm,geom=list(bm.verts)+list(bm.edges)+list(bm.faces),dist=.00001,plane_co=inverse@Vector((sign*.245,0,1.4)),plane_no=normal,clear_inner=True,clear_outer=False)
  edges=[e for e in cut['geom_cut'] if isinstance(e,bmesh.types.BMEdge) and e.is_boundary]
  if edges:bmesh.ops.holes_fill(bm,edges=edges,sides=0)
  bm.to_mesh(o.data);bm.free();o.data.update()
  if not o.data.polygons:bpy.data.objects.remove(o,do_unlink=True)
 bpy.data.objects.remove(original,do_unlink=True)
meshes=[o for o in scene.objects if o.type=='MESH']
assert meshes and sum(len(o.data.polygons) for o in meshes)>100
used_materials={m for o in meshes for p in o.data.polygons if (m:=o.data.materials[p.material_index])}
texture_dir=out/'Textures';texture_dir.mkdir(exist_ok=True)
used_images=set()
for mat in used_materials:
 for node in mat.node_tree.nodes:
  if node.type=='TEX_IMAGE' and node.image:used_images.add(node.image)
for im in used_images:
 original=Path(im.filepath).stem
 if max(im.size)>2048:im.scale(round(im.size[0]*2048/max(im.size)),round(im.size[1]*2048/max(im.size)))
 im.file_format='PNG';im.filepath_raw=str(texture_dir/(original+'_2K.png'));im.save()
 packed=Path(im.filepath_raw).read_bytes();im.pack(data=packed,data_len=len(packed))
for mat in used_materials:
 for node in mat.node_tree.nodes:
  if node.type=='BSDF_PRINCIPLED':
   node.inputs['Roughness'].default_value=.68
   node.inputs['Metallic'].default_value=0
 # Imported specular/gloss textures remain available to the Unity material pass.
for o in meshes:
 for p in o.data.polygons:p.use_smooth=True
rig.show_in_front=True
# Keep original Mixamo hierarchy for Humanoid mapping and animation reuse.
for side in ('Left','Right'):
 for finger in ('Thumb','Index','Middle','Ring','Pinky'):
  assert all('mixamorig:'+side+'Hand'+finger+str(n) in rig.data.bones for n in (1,2,3))

# FBX in bind pose. No obsolete Walking animation is carried into the arms asset.
bpy.ops.object.select_all(action='DESELECT')
for o in [rig,*meshes]:o.select_set(True)
bpy.context.view_layer.objects.active=rig
bpy.ops.export_scene.fbx(filepath=str(out/'FPS_Tactical_Arms.fbx'),use_selection=True,object_types={'MESH','ARMATURE'},add_leaf_bones=False,bake_anim=False,path_mode='RELATIVE',embed_textures=False,axis_forward='-Z',axis_up='Y',use_custom_props=True)

# Authoring controls are Blender-only empties. The FBX stays a clean deform rig.
controls=bpy.data.collections.new('AUTHORING — IK controls');scene.collection.children.link(controls)
def empty(name,location,display='SPHERE',size=.045):
 ob=bpy.data.objects.new(name,None);controls.objects.link(ob);ob.empty_display_type=display;ob.empty_display_size=size;ob.location=location;return ob
for side,sign in [('Left',1),('Right',-1)]:
 wrist=empty('CTRL_'+side+'_Wrist',(sign*.18,-.41,1.28))
 pole=empty('CTRL_'+side+'_Elbow',(sign*.65,.0,1.0),'CUBE')
 forearm=rig.pose.bones['mixamorig:'+side+'ForeArm'];ik=forearm.constraints.new('IK');ik.name='FPS wrist IK';ik.target=wrist;ik.pole_target=pole;ik.chain_count=2;ik.use_stretch=False
 # Pole angles depend on the imported FBX bone basis; verification renders expose
 # the result instead of silently claiming camera-ready weapon alignment.
 best=None
 for sample in range(72):
  angle=-math.pi+2*math.pi*sample/72;ik.pole_angle=angle;bpy.context.view_layer.update()
  distance=((rig.matrix_world@forearm.head)-pole.location).length
  if best is None or distance<best[0]:best=(distance,angle)
 ik.pole_angle=best[1];bpy.context.view_layer.update()
 hand=rig.pose.bones['mixamorig:'+side+'Hand']
 desired=Matrix.Rotation(math.radians(65*sign),4,'Y')@Matrix.Rotation(math.radians(-90*sign),4,'Z')@rig.matrix_world@hand.bone.matrix_local
 wrist.rotation_euler=desired.to_euler()
 rotation=hand.constraints.new('COPY_ROTATION');rotation.name='FPS wrist orientation';rotation.target=wrist;rotation.owner_space='WORLD';rotation.target_space='WORLD'
 wrist['purpose']='Move and rotate to position the wrist and orient the hand for weapon grip.'
 pole['purpose']='Move to control elbow direction.'

# A finger articulation exercise, not a weapon-specific reload animation.
scene.render.fps=30;scene.frame_start=1;scene.frame_end=60
for frame,curl in [(1,0),(20,.85),(40,.85),(60,0)]:
 scene.frame_set(frame)
 for side in ('Left','Right'):
  for finger in ('Index','Middle','Ring','Pinky'):
   for segment in (1,2,3):
    p=rig.pose.bones['mixamorig:'+side+'Hand'+finger+str(segment)]
    p.rotation_mode='XYZ';p.rotation_euler=(curl,0,0);p.keyframe_insert(data_path='rotation_euler',frame=frame,group=p.name)
  for segment in (1,2,3):
   p=rig.pose.bones['mixamorig:'+side+'HandThumb'+str(segment)]
   p.rotation_mode='XYZ';p.rotation_euler=(curl*.45,0,0);p.keyframe_insert(data_path='rotation_euler',frame=frame,group=p.name)
rig.animation_data.action.name='Finger_Articulation_Test'
scene.frame_set(20);bpy.context.view_layer.update()
bpy.ops.object.select_all(action='DESELECT');rig.select_set(True);bpy.context.view_layer.objects.active=rig
bpy.ops.export_scene.fbx(filepath=str(out/'Finger_Articulation_Test.fbx'),use_selection=True,object_types={'ARMATURE'},add_leaf_bones=False,bake_anim=True,bake_anim_use_all_actions=False,bake_anim_use_nla_strips=False,bake_anim_simplify_factor=0,axis_forward='-Z',axis_up='Y')

def aim(obj,target):obj.rotation_euler=(Vector(target)-obj.location).to_track_quat('-Z','Y').to_euler()
def camera(name,loc,target,lens=50):
 data=bpy.data.cameras.new(name);o=bpy.data.objects.new(name,data);scene.collection.objects.link(o);o.location=loc;aim(o,target);o.data.lens=lens;return o
cam=camera('Preview_Camera',(1.0,-1.4,2.05),(0,-.19,1.3),58);scene.camera=cam
fps=camera('FPS_Camera',(0,.32,1.58),(0,-.40,1.24),40)
for name,loc,power,size in [('Key',(-2,-3,4),650,4),('Fill',(2,-1,2.5),400,3),('Rim',(0,2,3),700,2)]:
 data=bpy.data.lights.new(name,'AREA');data.energy=power;data.shape='DISK';data.size=size;o=bpy.data.objects.new(name,data);scene.collection.objects.link(o);o.location=loc;aim(o,(0,0,1.3))
scene.world=bpy.data.worlds.new('Studio');scene.world.use_nodes=True;scene.world.node_tree.nodes['Background'].inputs[0].default_value=(.08,.10,.13,1);scene.world.node_tree.nodes['Background'].inputs[1].default_value=.5
scene.render.engine='CYCLES';scene.cycles.samples=24;scene.cycles.use_denoising=True
scene.render.resolution_x=1200;scene.render.resolution_y=900;scene.render.resolution_percentage=100
scene.view_settings.view_transform='AgX';scene.render.image_settings.file_format='PNG'
scene.render.film_transparent=False
for im in list(bpy.data.images):
 if im not in used_images:bpy.data.images.remove(im)
for im in used_images:im.filepath='//Textures/'+Path(im.filepath).name
bpy.context.preferences.filepaths.save_version=0
bpy.ops.wm.save_as_mainfile(filepath=str(out/'FPS_Tactical_Arms.blend'))
scene.render.filepath=str(out/'preview.png');bpy.ops.render.render(write_still=True)
scene.camera=fps;scene.render.filepath=str(out/'fps-preview.png');bpy.ops.render.render(write_still=True)
scene.camera=cam

report={'source_file':source.name,'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'blender':bpy.app.version_string,'bones':len(rig.data.bones),'finger_joints':30,'meshes':[{'name':o.name,'vertices':len(o.data.vertices),'triangles':sum(len(p.vertices)-2 for p in o.data.polygons),'materials':[m.name for m in o.data.materials]} for o in meshes],'textures':[{'name':Path(i.filepath).name,'size':list(i.size)} for i in used_images],'unity_verified':False,'notes':['Full Mixamo skeleton retained; mesh contains only arms.','Blender scene includes IK wrist/elbow targets and finger articulation test.','FBX contains bind-pose mesh and deform rig, with no combat animations.','Weapon grip/reload/grenade animations must be authored for the chosen weapons.']}
(out/'build-report.json').write_text(json.dumps(report,indent=2))
print('ARMS_REPORT',json.dumps(report))
