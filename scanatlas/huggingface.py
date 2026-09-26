"""Pinned, individually addressable files from the user-selected HF repository."""
import hashlib
import re
from pathlib import PurePosixPath
from urllib.parse import quote
import requests
from .downloads import transfer_files

REPO='Sl8th/Megascans'
BASE='https://huggingface.co/datasets/'+REPO

def sync(c):
 info=requests.get('https://huggingface.co/api/datasets/'+REPO,timeout=30);info.raise_for_status();revision=info.json()['sha']
 url='https://huggingface.co/api/datasets/'+REPO+'/tree/'+revision+'?recursive=true&limit=1000'
 entries=[]
 while url:
  r=requests.get(url,timeout=30);r.raise_for_status();entries.extend(r.json());url=r.links.get('next',{}).get('url')
 folders={}
 for e in entries:
  if e['type']=='file':folders.setdefault(str(PurePosixPath(e['path']).parent),[]).append(e)
 count=0
 with c.c:
  c.c.execute("DELETE FROM search WHERE id IN (SELECT id FROM assets WHERE id LIKE 'hf_%')")
  c.c.execute("DELETE FROM assets WHERE id LIKE 'hf_%'")
  for folder,items in folders.items():
   metadata=[e for e in items if e['path'].endswith('.json')]
   if len(metadata)!=1 or not folder.startswith('megascans 2/'):continue
   original=PurePosixPath(metadata[0]['path']).stem
   files=[];preview=''
   for e in items:
    name=PurePosixPath(e['path']).name
    uri=BASE+'/resolve/'+revision+'/'+quote(e['path'],safe='/')
    if '_Preview.' in name:preview=uri;continue
    ext=PurePosixPath(name).suffix.lower();res=re.search(r'_(\d+)K_',name,re.I);lod=re.search(r'_LOD(\d+)',name,re.I)
    if ext=='.fbx':kind='mesh'
    elif ext in ('.jpg','.png') and res:
     m=re.search(r'_(Albedo|Diffuse|AO|Normal|Roughness|Metalness|Opacity|Translucency|Displacement|Specular)(?:_|\.)',name,re.I)
     if not m:continue
     kind=m[1].lower()
    else:continue
    files.append(dict(name=name,type=kind,resolution=int(res[1])*1024 if res else 0,size=e['size'],mime='application/x-fbx' if ext=='.fbx' else 'image/jpeg' if ext=='.jpg' else 'image/png',lod=int(lod[1]) if lod else None,mesh_type='lod',url=uri,sha256=e.get('lfs',{}).get('oid'),physical=''))
   packages=[]
   for e in items:
    if not e['path'].lower().endswith('.zip'):continue
    name=PurePosixPath(e['path']).name;m=re.search(r'_(\d+)K',name,re.I)
    packages.append(dict(name=name,type='package',resolution=int(m[1])*1024 if m else 0,size=e['size'],mime='application/zip',url=BASE+'/resolve/'+revision+'/'+quote(e['path'],safe='/'),sha256=e.get('lfs',{}).get('oid'),lod=None))
   if not files and not packages:continue
   meshes=any(f['type']=='mesh' for f in files)
   archives=' '.join(e['path'] for e in items if e['path'].endswith('.zip')).lower()
   kind='3D Plants' if meshes and '3dplant' in archives else '3D Assets' if meshes else 'Atlases' if '_atlas_' in archives else 'Decals' if '_decal_' in archives else 'Surfaces'
   package_only=not files or (('_3d_' in archives or '_3dplant_' in archives) and not meshes)
   if package_only:
    files=packages
    if not files:continue
    kind='3D Plants' if '_3dplant_' in archives else '3D Assets' if '_3d_' in archives else kind
   name=PurePosixPath(folder).name.title();resolutions=sorted({f['resolution'] for f in files if f['resolution']})
   ident='hf_'+original
   c.upsert(dict(id=ident,name=name,kind=kind,subtype='Hugging Face',categories=kind+' '+name,tags=name.lower(),maxres=max(resolutions,default=0),preview=preview,tiny='',detail={'source':'huggingface','repository':REPO,'revision':revision,'quixel_id':original,'license':'Not stated by uploader; redistribution rights unverified','source_url':BASE+'/tree/'+revision+'/'+quote(folder,safe='/'),'files':files,'packages':packages,'package_only':package_only,'tags':name.lower().split(),'resolutions':resolutions,'gallery':[preview] if preview else [],'meta':{}}))
   count+=1
  covered={f['url'] for row in c.c.execute("SELECT detail FROM assets WHERE json_extract(detail,'$.source')='huggingface'") for f in __import__('json').loads(row[0]).get('packages',[])}
  for e in entries:
   if e['type']!='file' or not e['path'].lower().endswith('.zip'):continue
   uri=BASE+'/resolve/'+revision+'/'+quote(e['path'],safe='/')
   if uri in covered:continue
   name=PurePosixPath(e['path']).name;m=re.search(r'_(\d+)K',name,re.I);res=int(m[1])*1024 if m else 0
   ident='hf_package_'+hashlib.sha256(e['path'].encode()).hexdigest()[:20]
   file=dict(name=name,type='package',resolution=res,size=e['size'],mime='application/zip',url=uri,sha256=e.get('lfs',{}).get('oid'),lod=None)
   title=name.removesuffix('.zip').replace('_',' ').replace('-',' ')
   c.upsert(dict(id=ident,name=title,kind='3D Assets' if 'SKETCHFAB' in e['path'] else 'Surfaces',subtype='Archive package',categories=title,tags=title,maxres=res,preview='',tiny='',detail={'source':'huggingface','repository':REPO,'revision':revision,'license':'Not stated by uploader; original asset license unverified','source_url':BASE+'/blob/'+revision+'/'+quote(e['path'],safe='/'),'files':[file],'package_only':True,'resolutions':[res] if res else [],'tags':title.split(),'meta':{'Archive':'Contents not inspected','Quality':'Unknown; Ultra selects original package' if not res else str(res)}}))
   count+=1
 c.set_setting('active_source','huggingface')
 return {'source':REPO,'revision':revision,'available_assets':count,'asset_files_downloaded':False,'license':'Unstated; not verified as CC0 or authorized redistribution'}

