"""Dedicated user-driven Mixamo browser. Credentials stay in Adobe's page."""
from pathlib import Path
from PySide6.QtCore import QUrl,QCoreApplication,QEvent
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLabel,QComboBox,QPushButton,QFileDialog,QMessageBox)
from PySide6.QtGui import QDesktopServices
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEngineProfile,QWebEnginePage,QWebEngineDownloadRequest
from .catalog import DATA
from .mixamo import import_fbx,GUIDE

def dispose_browser(owner):
 if getattr(owner,'disposed',False):return
 owner.disposed=True
 for popup in getattr(owner,'auth_popups',[]):
  for view in popup.findChildren(QWebEngineView):
   page=view.page();view.stop();view.setPage(None);page.deleteLater();QCoreApplication.sendPostedEvents(page,QEvent.DeferredDelete)
  popup.hide()
 owner.view.stop();owner.view.setPage(None);page=owner.page;page.deleteLater();QCoreApplication.sendPostedEvents(page,QEvent.DeferredDelete)
 owner.profile.deleteLater();QCoreApplication.sendPostedEvents(owner.profile,QEvent.DeferredDelete)

class AuthPage(QWebEnginePage):
 def __init__(self,profile,parent,owner):super().__init__(profile,parent);self.owner=owner
 def createWindow(self,kind):
  dialog=QDialog(self.owner);dialog.setWindowTitle('Adobe sign-in');dialog.resize(650,800)
  layout=QVBoxLayout(dialog);view=QWebEngineView(dialog);page=AuthPage(self.profile(),view,self.owner);view.setPage(page);layout.addWidget(view)
  page.windowCloseRequested.connect(dialog.close);self.owner.auth_popups.append(dialog);dialog.show();return page

