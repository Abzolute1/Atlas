"""Explicit, entitlement-checked selective downloads. Never used by browsing."""
from __future__ import annotations
import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse,unquote
import requests

LEVELS={'Low':(1024,3),'Medium':(2048,2),'High':(4096,0),'Ultra':(None,0)}
MAPS={'albedo','diffuse','normal','roughness','ao','displacement','metalness','opacity','translucency','specular'}

def build_plan(asset,quality):
 if asset['detail'].get('source')=='mixamo':raise ValueError('Local Mixamo FBX: use atlas stage, not a texture-quality download plan')
 if quality not in LEVELS:raise ValueError('Unknown quality')
 if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',asset['id']):raise ValueError('Invalid asset ID in metadata')
 files=asset['detail'].get('files',[]);target,lod=LEVELS[quality]
 if asset['detail'].get('manifest_pending'):raise ValueError('Fetch file metadata with atlas plan ID before downloading; no asset transfer needed')
 if asset['detail'].get('source') in ('polyhaven','ambientcg') or asset['detail'].get('package_only'):
  eligible=[f for f in files if target is None or 0<f['resolution']<=target]
  if not eligible:raise ValueError('No files at or below selected quality')
  res=max(f['resolution'] for f in eligible);pool=[f for f in eligible if f['resolution']==res]
  if asset['detail'].get('source')=='polyhaven':
   chosen=[];groups={}
   for f in pool:groups.setdefault((f['type'],f['name'] if f['type']=='dependency' else ''),[]).append(f)
   for candidates in groups.values():chosen.append(min(candidates,key=lambda f:(f['mime']!='image/jpeg',f['name'].endswith('.exr'),f['size'])))
   if asset['kind']=='3D Assets' and not any(f['type']=='mesh' for f in chosen):raise ValueError('No supported FBX model at this quality; open source for other formats')
  else:chosen=[min(pool,key=lambda f:('JPG' not in f['name'],f['size']))]
  for f in chosen:
   if PurePosixPath(f['name']).is_absolute() or '..' in PurePosixPath(f['name']).parts or '\\' in f['name']:raise ValueError('Unsafe filename')
  return {'quality':quality,'files':chosen,'bytes':sum(f['size'] for f in chosen),'complete_size':all(f['size']>0 for f in chosen),'resolution':res,'archive_requires_extraction':any(f['name'].lower().endswith('.zip') for f in chosen)}

 textures=[f for f in files if f['type']!='mesh' and f['type'] in MAPS]
 if not textures:textures=[f for f in files if f['type']!='mesh']
 if not files:raise ValueError('This record has no downloadable file metadata. Open the official listing instead.')
 # Pick one resolution, format and LOD for each texture variant/map.
 groups={}
 for f in textures:
  variant=re.sub(r'_(?:\d+K|LOD\d+)', '', f['name'],flags=re.I)
  variant=re.sub(r'\.[^.]+$','',variant)
  groups.setdefault((f['type'],variant,f.get('physical','')),[]).append(f)
 chosen=[]
 for candidates in groups.values():
  available=sorted({f['resolution'] for f in candidates})
  eligible=available if target is None else [r for r in available if r<=target]
  if not eligible:raise ValueError(f'No texture at or below {target}px for {candidates[0]["type"]}; higher-resolution fallback is disabled.')
  resolution=max(eligible)
  pool=[f for f in candidates if f['resolution']==resolution]
  best=min(pool,key=lambda f:(0 if f['mime']=='image/jpeg' else 1,0 if f.get('lod')==lod else 1 if f.get('lod') is None else 2+abs(f['lod']-lod)))
  chosen.append(best)
 meshes=[f for f in files if f['type']=='mesh']
 groups={}
 for f in meshes:
  variant=re.sub(r'_(?:LOD\d+|High)(?=\.)','',f['name'],flags=re.I)
  variant=re.sub(r'\.[^.]+$','',variant)
  groups.setdefault(variant,[]).append(f)
 for candidates in groups.values():
  pool=[f for f in candidates if f.get('mesh_type')!='zbrush']
  if not pool:continue
  originals=[f for f in pool if f.get('mesh_type')=='original']
  if quality=='Ultra' and originals:pool=originals
  else:pool=[f for f in pool if f.get('lod') is not None] or pool
  chosen.append(min(pool,key=lambda f:(0 if f['mime']=='application/x-fbx' else 1,abs((f.get('lod') or 0)-lod))))
 # Don't duplicate identical filenames from overlapping metadata entries.
 chosen=list({f['name']:f for f in chosen}.values())
 if not chosen:raise ValueError('No usable files were described in this record.')
 for f in chosen:
  if not f['name'] or PurePosixPath(f['name']).is_absolute() or '..' in PurePosixPath(f['name']).parts or '\\' in f['name'] or f['name']=='.':raise ValueError('Unsafe filename in metadata')
 return {'quality':quality,'files':chosen,'bytes':sum(f['size'] for f in chosen),'complete_size':all(f['size']>0 for f in chosen),'resolution':max((f['resolution'] for f in chosen),default=0)}

