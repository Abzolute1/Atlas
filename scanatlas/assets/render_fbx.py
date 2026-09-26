"""Blender-only renderer. Reads local FBXs; writes previews, never source assets."""
import bpy,json,sys,math
from pathlib import Path
from mathutils import Vector
job=json.loads(Path(sys.argv[sys.argv.index('--')+1]).read_text())
bpy.ops.wm.read_factory_settings(use_empty=True)
scene=bpy.context.scene
bpy.ops.import_scene.fbx(filepath=job.get('character_file') or job['local_file'],use_anim=True)
meshes=[o for o in scene.objects if o.type=='MESH']
rigs=[o for o in scene.objects if o.type=='ARMATURE']
if not meshes or len(rigs)!=1:raise ValueError('A skinned character with one armature is required')
rig=rigs[0]
if job.get('character_file'):
 before=set(scene.objects)
 bpy.ops.import_scene.fbx(filepath=job['local_file'],use_anim=True)
 imported=set(scene.objects)-before
 clip=next((o for o in imported if o.type=='ARMATURE'),None)
 if not clip or not clip.animation_data or not clip.animation_data.action:raise ValueError('FBX contains no animation')
 # Match bone lengths and hierarchy; FBX bind rotations can differ per export.
 if set(rig.data.bones.keys())!=set(clip.data.bones.keys()):raise ValueError('Linked character skeleton does not match the clip')
 for bone in rig.data.bones:
  other=clip.data.bones[bone.name]
  if (bone.parent.name if bone.parent else None)!=(other.parent.name if other.parent else None):raise ValueError('Bone hierarchy mismatch')
  if abs(bone.length-other.length)>max(.002,bone.length*.001):raise ValueError('Character proportions do not match the clip')
 rig.animation_data_clear()
 for bone in rig.pose.bones:
  con=bone.constraints.new('COPY_TRANSFORMS');con.target=clip;con.subtarget=bone.name;con.owner_space='WORLD';con.target_space='WORLD'
 for o in imported:
  if o.type=='MESH':bpy.data.objects.remove(o,do_unlink=True)
 action=clip.animation_data.action
else:action=rig.animation_data.action if rig.animation_data else None
start,end=map(float,action.frame_range) if action else (1.,1.)
fps=scene.render.fps/scene.render.fps_base
frames=[round(start+(end-start)*t) for t in (.15,.5,.85)] if action else [1]
# Preview memory is capped; original textures and FBXs are unchanged.
for im in bpy.data.images:
 if max(im.size,default=0)>1024:
  ratio=1024/max(im.size);im.scale(max(1,round(im.size[0]*ratio)),max(1,round(im.size[1]*ratio)))
for m in bpy.data.materials:
 if m.use_nodes:
  for n in m.node_tree.nodes:
   if n.type=='BSDF_PRINCIPLED':
    n.inputs['Metallic'].default_value=0
    n.inputs['Roughness'].default_value=.65
def aim(o,p):o.rotation_euler=(Vector(p)-o.location).to_track_quat('-Z','Y').to_euler()
data=bpy.data.cameras.new('Preview');cam=bpy.data.objects.new('Preview',data);scene.collection.objects.link(cam)
cam.data.type='ORTHO';scene.camera=cam
view=Vector((.6,-1.5,.25)).normalized();cam.location=view*4;aim(cam,(0,0,0))
rotation=cam.rotation_euler.to_matrix();right=rotation@Vector((1,0,0));up=rotation@Vector((0,1,0))
centers={};scales=[]
for frame in frames:
 scene.frame_set(frame);bpy.context.view_layer.update();deps=bpy.context.evaluated_depsgraph_get();points=[]
 for o in meshes:
  e=o.evaluated_get(deps);points += [e.matrix_world@v.co for v in e.data.vertices]
 lo=Vector(tuple(min(p[i] for p in points) for i in range(3)));hi=Vector(tuple(max(p[i] for p in points) for i in range(3)))
 centers[frame]=(lo+hi)/2
 width=max(p.dot(right) for p in points)-min(p.dot(right) for p in points)
 height=max(p.dot(up) for p in points)-min(p.dot(up) for p in points)
 scales.append(max(width,height)*1.18)
cam.data.ortho_scale=max(scales);center=centers[frames[len(frames)//2]]
for name,offset,energy,size in [('Key',(-2,-3,4),650,4),('Fill',(3,-2,2),500,3),('Rim',(0,3,3),700,3)]:
 d=bpy.data.lights.new(name,'AREA');d.energy=energy;d.size=size;o=bpy.data.objects.new(name,d);scene.collection.objects.link(o);o.location=center+Vector(offset);aim(o,center)
scene.world=bpy.data.worlds.new('Studio');scene.world.use_nodes=True;scene.world.node_tree.nodes['Background'].inputs[0].default_value=(.10,.11,.13,1);scene.world.node_tree.nodes['Background'].inputs[1].default_value=.6
scene.render.engine='CYCLES';scene.cycles.samples=12;scene.cycles.use_denoising=True
scene.render.resolution_x=512;scene.render.resolution_y=512;scene.render.resolution_percentage=100
scene.render.image_settings.file_format='PNG';scene.view_settings.view_transform='AgX'
output=Path(job['output']);output.mkdir(parents=True,exist_ok=True)
paths=[]
for i,frame in enumerate(frames):
 scene.frame_set(frame);cam.location=centers[frame]+view*4;aim(cam,centers[frame]);scene.render.filepath=str(output/('pose-'+str(i)+'.png'));bpy.ops.render.render(write_still=True);paths.append(scene.render.filepath)
report={'paths':paths,'frames':frames,'frame_range':[start,end],'frame_rate':fps,'duration_seconds':(end-start)/fps if action else None,'bones':len(rig.data.bones),'preview_status':'local_render','character_id':job.get('character_id')}
(output/'report.json').write_text(json.dumps(report))
print('ATLAS_PREVIEW',json.dumps(report))
