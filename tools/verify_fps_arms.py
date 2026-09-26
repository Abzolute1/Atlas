import bpy,json,sys,math
from pathlib import Path
out=Path(sys.argv[sys.argv.index('--')+1])
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.fbx(filepath=str(out/'FPS_Tactical_Arms.fbx'),use_anim=False)
rig=next(o for o in bpy.context.scene.objects if o.type=='ARMATURE')
meshes=[o for o in bpy.context.scene.objects if o.type=='MESH']
assert len(meshes)==2
for o in meshes:
 assert any(m.type=='ARMATURE' and m.object==rig for m in o.modifiers)
 for v in o.data.vertices:
  assert v.groups and abs(sum(g.weight for g in v.groups)-1)<.015,(o.name,v.index)
def vertices():
 bpy.context.view_layer.update();dg=bpy.context.evaluated_depsgraph_get();result=[]
 for o in meshes:
  evaluated=o.evaluated_get(dg);m=evaluated.to_mesh();result.extend(evaluated.matrix_world@v.co for v in m.vertices);evaluated.to_mesh_clear()
 return result
rest=vertices();deformations=[]
for side in ('Left','Right'):
 for finger in ('Thumb','Index','Middle','Ring','Pinky'):
  p=rig.pose.bones['mixamorig:'+side+'Hand'+finger+'1'];p.rotation_mode='XYZ';p.rotation_euler.x=.6
  posed=vertices();delta=max((a-b).length for a,b in zip(rest,posed));assert delta>.001,(side,finger,delta)
  deformations.append({'finger':side+finger,'max_vertex_movement_m':delta});p.rotation_euler.x=0
report={'fbx_roundtrip':'passed','arm_meshes':len(meshes),'bones':len(rig.data.bones),'normalized_weights':'passed','finger_deformations':deformations,'textures':[],'unity_verified':False}
for im in bpy.data.images:
 if im.type=='IMAGE':
  first_pixel=im.pixels[0]
  assert im.has_data and max(im.size)<=2048,(im.name,list(im.size),im.filepath)
  report['textures'].append({'name':im.name,'size':list(im.size)})
(out/'blender-validation.json').write_text(json.dumps(report,indent=2));print('VALIDATED',json.dumps(report))
