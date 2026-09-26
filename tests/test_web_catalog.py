import os,time,json
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
os.environ.setdefault('QTWEBENGINE_CHROMIUM_FLAGS','--disable-gpu')
from PySide6.QtWidgets import QApplication
from scanatlas.catalog import Catalog
from scanatlas.web_catalog import WebCatalogWindow
from test_catalog import asset
from PySide6.QtGui import QImage,QColor
from scanatlas.mixamo import import_fbx

def test_web_layout_and_catalog_bridge(tmp_path):
 app=QApplication.instance() or QApplication([]);c=Catalog(tmp_path/'db')
 for n in range(25):
  a=asset(str(n),'Grass '+str(n));c.upsert(a)
 c.c.commit();w=WebCatalogWindow(c);w.show();results=[]
 deadline=time.monotonic()+12
 script="JSON.stringify({cards:document.querySelectorAll('.card').length,cardheight:document.querySelector('.card')?.getBoundingClientRect().height,downloadBottom:document.getElementById('download')?.getBoundingClientRect().bottom,footerBottom:document.querySelector('.foot')?.getBoundingClientRect().bottom,height:innerHeight})"
 while time.monotonic()<deadline:
  app.processEvents()
  w.page.runJavaScript(script,lambda x:results.append(json.loads(x)) if x else None)
  if results and results[-1].get('cards')==25 and results[-1].get('downloadBottom'):break
  time.sleep(.05)
 r=results[-1];assert r['cards']==25 and r['cardheight']>=230
 assert r['downloadBottom']<=r['height'] and r['footerBottom']<=r['height']
 w.timer.stop();w.close();app.processEvents()

def test_my_assets_filter_and_local_preview(tmp_path):
 app=QApplication.instance() or QApplication([]);c=Catalog(tmp_path/'db')
 c.upsert(asset('ordinary','Ordinary asset'));c.c.commit()
 fbx=tmp_path/'Arms.fbx';fbx.write_bytes(b'; FBX\nFBXHeaderExtension: {}')
 image=QImage(128,128,QImage.Format_RGB32);image.fill(QColor('#789abc'));image.save(str(tmp_path/'preview.png'))
 import_fbx(c,fbx,'Characters',name='Military FPS Arms',preview=tmp_path/'preview.png',my_asset=True,bundle=tmp_path)
 w=WebCatalogWindow(c);w.show();results=[];deadline=time.monotonic()+12;requested=False
 while time.monotonic()<deadline:
  app.processEvents()
  w.page.runJavaScript("JSON.stringify({ready:!!api,cards:document.querySelectorAll('.card').length,title:document.getElementById('title')?.textContent,pixels:document.querySelector('.card img')?.naturalWidth})",lambda x:results.append(json.loads(x)) if x else None)
  if results and results[-1].get('ready') and not requested:w.page.runJavaScript("scope('my-assets')");requested=True
  if results and results[-1].get('title')=='My assets' and results[-1].get('pixels')==128:break
  time.sleep(.05)
 assert results[-1]['title']=='My assets'
 assert results[-1]['cards']==1 and results[-1]['pixels']==128
 w.timer.stop();w.close();app.processEvents()

def test_web_reuses_cached_public_preview_offline(tmp_path,monkeypatch):
 from scanatlas.preview_cache import cache_path
 app=QApplication.instance() or QApplication([]);c=Catalog(tmp_path/'db')
 a=asset('cached','Cached rifle');a['preview']='https://cdn.polyhaven.com/cached.png';a['tiny']='';c.upsert(a);c.c.commit()
 image=QImage(128,128,QImage.Format_RGB32);image.fill(QColor('#789abc'))
 path=cache_path(a['preview'],tmp_path/'previews');path.parent.mkdir();image.save(str(path),'PNG')
 def fail(*args,**kwargs):raise AssertionError('Offline catalog must not fetch')
 monkeypatch.setattr('scanatlas.preview_cache.requests.get',fail)
 w=WebCatalogWindow(c,offline=True);w.show();results=[];deadline=time.monotonic()+12
 while time.monotonic()<deadline:
  app.processEvents()
  w.page.runJavaScript("JSON.stringify({card:document.querySelector('.card img')?.naturalWidth,hero:document.querySelector('.hero img')?.naturalWidth})",lambda x:results.append(json.loads(x)) if x else None)
  if results and results[-1].get('card')==128 and results[-1].get('hero')==128:break
  time.sleep(.05)
 assert results[-1]=={'card':128,'hero':128}
 w.close();app.processEvents()

