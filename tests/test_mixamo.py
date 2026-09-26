import json
import pytest
from scanatlas.catalog import Catalog
from scanatlas.mixamo import import_fbx, stage, local_state
from scanatlas.agent import describe

@pytest.fixture
def c(tmp_path):
 c=Catalog(tmp_path/'catalog.sqlite');c.set_setting('active_source','huggingface');yield c;c.close()

def fbx(tmp_path,name='Walk'):
 p=tmp_path/(name+'.fbx');p.write_bytes(b'; FBX 7.4.0 project file\nFBXHeaderExtension: {}\n'+name.encode());return p

def test_import_search_dedup_and_metadata(c,tmp_path):
 path=fbx(tmp_path);a=import_fbx(c,path,'Animations',tags='locomotion')
 assert c.query('walking',kind='Animations')[1]==1
 assert c.count()==1
 assert import_fbx(c,path,'Animations')['id']==a['id']
 assert c.count()==1
 d=describe(c,a);assert d['quixel_id'] is None and d['qualities']=={}
 assert d['availability']['file_exists'] and d['animation']['rig_validation']=='unverified'
 path.unlink();assert local_state(a)['state']=='missing'

def test_stage_hashes_link_and_no_overwrite(c,tmp_path):
 character=import_fbx(c,fbx(tmp_path,'Character'),'Characters')
 clip=import_fbx(c,fbx(tmp_path),'Animations',character['id'])
 target=tmp_path/'staged';ids=[character['id'],clip['id']]
 assert stage(c,ids,target)['dry_run'] and not target.exists()
 result=stage(c,ids,target,True)
 assert len(list(target.glob('*.fbx')))==2
 assert json.loads((target/'atlas-manifest.json').read_text())['items'][1]['character_id']==character['id']
 with pytest.raises(FileExistsError):stage(c,ids,target,True)
 Path=type(target);Path(clip['detail']['local_file']).write_bytes(b'changed')
 with pytest.raises(ValueError,match='changed'):stage(c,ids,tmp_path/'bad',True)
 assert not (tmp_path/'bad').exists()

def test_invalid_input(c,tmp_path):
 p=tmp_path/'fake.fbx';p.write_text('not an FBX')
 with pytest.raises(ValueError):import_fbx(c,p,'Characters')
 with pytest.raises(ValueError):import_fbx(c,fbx(tmp_path),'Animations','missing')

def test_personal_bundle_stages_dependencies_and_detects_changes(c,tmp_path):
 root=tmp_path/'package';root.mkdir();path=fbx(root,'Arms')
 (root/'Textures').mkdir();texture=root/'Textures'/'gloves.png';texture.write_bytes(b'example texture bytes')
 (root/'Arms.blend').write_bytes(b'editable source')
 a=import_fbx(c,path,'Characters',name='Military FPS Arms',my_asset=True,bundle=root)
 assert c.query(scope='my-assets')[1]==1
 assert c.query('military',scope='my-assets')[1]==1
 assert local_state(a)['file_count']==3
 target=tmp_path/'handoff';result=stage(c,[a['id']],target,True)
 assert (target/a['id']/'Textures'/'gloves.png').read_bytes()==texture.read_bytes()
 assert (target/result['items'][0]['filename']).is_file()
 texture.write_bytes(b'changed')
 with pytest.raises(ValueError,match='changed'):stage(c,[a['id']],tmp_path/'bad-bundle',True)
 assert not (tmp_path/'bad-bundle').exists()

def test_bundle_rejects_symlinks_and_external_entrypoint(c,tmp_path):
 root=tmp_path/'package';root.mkdir();path=fbx(root,'Arms')
 outside=fbx(tmp_path,'Other')
 with pytest.raises(ValueError,match='containing'):import_fbx(c,outside,'Characters',bundle=root)
 (root/'linked.fbx').symlink_to(outside)
 with pytest.raises(ValueError,match='symbolic'):import_fbx(c,path,'Characters',bundle=root)
