from scanatlas.metadata import normalize
from scanatlas.downloads import build_plan

def test_flat_maps_and_nested_components_both_normalize():
 fmt={'mimeType':'image/jpeg','contentLength':1200,'uri':'/quixel-megascans-assets/rock/rock_4K_Albedo.jpg'}
 flat={'id':'rock','name':'Rock','categories':['surface','rock'],'maps':[dict(fmt,type='albedo',resolution='4096x4096',physicalSize='1x1')]}
 nested={'id':'rock','name':'Rock','categories':['surface','rock'],'components':[{'type':'albedo','uris':[{'physicalSize':'1x1','resolutions':[{'resolution':'4096x4096','formats':[fmt]}]}]}]}
 a=normalize('rock',flat);b=normalize('rock',nested)
 assert a['detail']['files']==b['detail']['files']
 assert a['maxres']==4096;assert a['kind']=='Surfaces'
 assert build_plan(a,'Ultra')['bytes']==1200

def test_unsafe_asset_id_cannot_be_a_download_path():
 import pytest
 with pytest.raises(ValueError,match='asset ID'):build_plan({'id':'../../bad','detail':{}},'Low')

def test_flat_models_preserve_variant_paths():
 d={'id':'a','name':'Grass','categories':['3dplant','grass'],'models':[]}
 for v in [1,2]:
  for lod in [0,2,3]:
   d['models'].append({'mimeType':'application/x-fbx','uri':f'/quixel-megascans-assets/a/Var{v}/a_LOD{lod}.fbx','lod':lod,'type':'lod','tris':100,'contentLength':100})
 a=normalize('a',d);p=build_plan(a,'Low')
 assert {f['name'] for f in p['files']}=={'Var1/a_LOD3.fbx','Var2/a_LOD3.fbx'}
