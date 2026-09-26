import os,json,time
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
os.environ.setdefault('QTWEBENGINE_CHROMIUM_FLAGS','--disable-gpu')
from concurrent.futures import ThreadPoolExecutor
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QUrl
from scanatlas.catalog import Catalog
from scanatlas.mixamo_browser import MixamoBrowser
from scanatlas.mixamo_bridge import call,session_evidence
from scanatlas.mcp_server import command

def wait(app,predicate,timeout=12):
 end=time.monotonic()+timeout
 while time.monotonic()<end:
  app.processEvents()
  if predicate():return
  time.sleep(.01)
 raise AssertionError('Timed out')

def test_browser_bridge_and_automatic_import(tmp_path):
 app=QApplication.instance() or QApplication([]);c=Catalog(tmp_path/'db')
 browser=MixamoBrowser(None,c,start_url='about:blank');browser.show();loaded=[]
 browser.view.loadFinished.connect(lambda ok:loaded.append(ok))
 html='''<html><body><div class="product-nav"><h2>Walking on Test Character</h2></div><div class="product-animation" onclick="this.classList.add('product-selected')"><div class="product-image"><img src="https://www.mixamo.com/motions/123/preview.png"></div><p class="text-capitalize">Walking</p></div><div class="sidebar-header"><button class="btn-primary" onclick="document.querySelector('.asset-download-modal').style.display='block'">Download</button></div><div class="asset-download-modal"><select><option value="fbx7_2019">FBX</option><option value="fbx7_unity">FBX for Unity</option></select><select><option value="true">With Skin</option><option value="false">Without Skin</option></select><div class="modal-footer"><button class="btn-primary" onclick="let a=document.createElement('a');a.href='data:application/octet-stream;base64,OyBGQlggNy40LjAKRkJYSGVhZGVyRXh0ZW5zaW9uOiB7fQ==';a.download='Walking.fbx';a.click()">Download</button></div></div></body></html>'''
 browser.view.setHtml(html,QUrl('https://www.mixamo.com/'));wait(app,lambda:len(loaded)>0)
 with ThreadPoolExecutor(1) as pool:
  def rpc(action,**kw):
   f=pool.submit(call,c.path,action,**kw);wait(app,f.done,timeout=30);return f.result()
  status=rpc('status');assert status['state']=='ready' and status['items'][0]['ref']=='motions:123'
  selected=rpc('select',ref='motions:123');assert selected['items'][0]['selected']
  dry=rpc('download',destination=str(tmp_path),type='Animations');assert dry['dry_run'];assert not list(tmp_path.glob('*.fbx'))
  result=rpc('download',destination=str(tmp_path),type='Animations',execute=True);job=result['job_id']
  wait(app,lambda:browser.agent_jobs[job]['status'] in ('complete','failed'),20)
  assert browser.agent_jobs[job]['status']=='complete',browser.agent_jobs[job]
  a=c.get(browser.agent_jobs[job]['asset_id']);assert a['kind']=='Animations' and a['detail']['source']=='mixamo'
  browser.close();assert not browser.isVisible();status=rpc('status');assert status['ui_hidden']
  assert status['last_successful_export']['asset_id']==a['id']
  assert 'authentication_verified' not in status
 browser.shutdown();browser.deleteLater();app.processEvents();c.close()

def test_mcp_defaults_and_no_shell():
 assert command('atlas_mixamo_download',{'destination':'/tmp/example;echo bad'})==['mixamo','download','--destination','/tmp/example;echo bad','--type','Animations']
 assert '--execute' not in command('atlas_mixamo_download',{'destination':'/tmp'})

def test_readiness_and_failed_export_do_not_claim_authentication():
 result=session_evidence({'state':'ready','authentication_verified':False,'jobs':{'failed':{'status':'failed','asset_id':'old'}}})
 assert result['authentication_check']=='not_performed'
 assert result['last_successful_export'] is None
