"""Atlas agent CLI. JSON stdout; no GUI or asset requests for catalog operations."""
from __future__ import annotations
import argparse, json, os, sys, time, uuid, subprocess, base64, hashlib
from pathlib import Path
from .catalog import Catalog, DATA, TYPES
from .huggingface import HuggingFaceClient, sync as sync_huggingface, sources
from .public_sources import PUBLIC, PublicClient, hydrate, sync_polyhaven, sync_ambientcg
from .mixamo import GUIDE, import_fbx, local_state, stage
from .downloads import build_plan, LEVELS, QuixelClient

SCHEMA='atlas.v1'
def emit(value):print(json.dumps({'schema':SCHEMA,**value},ensure_ascii=False),flush=True)
def asset(c,ident):
 a=c.get(ident)
 if not a:raise ValueError('Unknown asset ID: '+ident)
 return a

def plans(a,files=False):
 if a['detail'].get('source')=='mixamo':return {}
 if a['detail'].get('manifest_pending'):return {q:{'available':None,'reason':'File metadata pending; run atlas plan ID','next_action':'plan'} for q in LEVELS}
 result={}
 for quality in LEVELS:
  try:
   p=build_plan(a,quality);p['file_count']=len(p['files']);p['size_bytes']=p.pop('bytes');p['size_is_complete']=p.pop('complete_size')
   if not files:p.pop('files')
   result[quality]=p
  except ValueError as ex:result[quality]={'available':False,'reason':str(ex)}
 return result

def describe(c,a,full=False):
 history=[dict(r) for r in c.c.execute('SELECT * FROM downloads WHERE asset_id=? ORDER BY id DESC',(a['id'],))]
 for h in history:h['path_exists']=Path(h['path']).is_dir()
 result={k:a[k] for k in ('id','name','kind','subtype','maxres')}
 result.update(source_url=a['detail'].get('source_url'),repository=a['detail'].get('repository'),revision=a['detail'].get('revision'),duplicate_key='quixel:'+a['detail'].get('quixel_id',a['id']),source=a['detail'].get('source','Quixel'),license=a['detail'].get('license','Account license'),quixel_id=a['detail'].get('quixel_id',a['id']),download_access='public_source' if a['detail'].get('source')=='huggingface' else 'account_required',tags=a['detail'].get('tags',[]),metadata=a['detail'].get('meta',{}),resolutions=a['detail'].get('resolutions',[]),preview_url=a['preview'],qualities=plans(a,full),ownership={'state':'acquired_last_sync' if c.c.execute('SELECT 1 FROM owned WHERE id=?',(a['id'],)).fetchone() else 'unverified','checked_live':False},local_library_path=a['local_path'] or None,downloads=history)
 if a['detail'].get('source')=='mixamo' and not a['detail'].get('catalog_only'):
  result.update(duplicate_key='sha256:'+a['detail']['sha256'],quixel_id=None,download_access='local_file',availability=local_state(a),next_action='stage' if Path(a['detail']['local_file']).is_file() else 'import-mixamo',animation={k:a['detail'].get(k) for k in ('character_id','rig_validation','duration_seconds','frame_rate','root_motion')})
 if a['detail'].get('source') in ('polyhaven','ambientcg'):
  result.update(duplicate_key=a['id'],quixel_id=None,download_access='public_source',next_action='plan',file_metadata_pending=a['detail'].get('manifest_pending',False))
 if a['detail'].get('catalog_only'):
  result.update(duplicate_key='mixamo:'+a['detail']['source_id'],quixel_id=None,download_access='mixamo_session',availability=local_state(a),next_action=local_state(a)['next_action'],source_ref=a['detail']['source_ref'],description=a['detail'].get('description',''))
 result['my_asset']=a['detail'].get('my_asset',False)
 if full:result['source_detail']=a['detail']
 return result

def brief(a):
 d=a['detail']
 result={k:a[k] for k in ('id','name','kind','subtype')}
 result.update(source=d.get('source','Quixel'),preview=a['preview'] or None,my_asset=d.get('my_asset',False))
 if d.get('source')=='mixamo':result.update(availability=local_state(a),next_action=local_state(a)['next_action'],source_ref=d.get('source_ref'))
 else:result.update(next_action='plan',qualities=plans(a))
 return result

