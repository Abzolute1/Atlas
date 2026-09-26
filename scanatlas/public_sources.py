"""Official CC0 catalogs; metadata sync never downloads asset payloads."""
import re
from pathlib import PurePosixPath
from urllib.parse import urlparse, unquote, parse_qs, urlencode, urlunparse
import requests
from .downloads import transfer_files

PUBLIC=('huggingface','polyhaven','ambientcg')
HEADERS={'User-Agent':'Atlas/0.3 (local asset catalog; Poly Haven integration)'}
def get(url):
 r=requests.get(url,headers=HEADERS,timeout=(10,60));r.raise_for_status();return r.json()
def walk(node):
 if isinstance(node,dict):
  yield node
  for v in node.values():yield from walk(v)
 elif isinstance(node,list):
  for v in node:yield from walk(v)
def record(source,ident,name,kind,tags,preview,detail):
 detail.update(source=source,license='CC0',tags=tags)
 return dict(id=source+'_'+ident,name=name,kind=kind,subtype=detail.pop('subtype',''),categories=' '.join(tags),tags=' '.join(tags),maxres=max(detail.get('resolutions',[]),default=0),preview=preview,tiny='',detail=detail)
def sync_polyhaven(c):
 data=get('https://api.polyhaven.com/assets');count=0
 with c.c:
  for ident,d in data.items():
   old=c.get('polyhaven_'+ident);cached=old['detail'].get('files',[]) if old else []
   tags=list(dict.fromkeys(d.get('tags',[])+d.get('categories',[])))
   a=record('polyhaven',ident,d['name'],{0:'HDRIs',1:'Surfaces',2:'3D Assets'}.get(d['type'],'Other'),tags,d.get('thumbnail_url',''),{'source_id':ident,'source_url':'https://polyhaven.com/a/'+ident,'files':cached,'manifest_pending':not bool(cached),'resolutions':[d.get('max_resolution',[0])[0]],'subtype':d.get('category','').split('/')[-1],'meta':{'Polycount':d.get('polycount'),'Dimensions (mm)':d.get('dimensions')},'source_metadata':d})
   c.upsert(a);count+=1
 return {'source':'polyhaven','indexed_assets':count,'asset_files_downloaded':False}
def sync_ambientcg(c):
 url='https://ambientcg.com/api/v2/full_json?limit=250&include=downloadData,imageData';items=[];seen=set()
 while url:
  if url in seen:raise ValueError('ambientCG pagination repeated')
  seen.add(url);data=get(url);items+=data['foundAssets'];url=data.get('nextPageHttp')
  if url:
   parsed=urlparse(url);params=parse_qs(parsed.query);params['include']=['downloadData,imageData'];url=urlunparse(parsed._replace(query=urlencode(params,doseq=True)))
 with c.c:
  for d in items:
   ident=d['assetId'];files=[]
   for f in walk(d.get('downloadFolders',{})):
    if not f.get('downloadLink') or not f.get('fileName'):continue
    name=f['fileName'];m=re.search(r'_(\d+)K',name,re.I)
    files.append({'name':name,'type':'package','resolution':int(m[1])*1024 if m else 0,'size':f.get('size',0),'mime':'application/zip','url':f['downloadLink'],'lod':None,'format':f.get('attribute','')})
   tags=d.get('tags',[]) or [];tags=tags if isinstance(tags,list) else [str(tags)]
   tags=list(dict.fromkeys(tags+[d.get('displayCategory','') or '',d.get('displayName',ident)]))
   a=record('ambientcg',ident,d.get('displayName') or ident,{'Material':'Surfaces','3DModel':'3D Assets','HDRI':'HDRIs','Decal':'Decals','Atlas':'Atlases'}.get(d.get('dataType'),'Other'),tags,d.get('previewImage',{}).get('512-PNG',''),{'source_id':ident,'source_url':d.get('shortLink','https://ambientcg.com/a/'+ident),'files':files,'resolutions':sorted({f['resolution'] for f in files}),'subtype':d.get('displayCategory') or d.get('dataType',''),'meta':{'Dimensions (cm)':[d.get('dimensionX'),d.get('dimensionY'),d.get('dimensionZ')]}})
   c.upsert(a)
 return {'source':'ambientcg','indexed_assets':len(items),'asset_files_downloaded':False}
def hydrate(c,a):
 d=a['detail']
 if d.get('source')!='polyhaven' or not d.get('manifest_pending'):return a
 data=get('https://api.polyhaven.com/files/'+d['source_id']);files=[]
 mapping={'Diffuse':'albedo','diff':'albedo','nor_gl':'normal','Rough':'roughness','rough':'roughness','AO':'ao','ao':'ao','Displacement':'displacement','disp':'displacement','Metal':'metalness'}
 for component,levels in data.items():
  for level,formats in levels.items():
   m=re.fullmatch(r'(\d+)k',level,re.I)
   if not m:continue
   resolution=int(m[1])*1024
   for fmt,f in formats.items():
    if not isinstance(f,dict) or not f.get('url'):continue
    typ=mapping.get(component)
    if a['kind']=='HDRIs' and fmt in ('hdr','exr'):typ='hdri'
    if component=='fbx' and fmt=='fbx':typ='mesh'
    if not typ or (typ not in ('mesh','hdri') and fmt not in ('jpg','png')):continue
    files.append(dict(name=unquote(PurePosixPath(urlparse(f['url']).path).name),type=typ,resolution=resolution,size=f['size'],mime='application/x-fbx' if typ=='mesh' else 'image/jpeg' if fmt=='jpg' else 'image/'+fmt,url=f['url'],md5=f.get('md5'),lod=None,mesh_type='original'))
    if typ=='mesh':
     for name,dep in f.get('include',{}).items():
      files.append(dict(name=name,type='dependency',resolution=resolution,size=dep['size'],mime='application/octet-stream',url=dep['url'],md5=dep.get('md5'),lod=None))
 d.update(files=files,manifest_pending=False,resolutions=sorted({f['resolution'] for f in files}));a['maxres']=max(d['resolutions'],default=0);c.upsert(a);c.c.commit();return a

class PublicClient:
 def download(self,a,plan,destination,progress=lambda *a:None,cancel=lambda:False):
  allowed={'polyhaven':{'dl.polyhaven.org'},'ambientcg':{'ambientcg.com'}}[a['detail']['source']]
  urls={}
  for f in plan['files']:
   u=urlparse(f['url'])
   if u.scheme!='https' or u.hostname not in allowed:raise ValueError('Unexpected public source host')
   urls[f['name']]=f['url']
  return transfer_files(a,plan,destination,urls,progress,cancel)