class MixamoBrowser(QDialog):
 def __init__(self,parent,catalog,on_import=lambda:None,start_url=None):
  super().__init__(parent);self.catalog=catalog;self.on_import=on_import;self.jobs={};self.agent_jobs={};self.agent_pending=None;self.auth_popups=[]
  self.setWindowTitle('Atlas · Mixamo — Adobe sign-in');self.resize(1250,850)
  layout=QVBoxLayout(self)
  notice=QLabel('Background Mixamo session · Sign in directly on Adobe’s website. Atlas never reads your password. Choose your export role below before downloading.\nMixamo exports original FBXs; the Medium texture filter does not apply. Unity must validate rigs and playback.');notice.setWordWrap(True);layout.addWidget(notice)
  bar=QHBoxLayout();bar.addWidget(QLabel('Import downloads as:'));self.role=QComboBox();self.role.addItems(['Characters','Animations']);bar.addWidget(self.role)
  self.characters=QComboBox();self.characters.addItem('Character not linked',None)
  for a in catalog.query(kind='Characters',limit=10000)[0]:self.characters.addItem(a['name'],a['id'])
  bar.addWidget(self.characters)
  reload=QPushButton('Reload');bar.addWidget(reload)
  external=QPushButton('Open in system browser');external.clicked.connect(lambda:QDesktopServices.openUrl(QUrl(GUIDE['url'])));bar.addWidget(external)
  layout.addLayout(bar);self.address=QLabel('https://www.mixamo.com/');self.address.setWordWrap(True);layout.addWidget(self.address)
  # Off-the-record profile: no passwords, cookies or account tokens persisted.
  self.profile=QWebEngineProfile(self)
  self.profile.setHttpCacheType(QWebEngineProfile.MemoryHttpCache)
  self.view=QWebEngineView();self.page=AuthPage(self.profile,self.view,self);self.view.setPage(self.page);layout.addWidget(self.view,1)
  self.view.urlChanged.connect(lambda url:self.address.setText(url.scheme()+'://'+url.host()+url.path()))
  self.view.loadFinished.connect(lambda ok:self.status.setText('Browser ready. Sign in and select an export.' if ok else 'Page failed to load. Try Open in system browser, then Import Mixamo FBX in Atlas.'))
  reload.clicked.connect(self.view.reload);self.profile.downloadRequested.connect(self.download)
  self.status=QLabel('Loading Mixamo…');self.status.setWordWrap(True);layout.addWidget(self.status)
  from .mixamo_bridge import MixamoBridge
  self.agent_bridge=MixamoBridge(self)
  layout.addWidget(QLabel('Agent commands: atlas mixamo status / search / select / download. Close hides this panel; The background service keeps the session alive even when the Atlas catalog is closed.'))
  self.view.setUrl(QUrl(start_url or GUIDE['url']))
 def download(self,request):
  name=Path(request.downloadFileName()).name
  if Path(name).suffix.lower()!='.fbx':
   self.status.setText('Choose FBX for Unity in Mixamo. This panel only imports FBX downloads.');request.cancel();return
  pending=self.agent_pending
  folder=pending['destination'] if pending else QFileDialog.getExistingDirectory(self,'Save Mixamo FBX',str(Path.home()/'Downloads'))
  if not folder:request.cancel();return
  if pending:name=pending['job_id'][:8]+'_'+name
  path=Path(folder)/name
  if path.exists():
   self.status.setText('File already exists. Select a different destination or export name.');request.cancel();return
  role=pending['role'] if pending else self.role.currentText();character=pending.get('character') if pending else self.characters.currentData() if role=='Animations' else None
  job_id=pending['job_id'] if pending else None
  if pending:self.agent_pending=None;self.agent_jobs[job_id].update(status='downloading',path=str(path),bytes_done=0,bytes_total=request.totalBytes())
  request.setDownloadDirectory(folder);request.setDownloadFileName(name)
  self.jobs[request.id()]=(request,path,role,character,job_id)
  if job_id:request.receivedBytesChanged.connect(lambda:self.agent_jobs[job_id].update(bytes_done=request.receivedBytes(),bytes_total=request.totalBytes()))
  request.receivedBytesChanged.connect(lambda:self.status.setText(f'{name}: {request.receivedBytes():,} / {request.totalBytes():,} bytes'))
  request.isFinishedChanged.connect(lambda:self.finished(request));request.accept()
 def finished(self,request):
  if not request.isFinished():return
  item=self.jobs.pop(request.id(),None)
  if not item:return
  _,path,role,character,job_id=item
  if request.state()!=QWebEngineDownloadRequest.DownloadCompleted:
   if job_id:self.agent_jobs[job_id].update(status='failed',error=request.interruptReasonString())
   self.status.setText('Download failed/cancelled: '+request.interruptReasonString());return
  try:
   a=import_fbx(self.catalog,path,role,character,name=self.agent_jobs[job_id]['plan'].get('selection') if job_id else None);self.status.setText('Available to Atlas agents: '+a['name']+' · '+a['id']);self.on_import()
   if job_id:self.agent_jobs[job_id].update(status='complete',asset_id=a['id'],path=str(path),bytes_done=path.stat().st_size)
   if role=='Characters':self.characters.addItem(a['name'],a['id']);self.characters.setCurrentIndex(self.characters.count()-1)
  except Exception as ex:
   if job_id:self.agent_jobs[job_id].update(status='failed',error=str(ex))
   self.status.setText('Saved file, but catalog import failed: '+str(ex))
 def shutdown(self):
  self.agent_bridge.server.close();dispose_browser(self);self.hide()
 def closeEvent(self,event):
  # Downloads and IPC continue in the independent service after this view hides.
  self.hide();event.ignore()

class SourceBrowser(QDialog):
 """Normal browser rendering for archive listings, no automatic archive downloads."""
 def __init__(self,parent,url):
  super().__init__(parent);self.setWindowTitle('Atlas · Archive source browser');self.resize(1200,850)
  layout=QVBoxLayout(self);notice=QLabel('Archive listing · access and per-asset files unverified. This viewer does not start archive downloads.');notice.setWordWrap(True);layout.addWidget(notice)
  self.profile=QWebEngineProfile(self);self.view=QWebEngineView();self.page=QWebEnginePage(self.profile,self.view);self.view.setPage(self.page);layout.addWidget(self.view)
  self.profile.downloadRequested.connect(lambda request:(request.cancel(),notice.setText('Archive download stopped. Atlas needs a verified per-asset manifest before integration.')))
  self.view.setUrl(QUrl(url))
 def closeEvent(self,event):
  dispose_browser(self);super().closeEvent(event)