def job_schema(c):
 c.c.execute('''CREATE TABLE IF NOT EXISTS agent_jobs(id TEXT PRIMARY KEY,asset_id TEXT,quality TEXT,destination TEXT,status TEXT,bytes_done INTEGER DEFAULT 0,bytes_total INTEGER DEFAULT 0,current_file TEXT,path TEXT,error TEXT,created REAL,updated REAL,cancel_requested INTEGER DEFAULT 0)''');c.c.commit()
def job_update(c,j,**values):
 values['updated']=time.time();c.c.execute('UPDATE agent_jobs SET '+','.join(k+'=?' for k in values)+' WHERE id=?',list(values.values())+[j]);c.c.commit()
def new_job(c,a,p,destination):
 job_schema(c);j=uuid.uuid4().hex
 c.c.execute('INSERT INTO agent_jobs(id,asset_id,quality,destination,status,bytes_total,created,updated) VALUES(?,?,?,?,?,?,?,?)',(j,a['id'],p['quality'],str(Path(destination).expanduser().resolve()),'queued',p['bytes'],time.time(),time.time()));c.c.commit();return j

def tracked_download(c,a,p,destination,client,progress=lambda *args:None,cancel=lambda:False,job_id=None):
 job_schema(c);j=job_id or new_job(c,a,p,destination);job_update(c,j,status='authorizing');last=0
 def cancelled():return cancel() or bool(c.c.execute('SELECT cancel_requested FROM agent_jobs WHERE id=?',(j,)).fetchone()[0])
 def update(done,total,name):
  nonlocal last
  if time.monotonic()-last>.2:
   job_update(c,j,status='downloading',bytes_done=done,bytes_total=total,current_file=name);last=time.monotonic()
  progress(done,total,name)
 try:
  path=client.download(a,p,destination,update,cancelled)
  c.record_download(a['id'],p['quality'],path);job_update(c,j,status='complete',path=path,bytes_done=sum((Path(path)/f['name']).stat().st_size for f in p['files']),current_file=None)
  return path
 except (Exception,KeyboardInterrupt) as ex:
  job_update(c,j,status='cancelled' if isinstance(ex,(InterruptedError,KeyboardInterrupt)) else 'failed',error=str(ex) or 'Interrupted');raise

