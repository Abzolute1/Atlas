"""Narrow local IPC to Atlas's Mixamo panel. No arbitrary JS, cookies or tokens."""
import json,os,socket,hashlib
from pathlib import Path
from urllib.parse import urlencode
from PySide6.QtCore import QObject,QTimer,QUrl
from PySide6.QtNetwork import QLocalServer

SNAPSHOT=r'''(()=>{
 if(location.hostname!=='www.mixamo.com'&&location.hostname!=='mixamo.com')return {state:'sign_in_required',items:[]};
 const cards=[...document.querySelectorAll('.product-animation,.product-character')];
 const items=cards.map((e,index)=>{let img=e.querySelector('.product-image img');let src=img?.src||'';let m=src.match(/\/(motions|characters)\/([^/]+)\//);return {ref:m?m[1]+':'+m[2]:'card:'+index,index,name:(e.querySelector('p.text-capitalize')?.textContent||e.querySelector('h3')?.textContent||'').trim(),preview_url:src,selected:e.classList.contains('product-selected')};});
 const modal=document.querySelector('.asset-download-modal');
 const controls=modal?[...modal.querySelectorAll('select')].map((e,index)=>({index,value:e.value,options:[...e.options].map(o=>({value:o.value,label:o.text}))})):[];
 const signedOut=[...document.querySelectorAll('a,button')].some(e=>/^(log in|sign up|sign in)$/i.test(e.textContent.trim())&&e.getClientRects().length);
 const download=!signedOut&&!!document.querySelector('.sidebar-header button.btn-primary');
 return {state:download?'ready':document.querySelector('input[type=password]')?'sign_in_required':'loading_or_signed_out',authentication_verified:false,readiness_evidence:download?'export_controls_visible':'none',items,selection:(document.querySelector('.product-nav h2')?.textContent||'').trim(),pagination:(document.querySelector('.search-description')?.textContent||'').trim(),download_dialog:!!modal,controls};
})()'''

def endpoint(database):
 root=Path(os.environ.get('XDG_RUNTIME_DIR',f'/tmp/atlas-runtime-{os.getuid()}'))/'atlas'
 root.mkdir(mode=0o700,parents=True,exist_ok=True)
 if root.is_symlink() or root.stat().st_uid!=os.getuid():raise ValueError('Unsafe Atlas runtime directory')
 root.chmod(0o700)
 return str(root/('mixamo-'+hashlib.sha256(str(Path(database).resolve()).encode()).hexdigest()[:12]+'.sock'))

def call(database,action,**args):
 from .mixamo_service import ensure
 ensure(database)
 path=endpoint(database)
 with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as sock:
  sock.settimeout(55)
  try:sock.connect(path)
  except (FileNotFoundError,ConnectionRefusedError):raise RuntimeError('Mixamo background service is unavailable; run atlas mixamo connect to sign in.') from None
  sock.sendall((json.dumps({'action':action,**args})+'\n').encode());data=b''
  while b'\n' not in data:
   chunk=sock.recv(65536)
   if not chunk:raise RuntimeError('Atlas closed the bridge connection')
   data+=chunk
   if len(data)>2*1024*1024:raise ValueError('Bridge response too large')
  result=json.loads(data.split(b'\n')[0])
  if result.get('error'):raise RuntimeError(result['error'])
  if action=='status' and result.get('jobs'):
   # A service kept alive through an upgrade may still run the old importer.
   # Queue saved FBX previews without restarting its signed-in session.
   from .catalog import Catalog
   from .local_previews import launch
   c=Catalog(database)
   try:
    from .mixamo_catalog import reconcile
    reconcile(c,result['jobs']);launch(c)
   finally:c.close()
  return session_evidence(result)

def session_evidence(result):
 # DOM readiness is not an authentication probe. Completed transfers are useful
 # evidence, but say nothing about whether the session has since expired.
 if 'authentication_verified' in result:
  result.pop('authentication_verified')
  result['authentication_check']='not_performed'
 if 'jobs' in result:
  completed=[(ident,job) for ident,job in result['jobs'].items() if job.get('status')=='complete' and job.get('asset_id')]
  result['last_successful_export']=None
  if completed:
   ident,job=completed[-1]
   result['last_successful_export']={'job_id':ident,'asset_id':job['asset_id'],'bytes':job.get('bytes_done'),'scope':'completed_export_in_this_service_session','current_authentication_guaranteed':False}
 return result