class QuixelClient:
 def __init__(self,token):
  self.token=token.strip()
  if self.token.startswith('{'):
   try:self.token=json.loads(self.token)['token']
   except (ValueError,KeyError):raise ValueError('Paste a Quixel access token or its auth-cookie JSON.')
  self.token=self.token.removeprefix('Bearer ').strip()
  if not self.token or '\n' in self.token:raise ValueError('A valid Quixel access token is required.')
  self.session=requests.Session()
 def api(self,method,path,**kwargs):
  try:
   response=self.session.request(method,'https://quixel.com/v1/'+path,headers={'Authorization':'Bearer '+self.token,'Accept':'application/json'},timeout=(15,60),allow_redirects=False,**kwargs)
  except requests.RequestException:raise RuntimeError('Could not reach Quixel. Check your connection and try again.') from None
  if response.status_code in (401,403):raise RuntimeError('Quixel did not authorize this request. Reconnect your account or use the official listing.')
  if not response.ok or response.is_redirect:raise RuntimeError(f'Quixel returned HTTP {response.status_code}. No asset files were requested.')
  try:return response.json()
  except ValueError:raise RuntimeError('Quixel returned an unexpected response. The legacy service may have changed.') from None
 def acquired(self):
  data=self.api('GET','assets/acquired')
  if not isinstance(data,list):raise RuntimeError('Could not verify the owned-library response. Download stopped.')
  return {str(x['assetID']) for x in data if isinstance(x,dict) and x.get('assetID')}
 def download(self,asset,plan,destination,progress=lambda *a:None,cancel=lambda:False):
  if cancel():raise InterruptedError('Download cancelled')
  # Recheck server entitlements each time; a local badge is not proof of access.
  if asset['id'] not in self.acquired():raise PermissionError('This asset is not in this Quixel account’s acquired library. Check Fab if you acquired it there.')
  components=[]
  for f in plan['files']:
   if f['type'] in ('mesh','brush'):continue
   component={'type':f['type'],'mimeType':f['mime'],'resolution':f"{f['resolution']}x{f['resolution']}"}
   if f.get('physical'):component['physicalSize']=f['physical']
   if component not in components:components.append(component)
  payload={'asset':asset['id'],'config':{'highpoly':plan['quality']=='Ultra','lowerlod_meshes':True,'lowerlod_normals':True,'ztool':False,'brushes':any(f['type']=='brush' for f in plan['files']),'meshMimeType':'application/x-fbx','albedo_lods':True},'components':components}
  response=self.api('POST','downloads',json=payload)
  signed={}
  def walk(node):
   if isinstance(node,dict):
    uri=node.get('uri','')
    if isinstance(uri,str) and uri.startswith('https://'):
     signed[unquote(urlparse(uri).path)]=uri
    for v in node.values():walk(v)
   elif isinstance(node,list):
    for v in node:walk(v)
  walk(response)
  selected_urls={}
  for f in plan['files']:
   matches=[uri for path,uri in signed.items() if path.endswith('/'+f['name'])]
   if len(matches)==1:selected_urls[f['name']]=matches[0]
  if any(f['name'] not in selected_urls for f in plan['files']):
   raise RuntimeError('The server did not provide every file for this exact quality selection. Nothing downloaded. Try another quality or use the official listing.')
  return transfer_files(asset,plan,destination,selected_urls,progress,cancel)

def transfer_files(asset,plan,destination,selected_urls,progress=lambda *a:None,cancel=lambda:False):
  target=Path(destination).expanduser().resolve()
  if not target.is_dir():raise ValueError('Choose an existing download folder.')
  slug=re.sub(r'[^\w -]','',asset['name']).strip()[:70] or 'Asset'
  folder=target/f"{slug}_{asset['id']}_{plan['quality'].lower()}"
  folder.mkdir(exist_ok=True)
  if folder.is_symlink():raise ValueError('The target asset folder must not be a symbolic link.')
  existing=folder/'download.json'
  if existing.exists():raise FileExistsError('This asset and quality already exist in that folder.')
  done=0;checksums={};written=[]
  for f in plan['files']:
   if cancel():raise InterruptedError('Download cancelled; completed files kept. Partial file removed.')
   output=folder/f['name'];part=folder/(f['name']+'.part')
   for parent in output.parents:
    if parent==folder:break
    if parent.is_symlink():raise ValueError('Destination contains a symbolic link.')
   output.parent.mkdir(parents=True,exist_ok=True)
   if output.exists() or output.is_symlink() or part.exists() or part.is_symlink():raise FileExistsError(f"File already exists: {f['name']}. Choose a different folder.")
   digest=hashlib.sha256();md5=hashlib.md5();size=0
   try:
    # No account token is sent to the signed file URL.
    with requests.get(selected_urls[f['name']],stream=True,timeout=(15,45)) as r:
     if not r.ok:raise RuntimeError(f'File service returned HTTP {r.status_code}. Reconnect and try again.')
     expected=int(r.headers.get('Content-Length',0))
     with part.open('xb') as out:
      for chunk in r.iter_content(256*1024):
       if cancel():raise InterruptedError('Download cancelled; partial file removed.')
       if not chunk:continue
       out.write(chunk);digest.update(chunk);md5.update(chunk);size+=len(chunk);done+=len(chunk)
       progress(done,plan['bytes'],f['name'])
     if f.get('size') and size!=f['size']:raise RuntimeError('File size differs from source manifest.')
     if f.get('md5') and md5.hexdigest()!=f['md5']:raise RuntimeError('Source MD5 mismatch.')
     if f.get('sha256') and digest.hexdigest()!=f['sha256']:raise RuntimeError('Source SHA256 mismatch.')
     if expected and expected!=size:raise RuntimeError('Incomplete file received; partial file removed.')
    part.rename(output);written.append(f['name']);checksums[f['name']]=digest.hexdigest()
   except requests.RequestException:raise RuntimeError('File transfer interrupted; try again with a new destination folder.') from None
   finally:part.unlink(missing_ok=True)
  existing.write_text(json.dumps({'id':asset['id'],'name':asset['name'],'source':asset['detail'].get('source','Quixel'),'license':asset['detail'].get('license','Account license'),'quality':plan['quality'],'files':written,'sha256':checksums},indent=2))
  return str(folder)
