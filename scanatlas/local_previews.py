"""Offline Blender thumbnails for already-imported FBXs. No asset downloads."""
import fcntl,json,os,shutil,subprocess,sys,tempfile
from pathlib import Path
from .catalog import Catalog


def blender_path(c):
 configured=c.setting('preview_blender')
 return configured if configured and Path(configured).is_file() else shutil.which('blender')


def pending(c,retry=False):
 return [c.get(r[0]) for r in c.c.execute("SELECT id FROM assets WHERE json_extract(detail,'$.source')='mixamo' AND json_extract(detail,'$.local_file') IS NOT NULL AND preview=''" + ("" if retry else " AND coalesce(json_extract(detail,'$.preview_status'),'missing')!='failed'"))]


def launch(c):
 """A separate process keeps catalog imports and UI responsive."""
 if not blender_path(c) or not pending(c):return False
 root=c.path.parent/'previews';root.mkdir(parents=True,exist_ok=True)
 with (root/'render.log').open('a') as log:
  subprocess.Popen([sys.executable,'-m','scanatlas.local_previews','--database',str(c.path)],stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
 return True


def render_asset(c,a,blender):
 d=a['detail'];root=c.path.parent/'previews'/'mixamo';root.mkdir(parents=True,exist_ok=True)
 job={'local_file':d['local_file'],'character_id':d.get('character_id')}
 if not Path(job['local_file']).is_file():raise ValueError('Local FBX is missing')
 if d.get('character_id'):
  character=c.get(d['character_id'])
  if not character or not Path(character['detail'].get('local_file','')).is_file():raise ValueError('Linked character FBX is missing')
  job['character_file']=character['detail']['local_file']
 with tempfile.TemporaryDirectory(prefix='.render-',dir=root) as temp:
  folder=Path(temp);job['output']=str(folder);(folder/'job.json').write_text(json.dumps(job))
  log=root/(a['id']+'.log')
  with log.open('w') as stream:
   proc=subprocess.run([blender,'--background','--factory-startup','--threads','6','--python-exit-code','1','--python',str(Path(__file__).parent/'assets/render_fbx.py'),'--',str(folder/'job.json')],stdout=stream,stderr=subprocess.STDOUT,timeout=240)
  if proc.returncode:raise ValueError('Blender preview failed; see '+str(log))
  report=json.loads((folder/'report.json').read_text());paths=[]
  from PySide6.QtGui import QImage
  for i,source in enumerate(report['paths']):
   image=QImage(source)
   if image.isNull():raise ValueError('Renderer produced an invalid image')
   dest=root/(a['id']+'-'+str(i)+'.png');os.replace(source,dest);paths.append(str(dest))
  # Re-read to preserve metadata changed by other agents during rendering.
  current=c.get(a['id'])
  if current['preview']:return {'id':a['id'],'status':'already_supplied'}
  if current['detail']['sha256']!=d['sha256']:raise ValueError('Asset changed while rendering')
  current['preview']=paths[len(paths)//2];current['detail'].update(preview_status='local_render',gallery=paths,preview_render={k:v for k,v in report.items() if k!='paths'})
  if a['kind']=='Animations':current['detail'].update(frame_rate=report['frame_rate'],duration_seconds=report['duration_seconds'])
  current['detail'].pop('preview_error',None);c.upsert(current);c.c.commit()
  return {'id':a['id'],'status':'complete','preview':current['preview']}


def run(c,ids=None,retry=False):
 blender=blender_path(c)
 if not blender:return {'status':'unavailable','reason':'Blender is not installed or configured','asset_files_downloaded':False}
 lockpath=c.path.parent/'previews'/'render.lock';lockpath.parent.mkdir(parents=True,exist_ok=True)
 results=[]
 with lockpath.open('a') as lock:
  try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:return {'status':'already_running'}
  attempted=set()
  while True:
   candidates=[a for a in pending(c,retry) if a['id'] not in attempted and (not ids or a['id'] in ids)]
   if not candidates:break
   a=candidates[0];attempted.add(a['id'])
   try:result=render_asset(c,a,blender)
   except Exception as ex:
    result={'id':a['id'],'status':'failed','error':str(ex)}
    latest=c.get(a['id'])
    if latest and not latest['preview']:
     latest['detail'].update(preview_status='failed',preview_error=str(ex));c.upsert(latest);c.c.commit()
   results.append(result)
 return {'status':'complete','items':results,'asset_files_downloaded':False}

if __name__=='__main__':
 import argparse
 parser=argparse.ArgumentParser();parser.add_argument('--database',required=True);args=parser.parse_args()
 c=Catalog(args.database)
 try:print(json.dumps(run(c)),flush=True)
 finally:c.close()
