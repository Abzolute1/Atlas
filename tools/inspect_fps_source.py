import bpy,json,sys
from pathlib import Path
source=Path(sys.argv[sys.argv.index('--')+1])
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.fbx(filepath=str(source),use_anim=False)
data={'objects':[],'images':[]}
for o in bpy.context.scene.objects:
 d={'name':o.name,'type':o.type,'location':list(o.location),'scale':list(o.scale),'dimensions':list(o.dimensions)}
 if o.type=='MESH':
  d.update(vertices=len(o.data.vertices),polygons=len(o.data.polygons),materials=[m.name for m in o.data.materials],groups=[g.name for g in o.vertex_groups])
 if o.type=='ARMATURE':
  d['bones']=[{'name':b.name,'head':list(o.matrix_world@b.head_local),'tail':list(o.matrix_world@b.tail_local),'parent':b.parent.name if b.parent else None} for b in o.data.bones]
 data['objects'].append(d)
for im in bpy.data.images:data['images'].append({'name':im.name,'size':list(im.size),'filepath':im.filepath,'packed':bool(im.packed_file)})
(source.parent/'inspection.json').write_text(json.dumps(data,indent=2))
print('INSPECTION',source.parent/'inspection.json')
