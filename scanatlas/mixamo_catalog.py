"""Local index of Mixamo's public product metadata; exports use the signed-in bridge."""
import json,re,time
from collections import Counter
from datetime import datetime,timezone
from urllib.parse import urlencode
import requests
from .mixamo import GUIDE

ENDPOINT='https://www.mixamo.com/api/v1/products'
# Public application identifier used by Mixamo's own downloadable web client.
# This is not an account credential or export entitlement.
HEADERS={'X-Api-Key':'mixamo2','User-Agent':'Atlas/0.5 (local catalog metadata)'}

def page(kind,number=1,limit=96,query=''):
 r=requests.get(ENDPOINT,headers=HEADERS,params={'type':kind,'page':number,'limit':limit,'query':query,'order':''},timeout=(8,30));r.raise_for_status()
 data=r.json()
 if not isinstance(data.get('results'),list) or not isinstance(data.get('pagination'),dict):raise ValueError('Unexpected Mixamo catalog response')
 return data

def record(product,stamp):
 typ=product['type'];ident=product['id'];kind='Characters' if typ=='Character' else 'Animations'
 thumb=product.get('thumbnail','');match=re.search(r'/(motions|characters)/([^/]+)/',thumb)
 ref=match.group(1)+':'+match.group(2) if match else None
 name=product['name'];description=product.get('description') or '';category=product.get('category') or ''
 if not isinstance(category,str):category=json.dumps(category)
 tags=list(dict.fromkeys(re.findall(r'[\w-]+',(name+' '+description+' '+category).lower())))
 detail={'source':'mixamo','source_url':'https://www.mixamo.com/#/?'+urlencode({'type':'Character' if typ=='Character' else 'Motion,MotionPack','query':name}),'license':GUIDE['license'],'catalog_only':True,'source_id':ident,'source_ref':ref,'product_type':typ,'description':description,'source_metadata':product,'indexed_at':stamp,'files':[],'tags':tags,'resolutions':[],'preview_status':'source_thumbnail' if thumb else 'missing','animated_preview':product.get('thumbnail_animated'),'requires_sign_in':True,'export_supported':typ in ('Character','Motion') and bool(ref)}
 return dict(id='mixamo_catalog_'+ident,name=name,kind=kind,subtype='Animation pack' if typ=='MotionPack' else 'Animation' if typ=='Motion' else 'Character',categories=kind+' Mixamo '+category,tags=' '.join(tags),maxres=0,preview=thumb,tiny='',detail=detail,local_path='')

def sync(c,progress=lambda *args:None):
 stamp=datetime.now(timezone.utc).isoformat();products={};counts={}
 for kind in ['Character','Motion,MotionPack']:
  first=page(kind);pagination=first['pagination'];pages=int(pagination['num_pages']);expected=int(pagination['num_results']);seen={}
  if not 1<=pages<=200:raise ValueError('Unexpected page count; existing index retained')
  # The upstream relevance order is unstable across pages. Union bounded
  # sweeps by stable product ID, and publish only after the advertised count
  # is covered. A partial refresh never destroys the previous local index.
  for sweep in range(4):
   for number in range(1,pages+1):
    data=first if number==1 and sweep==0 else page(kind,number)
    for p in data['results']:seen[p['id']]=p
    progress(len(products)+len(seen),kind,number,pages)
    if len(seen)==expected:break
   if len(seen)==expected:break
  if len(seen)!=expected:raise ValueError(f'Mixamo index incomplete: {len(seen)} of {expected} {kind}. Existing index retained; retry refresh.')
  products.update(seen);counts.update(Counter(p['type'] for p in seen.values()))
 # Atomically replace only remote catalog entries; local imports are preserved.
 with c.c:
  old=[r[0] for r in c.c.execute("SELECT id FROM assets WHERE json_extract(detail,'$.source')='mixamo' AND json_extract(detail,'$.catalog_only')=1")]
  for ident in old:c.c.execute('DELETE FROM search WHERE id=?',(ident,));c.c.execute('DELETE FROM assets WHERE id=?',(ident,))
  for p in products.values():c.upsert(record(p,stamp))
 result={'indexed_assets':len(products),'counts':counts,'indexed_at':stamp,'asset_files_downloaded':False,'source':ENDPOINT}
 c.set_setting('mixamo_catalog_sync',json.dumps(result));return result