class HuggingFaceClient:
 def download(self,asset,plan,destination,progress=lambda *a:None,cancel=lambda:False):
  urls={}
  prefix=BASE+'/resolve/'+asset['detail']['revision']+'/'
  for f in plan['files']:
   if not f.get('url','').startswith(prefix):raise ValueError('Unexpected Hugging Face file source')
   urls[f['name']]=f['url']
  return transfer_files(asset,plan,destination,urls,progress,cancel)

def sources(c):
 return [
  *[{'id':s,'name':n,'url':u,'status':'public_catalog','indexed_assets':c.c.execute("SELECT count(*) FROM assets WHERE json_extract(detail,'$.source')=?",(s,)).fetchone()[0],'license':'CC0','reason':'Official catalog; select an asset to resolve exact file sizes and quality options'} for s,n,u in [('polyhaven','Poly Haven','https://polyhaven.com'),('ambientcg','ambientCG','https://ambientcg.com')]],
  {'id':'mixamo','name':'Mixamo · Characters & Animations','url':'https://www.mixamo.com/','status':'indexed_catalog_and_local_imports','indexed_assets':c.c.execute("SELECT count(*) FROM assets WHERE json_extract(detail,'$.source')='mixamo'").fetchone()[0],'reason':'Full catalog metadata and cached previews are searchable locally. Export chosen characters/animations through the signed-in background session; local imports are staged separately.','license':'Adobe Mixamo terms; royalty-free project use, not CC0'},
  {'id':'huggingface','name':'Hugging Face · Sl8th/Megascans','url':BASE,'status':'indexed_public_files','indexed_assets':c.c.execute("SELECT count(*) FROM assets WHERE json_extract(detail,'$.source')='huggingface'").fetchone()[0],'license':'Not stated; redistribution permission unverified'},
  {'id':'cger-3d','name':'CGer · Megascans Archive — 3D','url':'https://www.cger.com/down/137-331-5','status':'listing_only','advertised_assets':4237,'advertised_size':'940 GB','download_available':False,'reason':'No inspected per-asset manifest or verified download access','license':'Redistribution permission unverified'},
  {'id':'cger-surfaces','name':'CGer · Megascans Archive — Surfaces','url':'https://www.cger.com/site/65213.html','status':'listing_only','advertised_assets':8211,'advertised_size':'1.42 TB','download_available':False,'reason':'No inspected per-asset manifest or verified download access','license':'Redistribution permission unverified'}]
