"""Web-rendered catalog, using the existing native catalog/download backend."""
import json
from pathlib import Path
from PySide6.QtCore import QObject,Slot,Signal,QUrl,QTimer,QThreadPool
from PySide6.QtWidgets import QMainWindow,QApplication,QInputDialog,QFileDialog
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEnginePage,QWebEngineProfile,QWebEngineSettings
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtGui import QDesktopServices
from .catalog import Catalog
from .app import Window,Job
from .agent import describe
from .public_sources import hydrate

def category_tiles(c,request,facets):
 """Small, read-only browse overview using the catalog's real taxonomy."""
 if any(request.get(key) for key in ('query','source','scope','collection','subtype','offset')):return []
 kinds=list(dict.fromkeys(request.get('types') or []))
 if len(kinds)>1:return []
 groups={}
 for kind,subtype,count in facets:
  if kinds:
   if kind!=kinds[0] or not subtype or not subtype.strip():continue
   key=(kind,subtype)
  else:
   if not kind:continue
   key=(kind,'')
  groups[key]=groups.get(key,0)+count
 # A single generic bucket adds a navigation step without narrowing anything.
 if kinds and len(groups)<=1:return []
 tiles=[]
 for (kind,subtype),count in sorted(groups.items(),key=lambda item:(-item[1],item[0])):
  where=c.source_clause()+" AND kind=? AND trim(coalesce(preview,''))<>''";params=[kind]
  if subtype:where+=' AND subtype=?';params.append(subtype)
  row=c.c.execute("SELECT id,preview FROM assets WHERE "+where+" ORDER BY CASE WHEN local_path<>'' AND coalesce(json_extract(detail,'$.catalog_only'),0)=0 THEN 0 WHEN json_extract(detail,'$.source') IN ('polyhaven','ambientcg') THEN 1 WHEN coalesce(json_extract(detail,'$.catalog_only'),0)=0 THEN 2 ELSE 3 END,name COLLATE NOCASE,id LIMIT 1",params).fetchone()
  if not row:continue
  tiles.append({'kind':kind,'subtype':subtype,'label':subtype or ('3D Models' if kind=='3D Assets' else kind),'count':count,'id':row['id'],'preview':row['preview']})
  if len(tiles)==12:break
 return tiles

class Bridge(QObject):
 result=Signal(str)
 def __init__(self,window):super().__init__(window);self.w=window
 def send(self,action,**values):self.result.emit(json.dumps({'action':action,**values},ensure_ascii=False))
 @Slot(str)
 def request(self,raw):
  try:
   r=json.loads(raw);action=r['action'];c=self.w.native.catalog
   if action=='search':
    rows,total,_=c.query(r.get('query',''),kinds=r.get('types',[]),subtype=r.get('subtype',''),source=r.get('source',''),scope=r.get('scope',''),collection=r.get('collection'),limit=60,offset=max(0,int(r.get('offset',0))),sort=r.get('sort','Relevance'))
    facets=c.facets();tiles=category_tiles(c,r,facets)
    needed={row['id'] for row in rows}|{tile['id'] for tile in tiles}
    for job in self.w.preview_jobs:
     if job.asset_id not in needed:job.cancel.set()
    self.send(action,request=r.get('request'),items=rows,total=total,collections=c.collections(),facets=facets,browse_categories=tiles,sources=[dict(x) for x in c.c.execute("SELECT json_extract(detail,'$.source') source,count(*) count FROM assets WHERE "+c.source_clause()+" GROUP BY 1")])
   elif action=='preview':
    a=c.get(r['id'])
    if not a:raise ValueError('Unknown preview asset')
    variant='animated' if r.get('variant')=='animated' else 'static';key=a['id']+':'+variant
    if key in self.w.preview_pending:return
    self.w.preview_pending.add(key)
    from .preview_cache import resolve
    def fetch_preview(progress,cancel):
     if cancel():return {'id':a['id'],'variant':variant,'url':'','status':'cancelled'}
     path,status=resolve(a['detail'].get('animated_preview','') if variant=='animated' else a['preview'],root=c.path.parent/'previews',fetch=not self.w.offline)
     return {'id':a['id'],'variant':variant,'url':QUrl.fromLocalFile(str(path)).toString() if path else '', 'status':status}
    job=Job(fetch_preview);job.asset_id=a['id'];self.w.preview_jobs.add(job)
    def done_preview(result):
     self.w.preview_jobs.discard(job);self.w.preview_pending.discard(key);self.send('preview',**result)
    def failed_preview(error):
     self.w.preview_jobs.discard(job);self.w.preview_pending.discard(key);self.send('preview',id=a['id'],variant=variant,url='',status='failed',error=error)
    job.signals.done.connect(done_preview);job.signals.failed.connect(failed_preview);self.w.preview_pool.start(job)
   elif action=='inspect':
    a=c.get(r['id'])
    if not a:raise ValueError('Asset no longer available')
    self.w.native.current=a;self.send(action,asset=describe(c,a,True))
    if a['detail'].get('manifest_pending') and not self.w.offline:
     def fetch(progress,cancel):
      db=Catalog(c.path)
      try:return hydrate(db,a)
      finally:db.close()
     job=Job(fetch);self.w.metadata_jobs.add(job)
     def done(asset):
      self.w.metadata_jobs.discard(job)
      if self.w.native.current and self.w.native.current['id']==asset['id']:self.w.native.current=asset;self.send('inspect',asset=describe(c,asset,True))
     def fail(error):self.w.metadata_jobs.discard(job);self.send('metadata_error',id=a['id'],message=error)
     job.signals.done.connect(done);job.signals.failed.connect(fail);self.w.native.pool.start(job)
   elif action=='save_collection':
    name,ok=QInputDialog.getText(self.w,'Save search','Collection name')
    if ok and name.strip():c.collection(name.strip(),json.dumps({'text':r.get('query',''),'kinds':r.get('types',[]),'subtype':r.get('subtype',''),'source':r.get('source','')}));self.send('collection_saved')
   elif action=='favorite':self.send(action,id=r['id'],favorite=c.favorite(r['id']))
   elif action=='download':
    a=c.get(r['id'])
    if not a:raise ValueError('Unknown asset')
    if a['detail'].get('catalog_only'):
     self.w.export_mixamo(a);return
    self.w.native.current=a;self.w.native.quality.setCurrentText(r.get('quality','Medium'));self.w.native.download()
   elif action=='source':self.w.native.current=c.get(r['id']);self.w.native.open_quixel()
   elif action=='folder':self.w.native.current=c.get(r['id']);self.w.native.open_local()
   elif action=='mixamo':self.w.native.open_mixamo()
   elif action=='sources':self.w.native.show_sources()
   elif action=='sync':self.w.native.sync_public()
   elif action=='sync_mixamo':self.w.sync_mixamo()
   elif action=='import':self.w.native.import_menu()
   elif action=='unity_configure':self.w.configure_unity()
   elif action=='unity_context':self.w.unity_context(r.get('id'),r.get('quality','Medium'))
   elif action=='unity_import':self.w.import_unity(r['id'],r.get('quality','Medium'))
   elif action=='unity_folder':
    from .unity_import import job_status
    job=job_status(c,r['job'])['jobs'][0]
    root=Path(job['project']).resolve();folder=(root/job['asset_folder']).resolve()
    if not folder.is_relative_to(root/'Assets'/'Atlas') or not folder.is_dir():raise ValueError('Imported asset folder is unavailable')
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
   else:raise ValueError('Unknown catalog action')
  except Exception as ex:self.send('error',message=str(ex))

