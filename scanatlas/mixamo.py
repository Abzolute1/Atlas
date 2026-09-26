"""Local Mixamo handoff. Never scrapes an account or infers rig compatibility."""
import hashlib
import json
import shutil
import tempfile
from pathlib import Path

URL = 'https://www.mixamo.com/'
GUIDE = {
 'source': 'mixamo', 'url': URL, 'authentication': 'atlas mixamo connect opens Adobe sign-in in the background service. Close the window after login; catalog UI is not required. Session stays in memory until service stops.',
 'remote_catalog_indexed': False, 'agent_browser_commands': True, 'automatic_download': 'Only explicit mixamo download --execute after user sign-in',
 'steps': [
  'Choose a character in Mixamo, or upload your humanoid character and complete Auto-Rigger.',
  'Download the character in FBX for Unity format, With Skin, preferably a T-pose.',
  'Download selected animations for that same character, Without Skin. Choose In Place for navigation-driven locomotion when available.',
  'Import each FBX into Atlas as Characters or Animations; link animations to the imported character ID.',
  'Stage selected IDs into a folder. Import the character into Unity as Humanoid and validate its Avatar.',
  'For clips exported on the same skeleton, try Copy From Other Avatar with that character Avatar. Validate mapping and playback; different skeletons need their own valid Avatar and retargeting.',
  'Check foot sliding, scale, root motion, looping and transitions before attaching the Animator to NPC navigation.'
 ],
 'quality': 'Original FBX; texture resolution and mesh LOD are not inferred. Medium/2K conversion is not performed.',
 'license_url': 'https://helpx.adobe.com/creative-cloud/faq/mixamo-faq.html',
 'license': 'Adobe Mixamo terms; royalty-free project use. Not CC0; this catalog does not redistribute source files.'
}

def digest(path):
 with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def import_fbx(c, path, kind, character=None, preview=None, tags='', name=None, my_asset=False, bundle=None):
 path=Path(path).expanduser().resolve()
 if kind not in ('Characters','Animations'):raise ValueError('Choose Characters or Animations')
 if not path.is_file() or path.suffix.lower()!='.fbx':raise ValueError('Select an existing FBX file')
 with path.open('rb') as stream:header=stream.read(4096)
 if not (header.startswith(b'Kaydara FBX Binary') or b'FBXHeaderExtension:' in header):raise ValueError('File does not have a recognized FBX header')
 if character:
  linked=c.get(character)
  if not linked or linked['kind']!='Characters':raise ValueError('Character ID must refer to an imported character')
 if preview:
  preview=Path(preview).expanduser().resolve()
  if not preview.is_file() or preview.suffix.lower() not in ('.png','.jpg','.jpeg'):raise ValueError('Preview must be an existing PNG or JPEG')
 checksum=digest(path);ident='mixamo_'+checksum[:24]
 if not name:
  name=path.stem
  if kind=='Animations' and '@' in name:
   name=name.split('@',1)[1]
   if character:name+=' on '+linked['name']
 existing=c.get(ident)
 if existing and existing['kind']!=kind:raise ValueError('This FBX is already indexed with a different role')
 detail={'source':'mixamo','source_url':URL,'license':GUIDE['license'],'tags':['mixamo',kind.lower(),*tags.split()],
  'meta':{'Rig validation':'Pending Unity inspection','File size':str(path.stat().st_size)+' bytes','Character ID':character or 'Not linked'},
  'files':[], 'local_file':str(path),'size_bytes':path.stat().st_size,'sha256':checksum,'character_id':character,
  'rig_validation':'unverified','duration_seconds':None,'frame_rate':None,'root_motion':None,
  'preview_status':'user_supplied' if preview else 'missing','resolutions':[]}
 detail['my_asset']=my_asset
 if bundle:
  root=Path(bundle).expanduser().resolve()
  if not root.is_dir() or not path.is_relative_to(root):raise ValueError('Bundle must be a directory containing the FBX')
  entries=[]
  for file in sorted(root.rglob('*')):
   if file.is_symlink():raise ValueError('Bundle must not contain symbolic links')
   if file.is_file():entries.append({'name':file.relative_to(root).as_posix(),'size_bytes':file.stat().st_size,'sha256':digest(file)})
  detail.update(bundle_root=str(root),bundle_files=entries,bundle_size_bytes=sum(f['size_bytes'] for f in entries),bundle_entrypoint=path.relative_to(root).as_posix())
 c.upsert(dict(id=ident,name=name,kind=kind,subtype='Personal derivative' if my_asset else 'Mixamo',categories=kind+' Mixamo'+(' My assets' if my_asset else ''),tags=' '.join(detail['tags'])+' '+name,maxres=0,preview=str(preview) if preview else '',tiny='',detail=detail,local_path=str(path.parent)))
 c.c.commit()
 if not preview:
  from .local_previews import launch
  launch(c)
 return c.get(ident)