def test_remote_mixamo_card_and_export_options(tmp_path):
 from scanatlas.mixamo_catalog import record
 from test_mixamo_catalog import product
 from scanatlas.preview_cache import cache_path
 app=QApplication.instance() or QApplication([]);c=Catalog(tmp_path/'db')
 a=record(product(),'today');c.upsert(a);c.c.commit()
 image=QImage(128,128,QImage.Format_RGB32);image.fill(QColor('#789abc'))
 path=cache_path(a['preview'],tmp_path/'previews');path.parent.mkdir();image.save(str(path),'PNG')
 w=WebCatalogWindow(c,offline=True);w.show();results=[];deadline=time.monotonic()+12
 while time.monotonic()<deadline:
  app.processEvents()
  w.page.runJavaScript("JSON.stringify({label:document.querySelector('.entry-status')?.textContent,pixels:document.querySelector('.card img')?.naturalWidth,button:document.getElementById('download')?.textContent,disabled:document.getElementById('download')?.disabled,size:document.getElementById('size')?.textContent})",lambda x:results.append(json.loads(x)) if x else None)
  if results and results[-1].get('pixels')==128:break
  time.sleep(.05)
 assert results[-1]=={'label':'Online catalog','pixels':128,'button':'Export FBX…','disabled':False,'size':'Known after export'}
 w.close();app.processEvents()

def test_sidebar_browses_full_category_and_pages_while_top_filters_keep_search(tmp_path):
 app=QApplication.instance() or QApplication([]);c=Catalog(tmp_path/'db')
 for n in range(130):
  a=asset(str(n),('Grass ' if n<41 else 'Stone ')+str(n).zfill(3),kind='Surfaces',subtype='Material');c.upsert(a)
 c.upsert(asset('model','Grass model',kind='3D Assets',subtype='Model'));c.c.commit()
 w=WebCatalogWindow(c,offline=True);w.show()
 def read(script):
  answers=[];w.page.runJavaScript('JSON.stringify('+script+')',lambda x:answers.append(json.loads(x)) if x else None)
  end=time.monotonic()+3
  while not answers and time.monotonic()<end:app.processEvents();time.sleep(.01)
  return answers[-1] if answers else {}
 def until(predicate):
  end=time.monotonic()+6
  while time.monotonic()<end:
   r=read("({ready:!!api,total:total,cards:[...document.querySelectorAll('.card')].map(x=>x.dataset.id),query:state.query,types:state.types,offset:state.offset,nextDisabled:$('next').disabled,page:$('pagination').textContent,scroll:$('grid').scrollTop,filters:$('activefilters').textContent})")
   if predicate(r):return r
   app.processEvents();time.sleep(.02)
  raise AssertionError(r)
 until(lambda r:r.get('total')==131)
 w.page.runJavaScript("state.query='grass';$('search').value='grass';type('Surfaces')")
 filtered=until(lambda r:r.get('total')==41)
 assert filtered['query']=='grass' and 'Search: grass' in filtered['filters']
 w.page.runJavaScript("document.querySelector('[data-kind=Surfaces]').click()")
 first=until(lambda r:r.get('total')==130 and r.get('query')=='')
 assert len(first['cards'])==60 and first['types']==['Surfaces']
 w.page.runJavaScript("$('grid').scrollTop=400;$('next').click()")
 second=until(lambda r:r.get('offset')==60 and r.get('cards')!=first['cards'])
 assert len(second['cards'])==60 and second['scroll']==0
 w.page.runJavaScript("$('next').click()")
 last=until(lambda r:r.get('offset')==120 and len(r.get('cards',[]))==10)
 assert last['nextDisabled'] and 'Page 3 of 3' in last['page']
 assert len(set(first['cards']+second['cards']+last['cards']))==130
 w.close();app.processEvents()

def test_failed_preview_can_be_retried_without_reopening(tmp_path,monkeypatch):
 app=QApplication.instance() or QApplication([]);c=Catalog(tmp_path/'db');a=asset('retry','Retry image');a['preview']='https://cdn.polyhaven.com/retry.png';c.upsert(a);c.c.commit()
 image=QImage(64,64,QImage.Format_RGB32);image.fill(QColor('#789abc'));path=tmp_path/'valid.png';image.save(str(path))
 attempts=[]
 def resolve(*args,**kwargs):
  attempts.append(1)
  if len(attempts)==1:raise ValueError('Temporary source error')
  return path,'cache'
 monkeypatch.setattr('scanatlas.preview_cache.resolve',resolve)
 w=WebCatalogWindow(c);w.show();deadline=time.monotonic()+8;clicked=False;loaded=False
 while time.monotonic()<deadline:
  app.processEvents();out=[]
  w.page.runJavaScript("JSON.stringify({retry:!!document.querySelector('.card .placeholder button'),pixels:document.querySelector('.card img')?.naturalWidth||0})",lambda x:out.append(json.loads(x)) if x else None)
  end=time.monotonic()+.2
  while not out and time.monotonic()<end:app.processEvents();time.sleep(.01)
  if out and out[-1]['retry'] and not clicked:w.page.runJavaScript("document.querySelector('.card .placeholder button').click()");clicked=True
  if out and out[-1]['pixels']==64:loaded=True;break
 assert clicked and loaded and len(attempts)==2
 w.close();app.processEvents()