def select(c,a,bridge=None):
 from .mixamo_bridge import call
 bridge=bridge or call;d=a['detail']
 if not d.get('catalog_only') or not d.get('export_supported'):raise ValueError('Select an individual catalog character or animation, not an animation pack')
 status=bridge(c.path,'status')
 if status.get('state')!='ready':raise ValueError('Mixamo sign-in required. Open Mixamo once in Atlas to sign in.')
 if any(j.get('status') in ('preparing','downloading') for j in status.get('jobs',{}).values()):raise ValueError('Wait for the active Mixamo export to finish')
 # Match the website's default 48/page and empty order. Stable ID selects the
 # exact variant, including entries with identical human-readable names.
 kind='Character' if a['kind']=='Characters' else 'Motion,MotionPack';first=page(kind,limit=48,query=a['name']);number=None
 for n in range(1,int(first['pagination']['num_pages'])+1):
  result=first if n==1 else page(kind,n,48,a['name'])
  if any(p['id']==d['source_id'] for p in result['results']):number=n;break
 if number is None:raise ValueError('Catalog entry is no longer present in Mixamo. Refresh its index.')
 view=bridge(c.path,'search',query=a['name'],type=a['kind'],page=number)
 deadline=time.monotonic()+8
 while not any(i['ref']==d['source_ref'] for i in view.get('items',[])) and time.monotonic()<deadline:
  time.sleep(.25);view=bridge(c.path,'status')
 if not any(i['ref']==d['source_ref'] for i in view.get('items',[])):raise ValueError('Exact catalog entry did not appear in the Mixamo session')
 view=bridge(c.path,'select',ref=d['source_ref'])
 selection=view.get('selection','')
 if a['kind']=='Characters':confirmed=selection.casefold().endswith(a['name'].casefold())
 else:confirmed=selection.casefold().startswith(a['name'].casefold()+' on ')
 if not confirmed:raise ValueError('Mixamo needs confirmation in its sign-in window before this item can be exported')
 return {'id':a['id'],'selection':selection,'source_ref':d['source_ref'],'asset_files_downloaded':False}

def export(c,a,destination,character=None,execute=False):
 from pathlib import Path
 from .mixamo_bridge import call
 d=a['detail']
 if not d.get('export_supported'):raise ValueError('Export individual characters or animations; animation packs are catalog listings')
 linked=c.get(character) if character else None
 if character and (not linked or linked['kind']!='Characters' or not linked['detail'].get('local_file')):raise ValueError('Animation character must be a downloaded character ID')
 result={'id':a['id'],'dry_run':not execute,'destination':str(Path(destination).expanduser().resolve()),'type':a['kind'],'quality':'Original FBX','size_bytes':None,'character_id':character,'requires_sign_in':True,'asset_files_downloaded':False,'note':'Character-specific exports have no byte size until Mixamo creates the FBX. Original textures; Medium/2K is not applied.'}
 if not execute:return result
 if not Path(result['destination']).is_dir():raise ValueError('Choose an existing export destination folder')
 if linked:
  remote_id=linked['detail'].get('catalog_id')
  if not remote_id:raise ValueError('This older import has no verified Mixamo catalog link. Export a character from the new catalog first, or use the current session character without linking.')
  remote=c.get(remote_id)
  if not remote:raise ValueError('Linked character is absent from the remote catalog; refresh it')
  select(c,remote)
 chosen=select(c,a);call(c.path,'prepare_download')
 job=call(c.path,'download',destination=result['destination'],type=a['kind'],character=character,execute=True)
 c.c.execute('CREATE TABLE IF NOT EXISTS mixamo_catalog_exports(job_id TEXT PRIMARY KEY,catalog_id TEXT,character_id TEXT,imported_id TEXT)')
 c.c.execute('INSERT INTO mixamo_catalog_exports(job_id,catalog_id,character_id) VALUES(?,?,?)',(job['job_id'],a['id'],character));c.c.commit()
 return {**result,**job,'selection':chosen['selection']}

def reconcile(c,jobs):
 if not c.c.execute("SELECT 1 FROM sqlite_master WHERE name='mixamo_catalog_exports'").fetchone():return
 for job_id,job in jobs.items():
  if job.get('status')!='complete' or not job.get('asset_id'):continue
  row=c.c.execute('SELECT catalog_id,imported_id FROM mixamo_catalog_exports WHERE job_id=?',(job_id,)).fetchone()
  if not row or row['imported_id']:continue
  a=c.get(job['asset_id']);remote=c.get(row['catalog_id'])
  if not a or not remote:continue
  a['detail']['catalog_id']=remote['id'];a['detail']['source_ref']=remote['detail']['source_ref'];a['detail']['source_id']=remote['detail']['source_id']
  a['name']=job.get('plan',{}).get('selection') or remote['name'];a['tags']+=' '+remote['tags']
  if not a['preview']:a['preview']=remote['preview'];a['detail']['preview_status']='source_thumbnail'
  c.upsert(a);c.c.execute('UPDATE mixamo_catalog_exports SET imported_id=? WHERE job_id=?',(a['id'],job_id))
 c.c.commit()