class MixamoBridge(QObject):
 def __init__(self,browser):
  super().__init__(browser);self.browser=browser;self.server=QLocalServer(self);self.server.setSocketOptions(QLocalServer.UserAccessOption);self.path=endpoint(browser.catalog.path);self.buffers={};self.busy=False
  # Never displace another running Atlas session.
  try:
   probe=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);probe.settimeout(.1);probe.connect(self.path);probe.close();self.available=False;return
  except (FileNotFoundError,ConnectionRefusedError):QLocalServer.removeServer(self.path)
  self.available=self.server.listen(self.path);self.server.newConnection.connect(self.connected)
 def connected(self):
  while self.server.hasPendingConnections():
   client=self.server.nextPendingConnection();self.buffers[client]=b'';client.readyRead.connect(lambda c=client:self.read(c));client.disconnected.connect(lambda c=client:self.buffers.pop(c,None))
 def reply(self,client,result):
  if client.state():client.write((json.dumps(result)+'\n').encode());client.flush();client.disconnectFromServer()
 def read(self,client):
  if client not in self.buffers:return
  self.buffers[client]+=bytes(client.readAll())
  if len(self.buffers[client])>65536:self.reply(client,{'error':'Request too large'});return
  if b'\n' not in self.buffers[client]:return
  raw,self.buffers[client]=self.buffers[client].split(b'\n',1)
  try:self.handle(client,json.loads(raw))
  except Exception as ex:self.reply(client,{'error':str(ex)})
 def js(self,code,callback):self.browser.page.runJavaScript(code,callback)
 def snap(self,callback):
  self.js('JSON.stringify('+SNAPSHOT+')',lambda raw:callback(json.loads(raw) if raw else {'state':'loading','items':[]}))
 def handle(self,c,r):
  action=r.get('action');b=self.browser
  if action=='connect':
   b.show();b.raise_();b.activateWindow();self.reply(c,{'status':'sign_in_window_open','session':'memory_only','instruction':'Sign in on Adobe’s page, then close the panel to keep it running in the background.'});return
  if action=='disconnect':
   from PySide6.QtWidgets import QApplication
   if b_pending(b):raise ValueError('Wait for pending downloads before disconnecting')
   self.reply(c,{'status':'disconnecting'});QTimer.singleShot(100,QApplication.instance().quit);return
  if action=='status':self.snap(lambda s:self.reply(c,{**s,'bridge_connected':True,'service_pid':os.getpid(),'session_storage':'memory_only','jobs':b.agent_jobs,'ui_hidden':not b.isVisible()}));return
  if action=='preview':
   path=Path(r['output']).expanduser().resolve()
   if path.exists():raise FileExistsError('Preview already exists')
   if path.suffix.lower()!='.png':raise ValueError('Use a PNG output filename')
   path.parent.mkdir(parents=True,exist_ok=True)
   self.snap(lambda s:self.capture(c,path,s));return
  if self.busy:raise RuntimeError('Mixamo is handling another command; retry after status')
  if action=='search':
   query=str(r.get('query',''))[:200];kind=r.get('type','Animations');page=int(r.get('page',1))
   if kind not in ('Characters','Animations') or not 1<=page<=10000:raise ValueError('Invalid type/page')
   params=urlencode({'page':page,'type':'Character' if kind=='Characters' else 'Motion,MotionPack','query':query})
   self.busy=True;b.view.setUrl(QUrl('https://www.mixamo.com/#/?'+params));self.poll(c,lambda s:bool(s.get('items')),tries=30);return
  if action=='select':
   ref=str(r['ref'])
   self.snap(lambda s:self.select(c,s,ref));return
  if action=='prepare_download':
   self.snap(lambda s:self.prepare(c,s));return
  if action=='download':
   destination=Path(r['destination']).expanduser().resolve();role=r.get('type','Animations');character=r.get('character')
   if role not in ('Characters','Animations') or not destination.is_dir():raise ValueError('Choose Characters/Animations and an existing destination folder')
   if character and (not b.catalog.get(character) or b.catalog.get(character)['kind']!='Characters'):raise ValueError('Unknown character ID')
   self.snap(lambda s:self.download(c,s,r,destination,role,character));return
  raise ValueError('Unknown Mixamo command')
 def capture(self,c,path,s):
  if s.get('state')!='ready':self.reply(c,{'error':'Sign in on Adobe’s page first. Login pages are not captured.'});return
  if not self.browser.view.grab().save(str(path),'PNG'):self.reply(c,{'error':'Could not render preview'});return
  self.reply(c,{'image_path':str(path),'selection':s.get('selection'),'items':s.get('items'),'asset_files_downloaded':False})
 def poll(self,c,predicate,tries):
  def check(s):
   if predicate(s) or tries<=0:
    self.busy=False;self.reply(c,{**s,'settled':bool(predicate(s))});return
   QTimer.singleShot(700,lambda:self.poll(c,predicate,tries-1))
  QTimer.singleShot(300,lambda:self.snap(check))
 def select(self,c,s,ref):
  if s.get('state')!='ready':self.reply(c,{'error':'Mixamo is not signed in/ready'});return
  matches=[x for x in s['items'] if x['ref']==ref]
  if len(matches)!=1:self.reply(c,{'error':'Reference not uniquely present; search again'});return
  index=matches[0]['index'];self.busy=True
  self.js(f"(()=>{{let e=document.querySelectorAll('.product-animation,.product-character')[{index}];if(e)e.click();}})()",lambda _:self.poll(c,lambda s:any(x['ref']==ref and x['selected'] for x in s.get('items',[])),30))
 def prepare(self,c,s):
  if s.get('state')!='ready':self.reply(c,{'error':'Sign in and select a character/animation first'});return
  if s.get('download_dialog'):self.reply(c,s);return
  self.busy=True;self.js("document.querySelector('.sidebar-header button.btn-primary')?.click()",lambda _:self.poll(c,lambda x:x.get('download_dialog'),15))
 def download(self,c,s,r,destination,role,character):
  if s.get('state')!='ready' or not s.get('download_dialog'):self.reply(c,{'error':'Run mixamo prepare-download first and inspect export options'});return
  controls=s.get('controls',[])
  if not controls or not any(x['value']=='fbx7_unity' for x in controls[0]['options']):self.reply(c,{'error':'FBX for Unity option unavailable; export manually'});return
  requested={0:'fbx7_unity'}
  if len(controls)>1 and any(x['value'] in ('true','false') for x in controls[1]['options']):requested[1]='true' if role=='Characters' else 'false'
  plan={'destination':str(destination),'type':role,'character_id':character,'selection':s.get('selection'),'size_bytes':None,'quality':'Original FBX','export_options':requested}
  if not r.get('execute'):self.reply(c,{'dry_run':True,'plan':plan});return
  if b_pending(self.browser):self.reply(c,{'error':'An agent export is already pending'});return
  import uuid,time
  job=uuid.uuid4().hex;self.browser.agent_pending={'job_id':job,'destination':str(destination),'role':role,'character':character,'created':time.time()};self.browser.agent_jobs[job]={'status':'preparing','plan':plan}
  settings=json.dumps(requested)
  code="(()=>{const values="+settings+";const els=document.querySelectorAll('.asset-download-modal select');for(const [i,v] of Object.entries(values)){let el=els[Number(i)];if(!el||![...el.options].some(o=>o.value===v))return false;el.value=v;el.dispatchEvent(new Event('change',{bubbles:true}));}return true})()"
  def configured(raw):
   if not raw:self.browser.agent_pending=None;self.browser.agent_jobs[job]['status']='failed';self.reply(c,{'error':'Export settings changed; retry'});return
   QTimer.singleShot(300,lambda:self.confirm(c,job,requested))
  self.js(code,configured)
 def confirm(self,c,job,requested):
  def verify(s):
   if any(str(s.get('controls',[{}]*4)[int(i)].get('value'))!=v for i,v in requested.items()):
    self.browser.agent_pending=None;self.browser.agent_jobs[job]['status']='failed';self.reply(c,{'error':'Could not confirm export settings'});return
   self.js("(()=>{let b=document.querySelector('.asset-download-modal .modal-footer button.btn-primary');if(!b||b.disabled)return false;b.click();return true})()",lambda ok:self.reply(c,{'job_id':job,'status':'preparing'} if ok else self.failed(job)))
   QTimer.singleShot(120000,lambda:self.expire(job))
  self.snap(verify)
 def failed(self,job):self.browser.agent_pending=None;self.browser.agent_jobs[job]['status']='failed';return {'error':'Download confirmation button unavailable'}
 def expire(self,job):
  if self.browser.agent_pending and self.browser.agent_pending['job_id']==job:self.browser.agent_pending=None;self.browser.agent_jobs[job].update(status='failed',error='Mixamo did not begin download within 120 seconds')

def b_pending(browser):return browser.agent_pending is not None or any(x.get('status')=='downloading' for x in browser.agent_jobs.values())