def test_visual_category_navigation_and_closable_asset_inspector(tmp_path,monkeypatch):
 app=QApplication.instance() or QApplication([]);c=Catalog(tmp_path/'db')
 image=QImage(96,96,QImage.Format_RGB32);image.fill(QColor('#769c6d'));preview=tmp_path/'preview.png';image.save(str(preview))
 for ident,name,kind,subtype in [('grass1','Grass One','Surfaces','Grass'),('grass2','Grass Two','Surfaces','Grass'),('stone','Stone','Surfaces','Stone'),('model','Grass Model','3D Assets','Plant')]:
  a=asset(ident,name,kind=kind,subtype=subtype);a['preview']=str(preview)
  a['detail'].update(source='polyhaven',license='CC0',resolutions=[2048],files=[{'name':'color.jpg','type':'albedo','resolution':2048,'size':1048576,'mime':'image/jpeg','url':'https://dl.polyhaven.org/color.jpg','lod':None}])
  c.upsert(a)
 c.c.commit()
 def no_network(*args,**kwargs):raise AssertionError('Browse test must use local previews and metadata only')
 monkeypatch.setattr('scanatlas.preview_cache.requests.get',no_network)
 w=WebCatalogWindow(c,offline=True);w.show()
 def read(expression):
  values=[];w.page.runJavaScript('JSON.stringify('+expression+')',lambda result:values.append(json.loads(result)) if result else None)
  deadline=time.monotonic()+2
  while not values and time.monotonic()<deadline:app.processEvents();time.sleep(.01)
  return values[-1] if values else {}
 def until(predicate):
  deadline=time.monotonic()+8
  while time.monotonic()<deadline:
   result=read("({ready:typeof api!=='undefined'&&!!api,total:typeof total!=='undefined'?total:-1,types:typeof state!=='undefined'?state.types:[],subtype:typeof state!=='undefined'?state.subtype:'',query:typeof state!=='undefined'?state.query:'',tiles:[...document.querySelectorAll('.category-tile')].map(e=>({label:e.getAttribute('aria-label'),pixels:e.querySelector('img')?.naturalWidth||0})),open:!!document.querySelector('.layout.detail-open'),width:document.getElementById('grid')?.getBoundingClientRect().width,download:(()=>{let b=document.getElementById('download');if(!b)return null;let r=b.getBoundingClientRect();return {enabled:!b.disabled,top:r.top,bottom:r.bottom,visible:r.width>0&&document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)===b}})(),height:innerHeight})")
   if predicate(result):return result
   app.processEvents();time.sleep(.02)
  raise AssertionError(result)
 try:
  home=until(lambda r:r.get('total')==4 and len(r.get('tiles',[]))==2 and all(t['pixels']==96 for t in r['tiles']))
  assert not home['open']
  w.page.runJavaScript("document.querySelector('.category-tile[aria-label=\"Browse Surfaces, 3 assets\"]').click()")
  until(lambda r:r.get('total')==3 and r.get('types')==['Surfaces'] and len(r['tiles'])==2 and all(t['pixels']==96 for t in r['tiles']))
  w.page.runJavaScript("document.querySelector('.category-tile[aria-label=\"Browse Grass, 2 assets\"]').click()")
  grass=until(lambda r:r.get('total')==2 and r.get('subtype')=='Grass' and not r['tiles'])
  w.page.runJavaScript("document.querySelector('.card[data-id=grass1]').click()")
  opened=until(lambda r:r.get('open') and r.get('download',{}).get('visible'))
  assert opened['download']['enabled'] and 0<opened['download']['top']<opened['download']['bottom']<=opened['height']
  assert opened['width']<grass['width']
  w.page.runJavaScript("document.querySelector('[aria-label=\"Close asset details\"]').click()")
  closed=until(lambda r:not r.get('open') and r.get('width')==grass['width'])
  assert closed['width']>opened['width']
  w.page.runJavaScript("$('search').value='grass';$('search').dispatchEvent(new Event('input'))")
  until(lambda r:r.get('query')=='grass' and r.get('total')==2)
  w.page.runJavaScript("$('subtype').value='Stone';$('subtype').dispatchEvent(new Event('change'))")
  until(lambda r:r.get('query')=='grass' and r.get('subtype')=='Stone' and r.get('total')==0)
  w.page.runJavaScript("document.querySelector('[data-kind=Surfaces]').click()")
  until(lambda r:r.get('total')==3 and r.get('query')=='' and r.get('subtype')=='')
 finally:
  w.timer.stop();w.close();app.processEvents()

