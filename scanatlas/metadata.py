from __future__ import annotations
import json
import re
import tarfile
from pathlib import Path
import ijson
import zstandard
from .catalog import Catalog

SOURCE='https://github.com/WAUthethird/quixel-megascans-scripts'
TYPE_MAP={'3d':'3D Assets','3D asset':'3D Assets','3dplant':'3D Plants','3D plant':'3D Plants','surface':'Surfaces','decal':'Decals','atlas':'Atlases','brush':'Brushes','imperfection':'Imperfections','displacement':'Displacements'}

def number(value):
 try:return int(str(value).split('x')[0])
 except (TypeError,ValueError):return 0

def preview_url(uri):
 if uri.startswith('/quixel-megascans-assets/'):
  return 'https://ddinktqu5prvc.cloudfront.net/'+uri.removeprefix('/quixel-megascans-assets/')
 return uri if uri.startswith(('https://','data:')) else ''

def asset_path(uri,asset_id):
 prefix='/quixel-megascans-assets/'+str(asset_id)+'/'
 return uri.removeprefix(prefix) if uri.startswith(prefix) else Path(uri).name

def normalize(asset_id,wrapper,local_path=''):
 d=wrapper.get('full_metadata',wrapper)
 semantic=d.get('semanticTags') or {}
 cats=d.get('categories') or []
 if not isinstance(cats,list):cats=[]
 cats=[str(c) for c in cats]
 kind=TYPE_MAP.get(semantic.get('asset_type'),TYPE_MAP.get(cats[0] if cats else '', 'Other'))
 subtype=(cats[-1] if len(cats)>1 else 'Uncategorized').replace('_',' ').replace('-',' ').title()
 tags=list(d.get('tags') or [])
 for key in ['contains','theme','descriptive','state','color']:
  val=semantic.get(key,[])
  tags += val if isinstance(val,list) else [str(val)]
 tags=list(dict.fromkeys(str(t) for t in tags))
 images=(d.get('previews') or {}).get('images',[])
 candidates=[i for i in images if i.get('uri','').startswith(('https://','/'))]
 candidates.sort(key=lambda i: (0 if i.get('uri','').lower().endswith('.jpg') else 1,abs(number(i.get('resolution'))-655)))
 preview=preview_url(candidates[0]['uri']) if candidates else ''
 tiny=next((i['uri'] for i in images if i.get('uri','').startswith('data:image/')),'')
 gallery=[preview_url(i.get('uri','')) for i in candidates if 'preview' in i.get('tags',[])][:5]
 components=d.get('components') or d.get('maps') or []
 files=[]
 # Legacy catalogs contain both nested components and newer flat maps.
 for entry in d.get('maps') or []:
  if not isinstance(entry,dict) or not entry.get('uri'):continue
  uri=entry['uri'];lod=re.search(r'_LOD(\d+)',uri,re.I)
  files.append({'name':asset_path(uri,asset_id),'type':entry.get('type','texture'),'resolution':number(entry.get('resolution')),'size':number(entry.get('contentLength')),'mime':entry.get('mimeType','image/jpeg'),'lod':int(lod[1]) if lod else None,'physical':entry.get('physicalSize','')})
 for entry in d.get('brushes') or []:
  if not isinstance(entry,dict) or not entry.get('uri'):continue
  uri=entry['uri']
  files.append({'name':asset_path(uri,asset_id),'type':'brush','resolution':number(entry.get('resolution')),'size':number(entry.get('contentLength')),'mime':entry.get('mimeType','application/octet-stream'),'lod':None,'physical':''})
 for component in components:
  if not isinstance(component,dict):continue
  typ=component.get('type','')
  for physical in component.get('uris',[]):
   for res in physical.get('resolutions',[]):
    for fmt in res.get('formats',[]):
     mime=fmt.get('mimeType','')
     if mime not in ('image/jpeg','image/png','image/x-exr'):continue
     uri=fmt.get('uri','')
     lod=re.search(r'_LOD(\d+)',uri,re.I)
     files.append({'name':asset_path(uri,asset_id),'type':typ,'resolution':number(res.get('resolution')),'size':number(fmt.get('contentLength')),'mime':mime,'lod':int(lod[1]) if lod else None,'physical':physical.get('physicalSize','')})
 for entry in d.get('models') or []:
  if entry.get('mimeType') not in ('application/x-fbx','application/x-obj') or not entry.get('uri'):continue
  lod=entry.get('lod');uri=entry['uri']
  files.append({'name':asset_path(uri,asset_id),'type':'mesh','resolution':0,'size':number(entry.get('contentLength')),'mime':entry['mimeType'],'lod':lod if isinstance(lod,int) and lod>=0 else None,'mesh_type':entry.get('type'),'tris':entry.get('tris')})
 meshes=d.get('meshes') or []
 for mesh in meshes:
  for fmt in mesh.get('uris',[]):
   if fmt.get('mimeType') not in ('application/x-fbx','application/x-obj'):continue
   uri=fmt.get('uri','');lod=re.search(r'_LOD(\d+)',uri,re.I)
   files.append({'name':asset_path(uri,asset_id),'type':'mesh','resolution':0,'size':number(fmt.get('contentLength')),'mime':fmt.get('mimeType'),'lod':int(lod[1]) if lod else None,'mesh_type':mesh.get('type'),'tris':mesh.get('tris')})
 resolutions=sorted({f['resolution'] for f in files if f['resolution']})
 meta={m.get('name',m.get('key','')):m.get('value') for m in d.get('meta',[]) if isinstance(m,dict)}
 return dict(id=str(d.get('id') or asset_id),name=str(d.get('name') or semantic.get('name') or wrapper.get('name') or asset_id),kind=kind,subtype=subtype,categories=' / '.join(cats),tags=' '.join(tags),maxres=max(resolutions,default=0),preview=preview,tiny=tiny,local_path=local_path,detail={'tags':tags,'categories':cats,'meta':meta,'resolutions':resolutions,'files':files,'gallery':gallery,'source':SOURCE if 'full_metadata' in wrapper else 'Local library','semantic':semantic})