def preview(c,ids,output,fetch=False):
 # Qt raster rendering works headlessly; no asset endpoints are used.
 os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
 from PySide6.QtWidgets import QApplication
 from PySide6.QtGui import QImage,QPainter,QColor,QFont
 from PySide6.QtCore import QRect,Qt
 import requests
 app=QApplication.instance() or QApplication([])
 selected=[asset(c,i) for i in ids]
 if not 1<=len(selected)<=24:raise ValueError('Preview sheets support 1–24 IDs')
 output=Path(output).expanduser().resolve()
 if output.exists() or output.with_suffix('.json').exists():raise FileExistsError('Preview output or manifest already exists')
 output.parent.mkdir(parents=True,exist_ok=True)
 cols=min(4,len(selected));w,h=(800,650) if len(selected)==1 else (400,350)
 canvas=QImage(cols*w,((len(selected)+cols-1)//cols)*h,QImage.Format_RGB32);canvas.fill(QColor('#111a20'));p=QPainter(canvas);entries=[]
 try:
  for n,a in enumerate(selected):
   x,y=n%cols*w,n//cols*h;gallery=a['detail'].get('gallery',[]);url=(gallery[min(1,len(gallery)-1)] if len(selected)==1 and fetch and gallery else a['preview']);cache=DATA/'previews'/(hashlib.sha256(url.encode()).hexdigest()+'.img');im=QImage();source='unavailable';error=None
   from .preview_cache import resolve
   try:
    path,source=resolve(url,root=c.path.parent/'previews',fetch=fetch)
    if path:im.load(str(path))
   except Exception as ex:error=str(ex)
   if im.isNull() and a['tiny']:
    try:im.loadFromData(base64.b64decode(a['tiny'].split(',',1)[1]));source='embedded_low_resolution'
    except Exception:pass
   box=QRect(x+12,y+10,w-24,h-120)
   if not im.isNull():
    scaled=im.scaled(box.size(),Qt.KeepAspectRatio,Qt.SmoothTransformation);p.drawImage(box.x()+(box.width()-scaled.width())//2,box.y()+(box.height()-scaled.height())//2,scaled)
   else:p.setPen(QColor('#d4dce0'));p.drawText(box,Qt.AlignCenter,'Preview unavailable');source='unavailable'
   p.setPen(QColor('#e6eeee'));p.setFont(QFont('DejaVu Sans',11));p.drawText(QRect(x+12,y+h-105,w-24,24),Qt.AlignLeft,p.fontMetrics().elidedText(f'{n+1}. {a["name"]}',Qt.ElideRight,w-24))
   p.setFont(QFont('DejaVu Sans',9));p.drawText(x+12,y+h-63,f'ID: {a["id"]}  |  {a["kind"]}')
   q=plans(a);sizes=' | '.join(k+': '+(f'{v["size_bytes"]/1048576:.1f} MiB'+('~' if not v['size_is_complete'] else '') if 'size_bytes' in v else 'n/a') for k,v in q.items())
   if a['detail'].get('source')=='mixamo':
    local=local_state(a);sizes="Mixamo catalog · export requires signed-in session · size pending" if a['detail'].get('catalog_only') else f"Local package: {local['size_bytes']/1048576:.1f} MiB · {local['file_count']} files"
   p.drawText(QRect(x+12,y+h-53,w-24,48),Qt.TextWordWrap,sizes)
   entries.append({'number':n+1,'id':a['id'],'name':a['name'],'bounds_xywh':[x,y,w,h],'preview_source':source,'preview_url':url,'image_pixels':[im.width(),im.height()] if not im.isNull() else None,'preview_error':error,'qualities':q})
 finally:p.end()
 if not canvas.save(str(output),'PNG'):raise OSError('Could not save preview sheet')
 manifest=output.with_suffix('.json');manifest.write_text(json.dumps({'schema':SCHEMA,'image_path':str(output),'items':entries},indent=2))
 return {'image_path':str(output),'manifest_path':str(manifest),'items':entries,'asset_files_downloaded':False}

def parser():
 p=argparse.ArgumentParser(prog='atlas',description='Atlas agent interface: JSON metadata and labeled vision previews. Run atlas gui for desktop.');p.add_argument('--database',type=Path)
 sub=p.add_subparsers(dest='command',required=True)
 sub.add_parser('mixamo-service');sub.add_parser('mcp')
 m=sub.add_parser('mixamo');ms=m.add_subparsers(dest='mixamo_action',required=True)
 ms.add_parser('connect');ms.add_parser('disconnect');ms.add_parser('status');ms.add_parser('prepare-download')
 x=ms.add_parser('search');x.add_argument('query',nargs='?',default='');x.add_argument('--type',choices=['Characters','Animations'],default='Animations');x.add_argument('--page',type=int,default=1)
 x=ms.add_parser('select');x.add_argument('ref')
 x=ms.add_parser('preview');x.add_argument('--output',required=True)
 x=ms.add_parser('download');x.add_argument('--destination',required=True);x.add_argument('--type',choices=['Characters','Animations'],default='Animations');x.add_argument('--character');x.add_argument('--execute',action='store_true')
 sub.add_parser('mixamo-guide');sub.add_parser('sync-mixamo')
 s=sub.add_parser('mixamo-select');s.add_argument('id')
 s=sub.add_parser('mixamo-export');s.add_argument('id');s.add_argument('--destination',required=True);s.add_argument('--character');s.add_argument('--execute',action='store_true')
 s=sub.add_parser('import-mixamo');s.add_argument('path');s.add_argument('--type',choices=['Characters','Animations'],required=True);s.add_argument('--character');s.add_argument('--preview');s.add_argument('--tags',default='');s.add_argument('--name');s.add_argument('--my-asset',action='store_true',help='Show this personal derivative under My assets');s.add_argument('--bundle',help='Index every file in this package directory for hash-checked staging')
 s=sub.add_parser('stage');s.add_argument('ids',nargs='+');s.add_argument('--destination',required=True);s.add_argument('--execute',action='store_true')
 s=sub.add_parser('unity-configure');s.add_argument('project')
 s=sub.add_parser('unity-import');s.add_argument('id');s.add_argument('--project');s.add_argument('--quality',choices=LEVELS,default='Medium');s.add_argument('--source');s.add_argument('--rig',choices=['auto','generic','humanoid','none'],default='auto');s.add_argument('--execute',action='store_true')
 s=sub.add_parser('unity-status');s.add_argument('--job');s.add_argument('--project')
 sub.add_parser('sources');sub.add_parser('sync-huggingface');sub.add_parser('sync-public');sub.add_parser('capabilities');sub.add_parser('facets');sub.add_parser('gui')
 s=sub.add_parser('search');s.add_argument('query',nargs='?',default='');s.add_argument('--type',action='append',choices=TYPES,dest='types');s.add_argument('--source',default='',choices=['',*PUBLIC,'mixamo']);s.add_argument('--subtype',default='');s.add_argument('--min-resolution',type=int,default=0);s.add_argument('--limit',type=int,default=20);s.add_argument('--offset',type=int,default=0);s.add_argument('--available-quality',choices=LEVELS);s.add_argument('--brief',action='store_true',help='Compact results for agent discovery; inspect selected IDs for full plans');s.add_argument('--literal',action='store_true');s.add_argument('--scope',choices=['favorites','owned','downloaded','my-assets'],default='')
 s=sub.add_parser('inspect');s.add_argument('id')
 s=sub.add_parser('plan');s.add_argument('id');s.add_argument('--quality',choices=LEVELS,default='Medium')
 s=sub.add_parser('render-previews');s.add_argument('ids',nargs='*');s.add_argument('--retry',action='store_true')
 s=sub.add_parser('preview');s.add_argument('ids',nargs='+');s.add_argument('--output',required=True);s.add_argument('--fetch-previews',action='store_true')
 s=sub.add_parser('status');s.add_argument('--job');s.add_argument('--asset')
 s=sub.add_parser('cancel');s.add_argument('job')
 s=sub.add_parser('download');s.add_argument('id');s.add_argument('--quality',choices=LEVELS,default='Medium');s.add_argument('--destination',required=True);s.add_argument('--execute',action='store_true');s.add_argument('--background',action='store_true')
 s=sub.add_parser('_worker');s.add_argument('job')
 return p

def main():
 args=parser().parse_args()
 if args.command=='mixamo-service':
  from .mixamo_service import main as service
  service(args.database);return
 if args.command=='mcp':
  from .mcp_server import serve
  serve(args.database);return
 if args.command=='gui':
  from .app import main as gui
  sys.argv=sys.argv[:1];gui();return
 c=Catalog(args.database)
 try:
  job_schema(c)
  if args.command=='mixamo':
   from .mixamo_bridge import call
   values=vars(args).copy();values.pop('command');values.pop('database');action=values.pop('mixamo_action').replace('-','_');emit(call(c.path,action,**values))
  elif args.command=='sync-mixamo':
   from .mixamo_catalog import sync
   emit(sync(c))
  elif args.command=='mixamo-select':
   from .mixamo_catalog import select
   emit(select(c,asset(c,args.id)))
  elif args.command=='mixamo-export':
   from .mixamo_catalog import export
   emit(export(c,asset(c,args.id),args.destination,args.character,args.execute))
  elif args.command=='mixamo-guide':emit(GUIDE)
  elif args.command=='import-mixamo':emit({'asset':describe(c,import_fbx(c,args.path,args.type,args.character,args.preview,args.tags,args.name,args.my_asset,args.bundle),True)})
  elif args.command=='stage':emit(stage(c,args.ids,args.destination,args.execute))
  elif args.command=='unity-configure':
   from .unity_import import configure
   emit(configure(c,args.project))
  elif args.command=='unity-import':
   from .unity_import import submit
   emit(submit(c,args.id,project=args.project,quality=args.quality,execute=args.execute,source=args.source,rig=args.rig))
  elif args.command=='unity-status':
   from .unity_import import job_status
   emit(job_status(c,args.job,args.project))
  elif args.command=='sources':emit({'sources':sources(c)})
  elif args.command=='sync-public':
   results=[]
   for sync_fn in (sync_polyhaven,sync_ambientcg,sync_huggingface):
    try:results.append(sync_fn(c))
    except Exception as ex:results.append({'source':sync_fn.__name__,'error':str(ex)})
   emit({'sources':results})
  elif args.command=='sync-huggingface':emit(sync_huggingface(c))
  elif args.command=='capabilities':
   emit({'name':'Atlas','version':'0.6.2','database':str(c.path),'active_source':'connected_catalogs','source_filter':c.setting('active_source','Quixel'),'asset_count':c.count(),'commands':['unity-configure','unity-import','unity-status','mixamo','mixamo-service','mcp','sync-public','mixamo-guide','sync-mixamo','mixamo-select','mixamo-export','import-mixamo','stage','sources','sync-huggingface','search','inspect','plan','preview','render-previews','status','download','cancel','facets','gui'],'types':TYPES,'qualities':list(LEVELS),'documentation':str(Path(__file__).parent/'AGENT_GUIDE.md'),'semantics':{'unity_import':'Download first, then unity-import ID --execute copies/extracts into the sole open Unity project by default, otherwise the saved project. Pass --project to select explicitly. Unity Editor prepares assets while open; poll unity-status for completion, outputs and warnings. Dry-run by default; no scene changes.', 'search':'Local JSON metadata; use --scope my-assets for saved derivatives (FPS arms). inspect source_detail and stage the complete package; read CODEX_README.md. Types OR together; --source filters providers. --available-quality includes Poly Haven candidates with pending file metadata: available=null is NOT verified; run plan on chosen IDs.','preview':'PNG contact sheet + JSON ID and rectangle manifest. Cache-only unless --fetch-previews; never downloads models/textures.','plan':'Exact selected filenames and estimated bytes; no transfer','download':'Dry run unless --execute. Poly Haven and ambientCG use official public files without tokens; ZIPs require extraction. Hugging Face entries use public pinned files; Quixel entries require ATLAS_QUIXEL_TOKEN. --background returns job ID. Legacy Quixel adapter; live service not verified.','status':'Durable job state, transferred bytes, heartbeat time, error and output path. Abrupt process death can leave a stale nonterminal state.','ownership':'Last-sync metadata is not proof; checked live before each transfer','auth':'Token stays in process environment/memory; never written to job database or command arguments'}})
  elif args.command=='facets':emit({'facets':[{'type':t,'subtype':s,'count':n} for t,s,n in c.facets()]})
  elif args.command=='search':
   if not 1<=args.limit<=100 or args.offset<0:raise ValueError('limit must be 1–100 and offset nonnegative')
   rows,total,related=c.query(args.query,kinds=args.types,subtype=args.subtype,minres=args.min_resolution,scope=args.scope,limit=c.count() if args.available_quality else args.limit,offset=0 if args.available_quality else args.offset,related=not args.literal,source=args.source)
   if args.available_quality:
    eligible=[]
    for row in rows:
     try:
      a=asset(c,row['id'])
      if a['detail'].get('manifest_pending'):
       if a['maxres']>=LEVELS[args.available_quality][0] if LEVELS[args.available_quality][0] else True:eligible.append(row)
      else:build_plan(a,args.available_quality);eligible.append(row)
     except ValueError:pass
    total=len(eligible);rows=eligible[args.offset:args.offset+args.limit]
   emit({'quality_filter_note':'Pending Poly Haven entries are candidates only; run plan to verify exact quality and bytes.' if args.available_quality else None,'total':total,'offset':args.offset,'next_offset':args.offset+len(rows) if args.offset+len(rows)<total else None,'related_terms':related,'items':[brief(asset(c,r['id'])) if args.brief else describe(c,asset(c,r['id'])) for r in rows]})
  elif args.command=='inspect':emit({'asset':describe(c,asset(c,args.id),True)})
  elif args.command=='plan' and asset(c,args.id)['detail'].get('source')=='mixamo':emit({'id':args.id,'availability':local_state(asset(c,args.id)),'next_action':'Use atlas mixamo-export ID --destination FOLDER; add --execute to export' if asset(c,args.id)['detail'].get('catalog_only') else 'Use atlas stage ID --destination NEW_FOLDER; add --execute to copy'})
  elif args.command=='plan':emit({'id':args.id,'plan':plans(hydrate(c,asset(c,args.id)),True)[args.quality],'asset_files_downloaded':False})
  elif args.command=='render-previews':
   from .local_previews import run
   emit(run(c,args.ids,args.retry))
  elif args.command=='preview':emit(preview(c,args.ids,args.output,args.fetch_previews))
  elif args.command=='status':
   where=[];values=[]
   if args.job:where.append('id=?');values.append(args.job)
   if args.asset:where.append('asset_id=?');values.append(args.asset)
   rows=[dict(r) for r in c.c.execute('SELECT * FROM agent_jobs'+(' WHERE '+' AND '.join(where) if where else '')+' ORDER BY created DESC LIMIT 100',values)]
   for row in rows:
    row['heartbeat_age_seconds']=round(time.time()-row['updated'],2);row['potentially_stale']=row['status'] not in ('complete','failed','cancelled') and row['heartbeat_age_seconds']>180
    row['progress_percent']=100 if row['status']=='complete' else round(min(100,max(0,row['bytes_done']/row['bytes_total']*100)),1) if row['bytes_total'] and row['bytes_total']>0 else None
   emit({'jobs':rows,'download_history':[dict(r) for r in c.c.execute('SELECT * FROM downloads'+(' WHERE asset_id=?' if args.asset else '')+' ORDER BY id DESC LIMIT 100',([args.asset] if args.asset else []))]})
  elif args.command=='cancel':
   if not c.c.execute('SELECT 1 FROM agent_jobs WHERE id=?',(args.job,)).fetchone():raise ValueError('Unknown job')
   job_update(c,args.job,cancel_requested=1);emit({'job_id':args.job,'cancel_requested':True})
  elif args.command in ('download','_worker'):
   if args.command=='download':
    a=hydrate(c,asset(c,args.id));p=build_plan(a,args.quality)
    if not args.execute:emit({'dry_run':True,'asset':describe(c,a),'plan':p,'destination':str(Path(args.destination).expanduser().resolve())});return
    if a['detail'].get('source') not in PUBLIC and not os.environ.get('ATLAS_QUIXEL_TOKEN'):raise ValueError('Set ATLAS_QUIXEL_TOKEN in the environment; do not pass credentials as arguments')
    if not Path(args.destination).expanduser().is_dir():raise ValueError('Destination must be an existing directory')
    j=new_job(c,a,p,args.destination)
    if args.background:
     proc=subprocess.Popen([sys.executable,'-m','scanatlas.agent','--database',str(c.path.resolve()),'_worker',j],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
     emit({'job_id':j,'pid':proc.pid,'status':'queued'});return
   else:j=args.job
   row=c.c.execute('SELECT * FROM agent_jobs WHERE id=?',(j,)).fetchone();a=asset(c,row['asset_id']);p=build_plan(a,row['quality'])
   path=tracked_download(c,a,p,row['destination'],HuggingFaceClient() if a['detail'].get('source')=='huggingface' else PublicClient() if a['detail'].get('source') in ('polyhaven','ambientcg') else QuixelClient(os.environ.get('ATLAS_QUIXEL_TOKEN','')),job_id=j)
   emit({'job_id':j,'status':'complete','path':path,'manifest_path':str(Path(path)/'download.json')})
 except Exception as ex:emit({'error':{'code':type(ex).__name__,'message':str(ex)}});sys.exit(1)
 finally:c.close()

if __name__=='__main__':main()