class WebCatalogWindow(QMainWindow):
 def __init__(self,catalog=None,offline=False):
  super().__init__();self.native=Window(catalog);self.native.images.online=False;self.native.image_timer.stop();self.metadata_jobs=set();self.preview_jobs=set();self.preview_pending=set();self.offline=offline;self.preview_pool=QThreadPool(self);self.preview_pool.setMaxThreadCount(4)
  self.setWindowTitle('Atlas 0.6.2 — Asset Library');self.setWindowIcon(self.native.windowIcon());self.resize(1600,1000);self.setMinimumSize(1100,720)
  self.view=QWebEngineView();self.setCentralWidget(self.view)
  self.profile=QWebEngineProfile(self);self.profile.setHttpCacheType(QWebEngineProfile.MemoryHttpCache)
  self.page=QWebEnginePage(self.profile,self.view);self.view.setPage(self.page)
  self.page.settings().setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls,True)
  self.channel=QWebChannel(self.page);self.bridge=Bridge(self);self.channel.registerObject('atlas',self.bridge);self.page.setWebChannel(self.channel)
  self.data_version=self.native.catalog.c.execute('PRAGMA data_version').fetchone()[0]
  from .local_previews import launch
  launch(self.native.catalog)
  self.view.setUrl(QUrl.fromLocalFile(str(Path(__file__).parent/'assets/web/catalog.html')))
  self.timer=QTimer(self);self.timer.setInterval(2000);self.timer.timeout.connect(self.report_status);self.timer.start();QApplication.instance().aboutToQuit.connect(self.timer.stop)
 def configure_unity(self):
  if self.native.busy:return False
  from .unity_import import configure
  c=self.native.catalog
  project=QFileDialog.getExistingDirectory(self,'Connect Unity project — select the folder containing Assets and ProjectSettings',c.setting('unity_project','') or str(Path.home()/'Unity'))
  if not project:return False
  configure(c,project);self.unity_context();self.bridge.send('notice',message='Unity project connected. Imports finish automatically while this project is open in Unity.');return True
 def unity_context(self,ident=None,quality='Medium'):
  from .unity_import import project_info,available_local,job_status
  c=self.native.catalog;project=project_info(c);a=c.get(ident) if ident else None
  jobs=job_status(c,project=project['project']).get('jobs',[]) if project.get('valid') else []
  jobs=[j for j in jobs if a and j.get('asset_id')==a['id'] and (a['detail'].get('source')=='mixamo' or j.get('quality')==quality)]
  self.bridge.send('unity_context',id=ident,quality=quality,project=project,local=available_local(c,a,quality) if a else {},job=jobs[0] if jobs else None)
 def import_unity(self,ident,quality):
  if self.native.busy:return
  from .unity_import import project_info,submit
  project=project_info(self.native.catalog,refresh=True)
  if not project.get('valid'):
   if not self.configure_unity():return
   project=project_info(self.native.catalog,refresh=True)
  if not project.get('valid'):
   self.bridge.send('error',message=project.get('note','Choose a Unity project before importing.'));return
  target_project=project['project']
  editor_open=project.get('source')=='open'
  self.native.task_started('Preparing Unity import…')
  def work(progress,cancel):
   c=Catalog(self.native.catalog.path)
   try:
    if cancel():raise InterruptedError('Import cancelled')
    def preparing(done,total,stage):
     if cancel():raise InterruptedError('Import cancelled')
     progress((done or 0,total or 0,stage))
    return submit(c,ident,project=target_project,quality=quality,execute=True,progress=preparing,
                  editor_open=editor_open)
   finally:c.close()
  def done(result):
   self.native.task_finished();self.unity_context(ident,quality);self.bridge.send('notice',message='Import queued. Unity will create materials and prefabs automatically when this project is open.')
  self.native.run_job(work,done)
 def sync_mixamo(self):
  if self.native.busy:return
  self.native.task_started('Refreshing Mixamo catalog metadata…')
  def work(progress,cancel):
   from .mixamo_catalog import sync
   c=Catalog(self.native.catalog.path)
   try:return sync(c,lambda n,kind,page,total:progress((n,0,'Indexing Mixamo')))
   finally:c.close()
  def done(result):
   self.native.task_finished();self.bridge.send('catalog_changed');self.bridge.send('notice',message=f"Indexed {result['indexed_assets']:,} Mixamo entries. No FBXs downloaded.")
  self.native.run_job(work,done)
 def export_mixamo(self,a):
  if self.native.busy:return
  character=None
  if a['kind']=='Animations':
   candidates=[self.native.catalog.get(x['id']) for x in self.native.catalog.query(kind='Characters',source='mixamo',scope='downloaded',limit=1000)[0]]
   candidates=[x for x in candidates if x['detail'].get('catalog_id')]
   labels=['Current Mixamo character (no local rig link)']+[x['name']+' · '+x['id'][-8:] for x in candidates]
   label,ok=QInputDialog.getItem(self,'Animation character','Export this motion on:',labels,0,False)
   if not ok:return
   index=labels.index(label);character=candidates[index-1]['id'] if index else None
  folder=QFileDialog.getExistingDirectory(self,'Save Mixamo FBX')
  if not folder:return
  self.native.task_started('Preparing Mixamo export…')
  def work(progress,cancel):
   import time
   from .mixamo_catalog import export
   from .mixamo_bridge import call
   c=Catalog(self.native.catalog.path)
   try:
    result=export(c,a,folder,character,True);job_id=result['job_id']
    while True:
     status=call(c.path,'status');job=status.get('jobs',{}).get(job_id,{})
     if job.get('status')=='complete':return job
     if job.get('status')=='failed':raise ValueError(job.get('error','Mixamo export failed'))
     progress((job.get('bytes_done',0),max(0,job.get('bytes_total',0)),'Mixamo export'))
     if cancel():return {'status':'background','job_id':job_id}
     time.sleep(1)
   finally:c.close()
  def done(job):
   self.native.task_finished();self.bridge.send('catalog_changed');self.bridge.send('asset_downloaded',id=job.get('asset_id'));self.bridge.send('notice',message='Mixamo FBX saved and indexed.' if job['status']=='complete' else 'Export continues in the background. Check Mixamo status.')
  self.native.active_download=self.native.run_job(work,done)
 def report_status(self):
  version=self.native.catalog.c.execute('PRAGMA data_version').fetchone()[0]
  if version!=self.data_version:
   self.data_version=version;self.bridge.send('catalog_changed')
   from .local_previews import launch
   launch(self.native.catalog)
  activity=None
  if self.native.busy:
   metrics=getattr(self.native,'task_metrics',{})
   total=metrics.get('total') or 0;done=metrics.get('done') or 0
   activity={'label':'Downloading' if self.native.active_download else 'Preparing',
             'percent':round(min(100,max(0,done*100/total)),1) if total else None,
             'detail':self.native.status.text(),'estimated':False}
   if not self.native.active_download and metrics.get('stage'):activity['detail']=metrics['stage']
  self.bridge.send('status',text=self.native.status.text(),busy=self.native.busy,count=self.native.catalog.count(),activity=activity)
 def closeEvent(self,event):
  if self.native.jobs or self.metadata_jobs:event.ignore();return
  from .mixamo_browser import dispose_browser
  self.timer.stop();self.preview_pool.clear();self.preview_pool.waitForDone();self.native.close();dispose_browser(self);super().closeEvent(event)