def import_archive(path,dbpath=None,progress=lambda *a:None,cancel=lambda:False):
 count=0;catalog=Catalog(dbpath)
 try:
  with open(path,'rb') as f,zstandard.ZstdDecompressor().stream_reader(f) as reader,tarfile.open(fileobj=reader,mode='r|') as tar:
   for member in tar:
    if not member.isfile() or not member.name.endswith('.json'):continue
    with catalog.c:
     for asset_id,wrapper in ijson.kvitems(tar.extractfile(member),'asset_metadata',use_float=True):
      if cancel():raise InterruptedError('Import cancelled; previous catalog kept.')
      catalog.upsert(normalize(asset_id,wrapper));count+=1
      if count%250==0:progress(count,18870)
    break
  catalog.set_setting('catalog_source',SOURCE)
  catalog.set_setting('catalog_snapshot','Legacy community snapshot · September 2025')
  return count
 finally:catalog.close()

def import_local(folder,dbpath=None,progress=lambda *a:None,cancel=lambda:False):
 catalog=Catalog(dbpath);count=0;skipped=0
 try:
  with catalog.c:
   for path in Path(folder).rglob('*.json'):
    if cancel():raise InterruptedError('Import cancelled; previous catalog kept.')
    if path.stat().st_size>15_000_000:continue
    try:
     d=json.loads(path.read_text(encoding='utf-8-sig'))
     if not isinstance(d,dict):continue
     if not d.get('id') or not ('categories' in d or 'semanticTags' in d):continue
     item=normalize(d['id'],d,str(path.parent))
     previews=list(path.parent.glob('*[Pp]review*'))
     if previews:item['preview']=str(previews[0])
     catalog.upsert(item);count+=1;progress(count,0)
    except (ValueError,OSError,TypeError):skipped+=1
  return count,skipped
 finally:catalog.close()

if __name__=='__main__':
 import argparse
 parser=argparse.ArgumentParser();parser.add_argument('archive');parser.add_argument('--db');args=parser.parse_args()
 print('Imported',import_archive(args.archive,args.db,lambda n,t:print(n,'/',t,flush=True)))
