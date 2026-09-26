import json
from pathlib import Path
import pytest
from scanatlas.downloads import build_plan, QuixelClient

def scan():
 files=[]
 for r in [1024,2048,4096,8192]:
  files += [dict(name=f'a_{r//1024}K_Albedo.jpg',type='albedo',resolution=r,size=10,mime='image/jpeg',lod=None,physical='1x1'),dict(name=f'a_{r//1024}K_Albedo_LOD4.jpg',type='albedo',resolution=r,size=5,mime='image/jpeg',lod=4,physical='1x1')]
  for lod in range(4):files.append(dict(name=f'a_{r//1024}K_Normal_LOD{lod}.jpg',type='normal',resolution=r,size=10,mime='image/jpeg',lod=lod,physical='1x1'))
 for lod in range(4):files.append(dict(name=f'a_LOD{lod}.fbx',type='mesh',resolution=0,size=10,mime='application/x-fbx',lod=lod,mesh_type='lod',tris=1000//(lod+1)))
 files.append(dict(name='a_High.fbx',type='mesh',resolution=0,size=30,mime='application/x-fbx',lod=None,mesh_type='original'))
 return dict(id='a',name='Sample Rock',detail={'files':files})

@pytest.mark.parametrize('quality,res,lod',[('Low',1024,3),('Medium',2048,2),('High',4096,0),('Ultra',8192,None)])
def test_plan_selects_only_requested_quality(quality,res,lod):
 p=build_plan(scan(),quality);assert p['resolution']==res and len(p['files'])==3
 assert next(f for f in p['files'] if f['type']=='mesh')['lod']==lod
 assert next(f for f in p['files'] if f['type']=='albedo')['lod'] is None
 assert p['bytes']==sum(f['size'] for f in p['files'])

class Response:
 ok=True
 headers={'Content-Length':'10'}
 def __enter__(self):return self
 def __exit__(self,*a):pass
 def iter_content(self,n):yield b'0123456789'

def test_unowned_never_requests_download(monkeypatch,tmp_path):
 client=QuixelClient('test-token');monkeypatch.setattr(client,'acquired',lambda:set())
 monkeypatch.setattr(client,'api',lambda *a,**k:pytest.fail('Download authorization must not be requested'))
 with pytest.raises(PermissionError):client.download(scan(),build_plan(scan(),'Low'),tmp_path)
 assert not list(tmp_path.iterdir())

def client_with_manifest(monkeypatch,files):
 client=QuixelClient('test-token');monkeypatch.setattr(client,'acquired',lambda:{'a'})
 manifest={'components':[{'uri':'https://authorized.example/'+f['name']} for f in files]}
 monkeypatch.setattr(client,'api',lambda *a,**k:manifest)
 return client

def test_missing_signed_files_never_falls_back_to_public_urls(monkeypatch,tmp_path):
 a=scan();p=build_plan(a,'Low');client=client_with_manifest(monkeypatch,p['files'][:1])
 monkeypatch.setattr('scanatlas.downloads.requests.get',lambda *a,**k:pytest.fail('No payload fetch expected'))
 with pytest.raises(RuntimeError,match='Nothing downloaded'):client.download(a,p,tmp_path)
 assert not list(tmp_path.iterdir())

def test_only_selected_files_written_and_token_not_forwarded(monkeypatch,tmp_path):
 a=scan();p=build_plan(a,'Low');client=client_with_manifest(monkeypatch,a['detail']['files']);calls=[]
 def get(url,**kwargs):
  assert 'headers' not in kwargs;calls.append(url);return Response()
 monkeypatch.setattr('scanatlas.downloads.requests.get',get)
 folder=Path(client.download(a,p,tmp_path));manifest=json.loads((folder/'download.json').read_text())
 assert len(calls)==3;assert set(manifest['files'])=={f['name'] for f in p['files']}
 assert len(manifest['sha256'])==3;assert not list(folder.glob('*.part'))
 with pytest.raises(FileExistsError):client.download(a,p,tmp_path)

def test_cancel_removes_partial(monkeypatch,tmp_path):
 a=scan();p=build_plan(a,'Low');client=client_with_manifest(monkeypatch,p['files']);cancel=[False]
 class InterruptedResponse(Response):
  def iter_content(self,n):
   yield b'0123';cancel[0]=True;yield b'456789'
 monkeypatch.setattr('scanatlas.downloads.requests.get',lambda *a,**k:InterruptedResponse())
 with pytest.raises(InterruptedError):client.download(a,p,tmp_path,cancel=lambda:cancel[0])
 assert not list(tmp_path.rglob('*.part'));assert not list(tmp_path.rglob('download.json'))

def test_signed_download_preserves_subdirectories(monkeypatch,tmp_path):
 a=scan();p=build_plan(a,'High')
 for f in p['files']:f['name']='Var1/'+f['name']
 client=client_with_manifest(monkeypatch,p['files']);monkeypatch.setattr('scanatlas.downloads.requests.get',lambda *a,**k:Response())
 folder=Path(client.download(a,p,tmp_path))
 assert (folder/'Var1'/'a_LOD0.fbx').exists()

def test_path_traversal_rejected():
 a=scan();a['detail']['files'][0]['name']='../escape.jpg'
 with pytest.raises(ValueError,match='filename'):build_plan(a,'Low')


def test_medium_rejects_oversized_texture_fallback():
 a=scan();a['detail']['files']=[f for f in a['detail']['files'] if f['type']=='mesh' or f['resolution']>2048]
 with pytest.raises(ValueError,match='higher-resolution fallback is disabled'):
  build_plan(a,'Medium')

def test_agent_defaults_to_medium():
 from scanatlas.agent import parser
 assert parser().parse_args(['plan','a']).quality=='Medium'
 assert parser().parse_args(['download','a','--destination','/tmp']).quality=='Medium'