def test_unity_import_button_queues_local_asset_and_reads_editor_report(tmp_path,monkeypatch):
 from scanatlas import unity_import
 from PySide6.QtWidgets import QFileDialog
 app=QApplication.instance() or QApplication([]);c=Catalog(tmp_path/'db')
 a=asset('unity_surface','Unity Surface',kind='Surfaces',subtype='Stone');c.upsert(a);c.c.commit()
 project=tmp_path/'UnityProject';(project/'Assets').mkdir(parents=True);(project/'ProjectSettings').mkdir();(project/'ProjectSettings/ProjectVersion.txt').write_text('m_EditorVersion: 6000.6.2f1')
 monkeypatch.setattr(QFileDialog,'getExistingDirectory',lambda *args,**kwargs:str(project))
 w=WebCatalogWindow(c,offline=True);w.resize(1100,720);w.show()
 def read():
  out=[];w.page.runJavaScript("JSON.stringify({ready:!!$('unityimport'),disabled:$('unityimport')?.disabled,text:$('unityimport')?.textContent,note:$('unitynote')?.textContent,progress:$('unitypercent')?.textContent,stage:$('unitystage')?.textContent,downloadProgress:$('activitypercent')?.textContent,downloadVisible:!$('activity')?.hidden,indeterminate:!$('activitybar')?.hasAttribute('value'),bottom:$('unityimport')?.getBoundingClientRect().bottom,height:innerHeight})",lambda x:out.append(json.loads(x)) if x else None)
  end=time.monotonic()+2
  while not out and time.monotonic()<end:app.processEvents();time.sleep(.01)
  return out[-1] if out else {}
 def until(check):
  end=time.monotonic()+8
  while time.monotonic()<end:
   r=read()
   if check(r):return r
   app.processEvents();time.sleep(.03)
  raise AssertionError(r)
 until(lambda r:r.get('ready') and r.get('disabled'))
 folder=tmp_path/'download';folder.mkdir();im=QImage(8,8,QImage.Format_RGB32);im.fill(QColor('#789abc'));im.save(str(folder/'stone_Color.png'))
 (folder/'download.json').write_text(json.dumps({'id':a['id'],'quality':'Medium','files':['stone_Color.png']}));c.record_download(a['id'],'Medium',str(folder))
 w.page.runJavaScript("document.querySelector('.card').click();send('unity_context',{id:current.id,quality:'Medium'})")
 until(lambda r:r.get('disabled') is False)
 w.page.runJavaScript("$('unityimport').click()")
 queued=until(lambda r:r.get('text')=='Waiting for Unity…')
 assert queued['bottom']<=queued['height']
 jobs=unity_import.job_status(c)['jobs'];assert len(jobs)==1
 job=jobs[0];report=project/'AtlasImports/reports'/ (job['job_id']+'.json');report.parent.mkdir(exist_ok=True)
 report.write_text(json.dumps({'job_id':job['job_id'],'status':'processing','progress_percent':62,'progress_estimated':True,'stage':'Creating materials'}))
 processing=until(lambda r:r.get('progress')=='62% estimated')
 assert processing['stage']=='Creating materials' and processing['bottom']<=processing['height']
 w.native.task_started('Downloading textures');w.native.active_download=object();w.native.task_progress((37,100,'stone_Color.png'));w.report_status()
 downloading=until(lambda r:r.get('downloadVisible') and r.get('downloadProgress')=='37%')
 assert not downloading['indeterminate']
 w.native.task_progress((37,0,'stone_Color.png'));w.report_status()
 until(lambda r:r.get('downloadVisible') and r.get('indeterminate') and r.get('downloadProgress')=='Working…')
 w.native.task_finished();w.report_status()
 report.write_text(json.dumps({'job_id':job['job_id'],'status':'complete','prefabs':[],'materials':['Generated/Stone.mat'],'animations':[],'warnings':[]}))
 complete=until(lambda r:r.get('text')=='Imported to Unity ✓')
 assert complete['progress']=='100%'
 assert '1 materials' in complete['note'] and (folder/'stone_Color.png').is_file()
 w.close();app.processEvents()