def local_state(a):
 d=a['detail']
 if d.get('catalog_only'):
  return {'state':'remote_catalog','file_exists':False,'size_bytes':None,'file_count':0,'quality':'Original FBX','next_action':'mixamo-export' if d.get('export_supported') else 'browse_pack','requires_sign_in':True,'export_supported':d.get('export_supported',False)}
 p=Path(d['local_file']);exists=p.is_file()
 files=d.get('bundle_files',[])
 missing=[f['name'] for f in files if not (Path(d['bundle_root'])/f['name']).is_file()]
 return {'state':'local' if exists and not missing else 'missing','file_exists':exists,'missing_files':missing,'size_bytes':d.get('bundle_size_bytes',d['size_bytes']),'fbx_size_bytes':d['size_bytes'],'file_count':len(files) or 1,'sha256':d['sha256'],
  'rig_validation':d['rig_validation'],'character_id':d.get('character_id'),
  'next_action':'stage' if exists else 'import-mixamo','quality':'Original','integrity_checked':False}

def stage(c, ids, destination, execute=False):
 assets=[]
 for ident in dict.fromkeys(ids):
  a=c.get(ident)
  if not a or a['detail'].get('source')!='mixamo':raise ValueError('stage currently supports imported Mixamo IDs only: '+ident)
  if a['detail'].get('catalog_only'):raise ValueError('This is a catalog entry. Use atlas mixamo-export ID to download it first.')
  if not Path(a['detail']['local_file']).is_file():raise ValueError('Local file missing: '+ident)
  assets.append(a)
 if not assets:raise ValueError('Select at least one asset')
 target=Path(destination).expanduser().resolve()
 if target.exists():raise FileExistsError('Use a new destination folder; existing files are never overwritten')
 result={'dry_run':not execute,'destination':str(target),'size_bytes':sum(a['detail'].get('bundle_size_bytes',a['detail']['size_bytes']) for a in assets),'items':[{'id':a['id'],'name':a['name'],'kind':a['kind'],'filename':a['id']+'/'+a['detail']['bundle_entrypoint'] if a['detail'].get('bundle_files') else a['id']+'.fbx','sha256':a['detail']['sha256'],'source':'mixamo','my_asset':a['detail'].get('my_asset',False),'files':a['detail'].get('bundle_files',[]),'character_id':a['detail'].get('character_id'),'rig_validation':a['detail'].get('rig_validation','unverified')} for a in assets],'unity_workflow':GUIDE['steps'][-3:],'quality':'Original','asset_files_downloaded':False}
 if not execute:return result
 target.parent.mkdir(parents=True,exist_ok=True)
 temp=Path(tempfile.mkdtemp(prefix='.atlas-stage-',dir=target.parent))
 try:
  for a,item in zip(assets,result['items']):
   if a['detail'].get('bundle_files'):
    root=Path(a['detail']['bundle_root']).resolve()
    for f in a['detail']['bundle_files']:
     relative=Path(f['name']);source=root/relative
     if relative.is_absolute() or '..' in relative.parts or source.is_symlink() or not source.resolve().is_relative_to(root):raise ValueError('Unsafe bundle path')
     output=temp/a['id']/relative;output.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,output)
     if digest(output)!=f['sha256']:raise ValueError('Source changed since indexing: '+f['name'])
    continue
   output=temp/item['filename'];shutil.copyfile(a['detail']['local_file'],output)
   if digest(output)!=item['sha256']:raise ValueError('Source changed since indexing: '+a['id'])
  (temp/'atlas-manifest.json').write_text(json.dumps(result,indent=2))
  temp.rename(target)
 except BaseException:
  shutil.rmtree(temp,ignore_errors=True);raise
 return result
