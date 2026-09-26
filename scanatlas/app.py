from __future__ import annotations
import argparse
import base64
import hashlib
import html
import shutil
import json
import os
import sys
import threading
import time
from collections import OrderedDict
from pathlib import Path
from urllib.parse import quote, urlparse
from PySide6.QtCore import Qt, QSize, QRect, QEvent, QAbstractListModel, QModelIndex, QObject, Signal, QRunnable, QThreadPool, QTimer, QUrl
from PySide6.QtGui import QColor, QPainter, QPixmap, QFont, QIcon, QDesktopServices, QShortcut, QKeySequence
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
from PySide6.QtWidgets import (QGridLayout,QApplication,QMainWindow,QWidget,QHBoxLayout,QVBoxLayout,QLabel,QPushButton,QLineEdit,QTreeWidget,QTreeWidgetItem,QListView,QStyledItemDelegate,QStyle,QComboBox,QSplitter,QScrollArea,QFrame,QDialog,QDialogButtonBox,QFileDialog,QMessageBox,QInputDialog,QCheckBox,QProgressBar,QSlider,QMenu,QFormLayout,QHeaderView,QTextBrowser)
from .catalog import Catalog, DATA, TYPES
from .huggingface import HuggingFaceClient, sources
from .downloads import LEVELS, build_plan, QuixelClient
from .public_sources import PUBLIC, PublicClient, hydrate, sync_polyhaven, sync_ambientcg
from .mixamo import import_fbx, stage, GUIDE
from .metadata import import_archive, import_local

STYLE='''
* {font-family: "Inter", "DejaVu Sans", sans-serif; font-size:12px; color:#dce0e4;}
QMainWindow,QDialog {background:#0e161a;}
QWidget#sidebar,QWidget#inspector {background:#131e23;}
QWidget#topbar {background:#141f24; border-bottom:1px solid #2b3035;}
QWidget#center {background:#0e161a;}
QLabel {background:transparent;}
QLabel#muted {color:#8b949d;}
QLabel#eyebrow {color:#7f8b96; font-size:10px; font-weight:600; letter-spacing:0px;}
QLabel#title {font-size:22px;font-weight:600;color:#f0f3f5;}
QLabel#assettitle {font-size:19px;font-weight:600;color:#eef2f4;}
QLabel#brand {font-size:21px;font-weight:600;letter-spacing:0px;color:#f0f3f5;}
QLineEdit {background:#19272d;border:1px solid #343c43;border-radius:3px;padding:8px;selection-background-color:#276e64;}
QLineEdit:focus {border:1px solid #65cbb4;}
QPushButton {background:#1c2a31;border:1px solid #343b42;border-radius:3px;padding:7px 10px;}
QPushButton:hover {background:#303941;border-color:#61717c;}
QPushButton:pressed {background:#3a474f;}
QPushButton:disabled {color:#62707a;background:#22272b;border-color:#2a3035;}
QPushButton#primary {background:#29c9b1;color:#102b25;border:0;font-weight:700;padding:12px;}
QPushButton#primary:hover {background:#8ee5d1;}
QPushButton#primary:disabled {background:#344840;color:#7e9b91;}
QPushButton#typeFilter {background:#162229;border:1px solid #2d4048;border-radius:12px;padding:6px 8px;color:#9eabb5;text-align:left;}
QPushButton#typeFilter:checked {background:#193e3a;border-color:#2dcab1;color:#e0eee8;}
QPushButton#typeFilter:hover {border-color:#81938d;}
QPushButton#flat {background:transparent;border:0;color:#9eabb5;text-align:left;}
QPushButton#flat:checked {background:#1b3539;color:#e5f2f0;border-left:2px solid #29c9b1;}
QPushButton#flat:hover {background:#252e34;color:#e2e9ed;}
QTreeWidget {background:transparent;border:0;outline:0;font-size:12px;}
QTreeWidget::item {height:32px;border-radius:4px;padding-left:3px;}
QTreeWidget::item:selected {background:#263d37;color:#8ce0cb;}
QTreeWidget::item:hover:!selected {background:#232a2f;}
QTreeWidget::branch {background:transparent;}
QListView {background:transparent;border:0;outline:0;}
QComboBox {background:#1c2a31;border:1px solid #343b42;border-radius:3px;padding:7px 10px;min-width:95px;}
QComboBox QAbstractItemView {background:#1c2a31;selection-background-color:#31554c;}
QScrollArea,QTextBrowser {border:0;background:transparent;}
QScrollBar:vertical {background:#181c20;width:8px;margin:0;}
QScrollBar::handle:vertical {background:#3b454d;min-height:35px;border-radius:4px;}
QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical {height:0;}
QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical {background:none;}
QSplitter::handle {background:#2b3136;width:1px;}
QProgressBar {background:#23292e;border:0;border-radius:3px;text-align:center;height:16px;}
QProgressBar::chunk {background:#53b49e;border-radius:3px;}
QCheckBox {spacing:7px;color:#a8b5bf;}
QToolTip {background:#303940;border:1px solid #53616c;color:#eef3f7;padding:6px;}
QSlider::groove:horizontal {height:3px;background:#333f47;}
QSlider::handle:horizontal {width:11px;margin:-4px 0;background:#7ac6b4;border-radius:5px;}
QMenu {background:#242b30;border:1px solid #3b474f;}
QMenu::item {padding:8px 20px;}
QMenu::item:selected {background:#34584d;}
'''

def label(text='',name='',wrap=False):
 w=QLabel(text);w.setObjectName(name);w.setWordWrap(wrap);return w

def button(text,fn=None,name=''):
 b=QPushButton(text);b.setObjectName(name);b.setCursor(Qt.PointingHandCursor)
 if fn:b.clicked.connect(fn)
 return b

def ui_icon(name):
 return QIcon(str(Path(__file__).parent/'assets/icons'/f'{name}.svg'))

def separator():
 line=QFrame();line.setFixedHeight(1);line.setStyleSheet('background:#293a42;');return line

def detail_html(sections,tags):
 blocks=[]
 for section in sections:
  heading,_,body=section.partition('\n')
  if heading=='TAGS':
   chips=' &nbsp; '.join('<a style="color:#a9d4cb;text-decoration:none;background-color:#26383e;" href="'+html.escape(tag,quote=True)+'">'+html.escape(tag)+'</a>' for tag in dict.fromkeys(tags) if tag)
   content=chips
  elif heading=='PHYSICAL DETAILS' and ': ' in body:
   content='<table cellspacing="2" width="100%">'+''.join('<tr><td style="color:#8ea3ac">'+html.escape(line.partition(': ')[0])+'</td><td>'+html.escape(line.partition(': ')[2])+'</td></tr>' for line in body.splitlines())+'</table>'
  else:content=html.escape(body).replace('\n','<br>')
  blocks.append('<p style="margin:0 0 12px 0"><span style="font-size:10px;color:#9aafb7;font-weight:600">'+html.escape(heading)+'</span><br>'+content+'</p>')
 return '<html><body style="color:#c1cdd2;font-size:12px">'+''.join(blocks)+'</body></html>'

def human_size(n):
 if not n:return 'Size unknown'
 for unit in ['B','KB','MB','GB','TB']:
  if n<1024:return f'{n:,.1f} {unit}'
  n/=1024
 return f'{n:,.1f} PB'

def resolution(n):return f'{n//1024}K' if n>=1024 and n%1024==0 else str(n)+'px' if n else 'Unknown'

class Signals(QObject):
 done=Signal(object);failed=Signal(str);progress=Signal(object)
class Job(QRunnable):
 def __init__(self,fn):super().__init__();self.fn=fn;self.signals=Signals();self.cancel=threading.Event()
 def run(self):
  try:self.signals.done.emit(self.fn(self.signals.progress.emit,self.cancel.is_set))
  except Exception as ex:self.signals.failed.emit(str(ex))

class Images(QObject):
 changed=Signal(str)
 def __init__(self):
  super().__init__();self.manager=QNetworkAccessManager(self);self.memory=OrderedDict();self.pending=set();self.failed=set();self.online=True
  self.root=DATA/'previews';self.root.mkdir(parents=True,exist_ok=True)
 def prune(self):
  entries=sorted((p for p in self.root.glob('*.img')),key=lambda p:p.stat().st_mtime)
  size=sum(p.stat().st_size for p in entries)
  for p in entries:
   if size<256*1024*1024:break
   size-=p.stat().st_size;p.unlink(missing_ok=True)
 def remember(self,key,pixmap):
  self.memory[key]=pixmap;self.memory.move_to_end(key)
  while len(self.memory)>160:self.memory.popitem(last=False)
 def get(self,url,tiny=''):
  if url in self.memory:
   self.memory.move_to_end(url);return self.memory[url]
  cache=self.root/(hashlib.sha256(url.encode()).hexdigest()+'.img')
  local=Path(url) if url and not url.startswith(('https:','data:')) else None
  if (local and local.is_file()) or cache.is_file():
   pix=QPixmap(str(local if local and local.is_file() else cache))
   if not pix.isNull():self.remember(url,pix);return pix
  if self.online and url.startswith('https://') and url not in self.pending and url not in self.failed and len(self.pending)<6:
   # Only catalog preview CDN, never model/texture URLs.
   host=urlparse(url).hostname
   if host in ('ddinktqu5prvc.cloudfront.net','cdn.polyhaven.com','acg-media.struffelproductions.com') or url.startswith('https://huggingface.co/datasets/Sl8th/Megascans/resolve/'):
    self.pending.add(url)
    request=QNetworkRequest(QUrl(url));request.setTransferTimeout(15000)
    request.setAttribute(QNetworkRequest.RedirectPolicyAttribute,QNetworkRequest.NoLessSafeRedirectPolicy)
    reply=self.manager.get(request)
    reply.downloadProgress.connect(lambda n,total,r=reply:r.abort() if n>8*1024*1024 else None)
    reply.finished.connect(lambda r=reply,u=url,c=cache:self.finished(r,u,c))
  if tiny:
   key=hashlib.md5(tiny.encode()).hexdigest()
   if key in self.memory:return self.memory[key]
   pix=QPixmap()
   try:pix.loadFromData(base64.b64decode(tiny.split(',',1)[1]))
   except Exception:pass
   if not pix.isNull():self.remember(key,pix);return pix
  return QPixmap()
 def finished(self,reply,url,cache):
  self.pending.discard(url);data=bytes(reply.readAll());pix=QPixmap()
  if reply.error()==QNetworkReply.NoError and len(data)<=8*1024*1024 and pix.loadFromData(data):
   self.remember(url,pix)
   try:cache.write_bytes(data)
   except OSError:pass
  else:self.failed.add(url)
  reply.deleteLater();self.changed.emit(url)

class AssetModel(QAbstractListModel):
 def __init__(self):super().__init__();self.rows=[]
 def rowCount(self,parent=QModelIndex()):return len(self.rows)
 def data(self,index,role=Qt.DisplayRole):
  if not index.isValid():return None
  r=self.rows[index.row()]
  if role==Qt.DisplayRole:return r['name']
  if role==Qt.UserRole:return r
  if role==Qt.ToolTipRole:return f"{r['name']}\n{r['id']} · {r['kind']} / {r['subtype']}"
 def replace(self,rows):self.beginResetModel();self.rows=rows;self.endResetModel()

class CardDelegate(QStyledItemDelegate):
 favoriteClicked=Signal(str)
 def __init__(self,images,parent):super().__init__(parent);self.images=images;self.card=QSize(216,202)
 def editorEvent(self,event,model,opt,index):
  r=opt.rect.adjusted(5,5,-5,-5)
  if event.type()==QEvent.MouseButtonRelease and event.button()==Qt.LeftButton and QRect(r.right()-34,r.bottom()-40,32,34).contains(event.position().toPoint()):
   self.favoriteClicked.emit(index.data(Qt.UserRole)['id']);return True
  return super().editorEvent(event,model,opt,index)
 def sizeHint(self,*args):return self.card
 def paint(self,p,opt,index):
  a=index.data(Qt.UserRole);r=opt.rect.adjusted(5,5,-5,-5)
  selected=bool(opt.state&QStyle.State_Selected);hover=bool(opt.state&QStyle.State_MouseOver)
  p.save();p.setRenderHint(QPainter.Antialiasing)
  p.setPen(QColor('#29d5bb' if selected else '#50636c' if hover else '#28383f'))
  p.setBrush(QColor('#1b2c30' if selected else '#19252b'));p.drawRoundedRect(r,6,6)
  imgrect=QRect(r.x()+1,r.y()+1,r.width()-2,r.height()-57)
  pix=self.images.get(a['preview'],a['tiny'])
  if not pix.isNull():
   scaled=pix.scaled(imgrect.size(),Qt.KeepAspectRatio,Qt.SmoothTransformation)
   p.drawPixmap(imgrect.x()+(imgrect.width()-scaled.width())//2,imgrect.y()+(imgrect.height()-scaled.height())//2,scaled)
  else:
   p.setPen(QColor('#52636b'));p.setFont(QFont('DejaVu Sans',24));p.drawText(imgrect,Qt.AlignCenter,'◇')
   p.setFont(QFont('DejaVu Sans',9));p.drawText(imgrect.adjusted(0,60,0,0),Qt.AlignCenter,'Preview unavailable')
  p.setFont(QFont('DejaVu Sans',8));p.setPen(QColor('#b9d8d3'));p.drawText(imgrect.adjusted(9,7,-55,-7),Qt.AlignTop|Qt.AlignLeft,a.get('source') or 'Quixel')
  badge=QRect(imgrect.right()-48,imgrect.y()+9,39,21)
  p.setPen(Qt.NoPen);p.setBrush(QColor(17,22,25,220));p.drawRoundedRect(badge,3,3)
  p.setFont(QFont('DejaVu Sans',9));p.setPen(QColor('#c4d1d7'));p.drawText(badge,Qt.AlignCenter,resolution(a['maxres']) if a['maxres'] else '—')
  p.setPen(QColor('#2ad2b9' if a.get('favorite') else '#82969e'));p.setFont(QFont('DejaVu Sans',15));p.drawText(QRect(r.right()-30,r.bottom()-35,24,26),Qt.AlignCenter,'♥' if a.get('favorite') else '♡')
  p.setFont(QFont('DejaVu Sans',10,QFont.Medium));p.setPen(QColor('#edf0f2'))
  p.drawText(QRect(r.x()+12,r.bottom()-48,r.width()-48,23),Qt.AlignVCenter,p.fontMetrics().elidedText(a['name'],Qt.ElideRight,r.width()-48))
  p.setFont(QFont('DejaVu Sans',8));p.setPen(QColor('#96a4ad'))
  p.drawText(QRect(r.x()+12,r.bottom()-25,r.width()-48,18),Qt.AlignVCenter,p.fontMetrics().elidedText(a['kind']+'  /  '+a['subtype'],Qt.ElideRight,r.width()-48))
  p.restore()

class Preview(QLabel):
 def __init__(self,images):
  super().__init__();self.images=images;self.url='';self.tiny='';self.setMinimumHeight(210);self.setMaximumHeight(260);self.setAlignment(Qt.AlignCenter);self.images.changed.connect(lambda _:self.update());self.setStyleSheet('background:#111619;border:1px solid #2b343b;border-radius:7px;')
 def set_image(self,url,tiny=''):self.url=url;self.tiny=tiny;self.update()
 def paintEvent(self,event):
  super().paintEvent(event)
  pix=self.images.get(self.url,self.tiny)
  p=QPainter(self)
  if not pix.isNull():
   scaled=pix.scaled(self.size()-QSize(12,12),Qt.KeepAspectRatio,Qt.SmoothTransformation);p.drawPixmap((self.width()-scaled.width())//2,(self.height()-scaled.height())//2,scaled)
  else:p.setPen(QColor('#647780'));p.drawText(self.rect(),Qt.AlignCenter,'No preview available')

class DownloadDialog(QDialog):
 def __init__(self,window,asset):
  super().__init__(window);self.window=window;self.asset=asset;self.plan=None;self.setWindowTitle('Download selected asset');self.resize(530,520)
  l=QVBoxLayout(self);l.setSpacing(15);l.setContentsMargins(25,25,25,25)
  l.addWidget(label('DOWNLOAD ASSET','eyebrow'));l.addWidget(label(asset['name'],'assettitle',True))
  self.quality=QComboBox();self.quality.addItems(list(LEVELS));self.quality.setCurrentText(window.quality.currentText());l.addWidget(self.quality)
  self.summary=label('',wrap=True);l.addWidget(self.summary)
  self.files=label('', 'muted',True);self.files.setTextInteractionFlags(Qt.TextSelectableByMouse)
  sc=QScrollArea();sc.setWidgetResizable(True);sc.setWidget(self.files);sc.setMinimumHeight(130);l.addWidget(sc)
  l.addWidget(label('DESTINATION FOLDER','eyebrow'))
  row=QHBoxLayout();self.folder=QLineEdit(window.catalog.setting('destination',str(Path.home()/'Downloads')));row.addWidget(self.folder);row.addWidget(button('Browse…',self.browse));l.addLayout(row)
  self.notice=label('Only the files listed above will be downloaded. A separate asset folder will be created. Account access is checked before transfer.','muted',True);l.addWidget(self.notice)
  self.start=button('Download selected files',self.accept,'primary');l.addWidget(self.start)
  l.addWidget(button('Cancel',self.reject))
  self.quality.currentTextChanged.connect(self.update_plan);self.update_plan()
 def browse(self):
  folder=QFileDialog.getExistingDirectory(self,'Download destination',self.folder.text())
  if folder:self.folder.setText(folder)
 def update_plan(self):
  try:
   self.plan=build_plan(self.asset,self.quality.currentText())
   files=self.plan['files'];tri=sum(f.get('tris') or 0 for f in files if f['type']=='mesh')
   suffix=f' · {tri:,} triangles' if tri else ''
   self.summary.setText(f"{resolution(self.plan['resolution'])} textures · {len(files)} files{suffix}\nEstimated payload: {human_size(self.plan['bytes'])}"+(' (some sizes unknown)' if not self.plan['complete_size'] else ''))
   self.files.setText('\n'.join(f"{f['name']}  ·  {human_size(f['size'])}" for f in files))
   public=self.asset['detail'].get('source') in PUBLIC
   self.start.setEnabled((public or (bool(self.window.client) and self.asset['id'] in self.window.live_owned)) and not self.window.busy)
   if public:self.notice.setText(self.asset['detail'].get('source','')+' · '+self.asset['detail'].get('license','')+'. Only listed files download. ZIP packages require extraction.')
   elif not self.window.client:self.notice.setText('Connect your Quixel account first. Browsing the catalog does not require an account.')
   elif self.asset['id'] not in self.window.live_owned:self.notice.setText('Not acquired in the connected Quixel account. If you own it through Fab, use Open in Fab instead.')
  except ValueError as ex:self.summary.setText(str(ex));self.start.setEnabled(False)
 def accept(self):
  if not Path(self.folder.text()).expanduser().is_dir():QMessageBox.information(self,'Choose a folder','Choose an existing destination folder.');return
  super().accept()

class Window(QMainWindow):
 def __init__(self,catalog=None):
  super().__init__();self.catalog=catalog or Catalog();self.images=Images();self.jobs=set();self.pool=QThreadPool.globalInstance();self.current=None;self.client=None;self.live_owned=set();self.busy=False;self.offset=0;self.total=0;self.scope='';self.kind='';self.kinds=[];self.subtype='';self.collection_id=None;self.smart_query=None;self.active_download=None
  self.setWindowTitle('Atlas — Asset Catalog');self.setWindowIcon(QIcon(str(Path(__file__).parent/'assets/atlas-icon-v1.png')));self.resize(1788,1000);self.setMinimumSize(1280,800)
  root=QWidget();self.setCentralWidget(root);layout=QVBoxLayout(root);layout.setContentsMargins(0,0,0,0);layout.setSpacing(0)
  top=QWidget();top.setObjectName('topbar');tl=QHBoxLayout(top);tl.setContentsMargins(20,10,20,10)
  brand=QWidget();bl=QHBoxLayout(brand);bl.setContentsMargins(0,0,0,0);logo=QLabel();logo.setPixmap(QIcon(str(Path(__file__).parent/'assets/scanatlas.svg')).pixmap(32,32));bl.addWidget(logo);bl.addWidget(label('Atlas','brand'));bl.addStretch();brand.setFixedWidth(210);tl.addWidget(brand)
  self.search=QLineEdit();self.search.setPlaceholderText('Search assets, tags or Quixel IDs…');self.search.setClearButtonEnabled(True);self.search.setMinimumHeight(38);self.search.addAction(ui_icon('search'),QLineEdit.LeadingPosition);tl.addWidget(self.search,1)
  self.res_filter=QComboBox();self.res_filter.addItems(['Any resolution','2K and above','4K and above','8K and above']);self.res_filter.currentIndexChanged.connect(self.refresh);tl.addWidget(self.res_filter)
  self.sort=QComboBox();self.sort.addItems(['Relevance','Name A–Z','Name Z–A','Highest resolution']);self.sort.currentIndexChanged.connect(self.refresh);tl.addWidget(self.sort);tl.addSpacing(12)
  self.connection_label=label('●  Connected catalogs','muted');tl.addWidget(self.connection_label);tl.addSpacing(14);self.connect_button=button('Connect Quixel',self.connect_account);tl.addWidget(self.connect_button);tl.addWidget(button('Mixamo',self.open_mixamo));tl.addWidget(button('Sources',self.show_sources));tl.addWidget(button('Import library',self.import_menu));layout.addWidget(top)
  split=QSplitter();layout.addWidget(split,1)
  side=QWidget();side.setObjectName('sidebar');sl=QVBoxLayout(side);sl.setContentsMargins(16,22,12,14);sl.setSpacing(6)
  sl.addWidget(label('WORKSPACE','eyebrow'));self.scope_buttons={}
  for title,scope,glyph in [('All assets','','layers'),('Favorites','favorites','heart'),('Acquired','owned','check'),('Downloaded','downloaded','download')]:
   b=button(title,lambda checked=False,s=scope:self.select_scope(s),'flat');b.setIcon(ui_icon(glyph));b.setIconSize(QSize(19,19));b.setCheckable(True);b.setMinimumHeight(38);self.scope_buttons[scope]=b;sl.addWidget(b)
  sl.addWidget(separator());sl.addSpacing(8);sl.addWidget(label('ASSET CATEGORIES','eyebrow'))
  self.tree=QTreeWidget();self.tree.setColumnCount(2);self.tree.setHeaderHidden(True);self.tree.header().setStretchLastSection(False);self.tree.header().setMinimumSectionSize(30);self.tree.header().setSectionResizeMode(0,QHeaderView.Stretch);self.tree.header().setSectionResizeMode(1,QHeaderView.Fixed);self.tree.setColumnWidth(1,44);self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff);self.tree.setIndentation(14);self.tree.itemClicked.connect(self.tree_selected);self.tree.itemExpanded.connect(lambda i:self.tree_marker(i,True));self.tree.itemCollapsed.connect(lambda i:self.tree_marker(i,False));sl.addWidget(self.tree,1)
  sl.addWidget(separator());row=QHBoxLayout();row.addWidget(label('MY COLLECTIONS','eyebrow'));row.addStretch();row.addWidget(button('+',self.new_collection,'flat'));sl.addLayout(row)
  self.collection_tree=QTreeWidget();self.collection_tree.setHeaderHidden(True);self.collection_tree.setMaximumHeight(112);self.collection_tree.itemClicked.connect(self.select_collection);self.collection_tree.setContextMenuPolicy(Qt.CustomContextMenu);self.collection_tree.customContextMenuRequested.connect(self.collection_menu);sl.addWidget(self.collection_tree)
  sl.addWidget(button('+ Save search as collection',self.save_search,'flat'))
  self.network=QCheckBox('Load online previews');self.network.setChecked(self.catalog.setting('online_previews','1')=='1');self.images.online=self.network.isChecked();self.network.toggled.connect(self.toggle_previews);sl.addWidget(self.network)
  storage=QFrame();storage.setStyleSheet('QFrame {background:#17252b;border:1px solid #2b3b43;border-radius:5px;} QLabel {border:0;}');stl=QVBoxLayout(storage);stl.addWidget(label('Local storage','muted'));disk=shutil.disk_usage(DATA);meter=QProgressBar();meter.setRange(0,100);meter.setValue(round(100*disk.used/disk.total));meter.setTextVisible(False);meter.setFixedHeight(5);stl.addWidget(meter);stl.addWidget(label(f'{human_size(disk.free)} free of {human_size(disk.total)}','muted'));sl.addWidget(storage);split.addWidget(side)
  center=QWidget();center.setObjectName('center');cl=QVBoxLayout(center);cl.setContentsMargins(20,16,16,12);cl.setSpacing(10)
  self.breadcrumb=label('','muted');self.breadcrumb.hide()
  title_row=QHBoxLayout();self.heading=label('All assets','title');title_row.addWidget(self.heading);title_row.addStretch();cl.addLayout(title_row)
  self.debounce=QTimer();self.debounce.setSingleShot(True);self.debounce.setInterval(180);self.debounce.timeout.connect(self.refresh);self.search.textChanged.connect(lambda:self.debounce.start())
  type_grid=QGridLayout();type_grid.setHorizontalSpacing(6);type_grid.setVerticalSpacing(6);self.type_buttons={}
  for n,(key,title) in enumerate([('', 'All types')]+[(k,'3D Models' if k=='3D Assets' else k) for k in TYPES]):
   chip=button(title,lambda checked=False,k=key:self.toggle_type(k),'typeFilter');chip.setCheckable(True);chip.setChecked(not key);chip.setToolTip('Combine types: results can match any selected type. 3D Plants is separate from 3D Models.');self.type_buttons[key]=chip;type_grid.addWidget(chip,n//5,n%5)
  cl.addLayout(type_grid)
  filters=QHBoxLayout();self.related=QCheckBox('Related terms');self.related.setChecked(True);self.related.setToolTip('Include related concepts and typo correction. Exact name matches rank first.');self.related.toggled.connect(self.refresh);filters.addWidget(self.related)
  self.source_filter=QComboBox()
  for name,key in [('All connected sources',''),('Poly Haven · CC0','polyhaven'),('ambientCG · CC0','ambientcg'),('Hugging Face','huggingface'),('Mixamo · local','mixamo')]:self.source_filter.addItem(name,key)
  self.source_filter.currentIndexChanged.connect(self.refresh);filters.addWidget(self.source_filter);filters.addWidget(button('Clear filters',self.clear_filters));filters.addStretch();cl.addLayout(filters)
  self.results_label=label('','muted');cl.insertWidget(1,self.results_label)
  self.model=AssetModel();self.grid=QListView();self.grid.setModel(self.model);self.grid.setViewMode(QListView.IconMode);self.grid.setResizeMode(QListView.Adjust);self.grid.setMovement(QListView.Static);self.grid.setWrapping(True);self.grid.setUniformItemSizes(True);self.grid.setMouseTracking(True);self.grid.setSpacing(0);self.grid.setVerticalScrollMode(QListView.ScrollPerPixel);self.delegate=CardDelegate(self.images,self.grid);self.grid.setItemDelegate(self.delegate);self.delegate.favoriteClicked.connect(self.favorite_asset);self.grid.setGridSize(self.delegate.card);self.grid.selectionModel().currentChanged.connect(self.asset_selected);self.grid.doubleClicked.connect(self.large_preview);cl.addWidget(self.grid,1)
  self.empty=label('','muted',True);self.empty.setAlignment(Qt.AlignCenter);self.empty.hide();cl.addWidget(self.empty)
  footer=QHBoxLayout();self.previous=button('← Previous',lambda:self.page(-1));self.next=button('Next →',lambda:self.page(1));footer.addWidget(self.previous);self.page_label=label('','muted');footer.addWidget(self.page_label);footer.addWidget(self.next);footer.addStretch();footer.addWidget(label('Grid','muted'));slider=QSlider(Qt.Horizontal);slider.setRange(170,290);slider.setValue(216);slider.setFixedWidth(85);slider.valueChanged.connect(self.resize_cards);footer.addWidget(slider);cl.addLayout(footer);split.addWidget(center)
  inspector=QWidget();inspector.setObjectName('inspector');il=QVBoxLayout(inspector);il.setContentsMargins(18,16,18,16);il.setSpacing(8)
  self.preview=Preview(self.images);self.preview.setMinimumHeight(180);self.preview.setMaximumHeight(210);self.preview.setToolTip('Double-click an asset card for a larger preview');il.addWidget(self.preview)
  self.asset_title=label('Select an asset','assettitle',True);il.addWidget(self.asset_title)
  self.asset_type=label('Browse the catalog to inspect its details.','muted',True);il.addWidget(self.asset_type)
  self.asset_id=label('','muted');self.asset_id.setTextInteractionFlags(Qt.TextSelectableByMouse);il.addWidget(self.asset_id)
  actions=QHBoxLayout();self.fav=button('Add to favorites',self.toggle_favorite);self.fav.setIcon(ui_icon('heart'));actions.addWidget(self.fav);collect=button('Add to collection',self.add_to_collection);collect.setIcon(ui_icon('folder'));actions.addWidget(collect);il.addLayout(actions)
  self.details=QTextBrowser();self.details.setOpenLinks(False);self.details.anchorClicked.connect(lambda url:self.search_tag(url.toString()));il.addWidget(self.details,1)
  il.addWidget(separator());il.addWidget(label('DOWNLOAD','eyebrow'));self.quality=QComboBox();self.quality.addItems(list(LEVELS));self.quality.setCurrentText('Medium');self.quality.currentTextChanged.connect(self.quality_changed);il.addWidget(self.quality)
  self.quality_info=label('','muted',True);il.addWidget(self.quality_info)
  self.download_button=button('Download asset…',self.download,'primary');self.download_button.setIcon(ui_icon('download'));self.download_button.setToolTip('Choose quality and destination folder before downloading');self.download_button.setEnabled(False);il.addWidget(self.download_button)
  links=QHBoxLayout();links.addWidget(button('Open source ↗',self.open_quixel));links.addWidget(button('Find on Fab ↗',self.open_fab));il.addLayout(links);self.open_folder_button=button('Open local folder',self.open_local);self.open_folder_button.hide();il.addWidget(self.open_folder_button);split.addWidget(inspector)
  side.setMinimumWidth(215);side.setMaximumWidth(310);inspector.setMinimumWidth(360);inspector.setMaximumWidth(440);split.setSizes([240,1148,400]);split.setCollapsible(0,False);split.setCollapsible(1,False);split.setCollapsible(2,False)
  status=QWidget();st=QHBoxLayout(status);st.setContentsMargins(20,7,20,7);self.status=label('','muted');st.addWidget(self.status,1);self.progress=QProgressBar();self.progress.setFixedWidth(200);self.progress.hide();st.addWidget(self.progress);self.cancel_button=button('Cancel',self.cancel_task,'flat');self.cancel_button.hide();st.addWidget(self.cancel_button);layout.addWidget(status)
  self.images.changed.connect(self.image_changed);self.image_timer=QTimer(self);self.image_timer.setInterval(1500);self.image_timer.timeout.connect(self.grid.viewport().update);self.image_timer.start()
  self.shortcuts=[QShortcut(QKeySequence('Ctrl+F'),self),QShortcut(QKeySequence('Escape'),self)]
  self.shortcuts[0].activated.connect(self.search.setFocus);self.shortcuts[1].activated.connect(self.search.clear)
  self.populate_tree();self.populate_collections();self.refresh();self.show_status()
 def show_status(self,text=None):
  self.status.setText(text or f"{self.catalog.count():,} assets in catalog  ·  Metadata snapshot")
 def toggle_previews(self,enabled):
  self.images.online=enabled;self.catalog.set_setting('online_previews',int(enabled));self.grid.viewport().update();self.preview.update()
 def resize_cards(self,width):self.delegate.card=QSize(width,width-6);self.grid.setGridSize(self.delegate.card);self.grid.doItemsLayout()
 def tree_marker(self,item,expanded):
  pass # Native tree branch arrows indicate expanded state.
 def populate_tree(self):
  self.tree.clear();facets=self.catalog.facets()
  for kind in TYPES:
   records=[r for r in facets if r[0]==kind]
   if not records:continue
   root=QTreeWidgetItem([kind,f'{sum(r[2] for r in records):,}']);root.setIcon(0,ui_icon({'3D Assets':'cube','3D Plants':'plant','Surfaces':'layers','Brushes':'brush'}.get(kind,'grid')));root.setTextAlignment(1,Qt.AlignRight|Qt.AlignVCenter);root.setForeground(1,QColor('#82969e'));root.setData(0,Qt.UserRole,(kind,''));self.tree.addTopLevelItem(root)
   for _,subtype,n in records:
    child=QTreeWidgetItem([subtype,f'{n:,}']);child.setForeground(1,QColor('#82969e'));child.setTextAlignment(1,Qt.AlignRight|Qt.AlignVCenter);child.setData(0,Qt.UserRole,(kind,subtype));root.addChild(child)
 def populate_collections(self):
  self.collection_tree.clear()
  for c in self.catalog.collections():
   item=QTreeWidgetItem([c['name']]);item.setIcon(0,ui_icon('folder'));item.setData(0,Qt.UserRole,c);self.collection_tree.addTopLevelItem(item)
 def select_scope(self,scope):
  self.scope=scope;self.kinds=[];self.sync_types();self.kind=self.subtype='';self.collection_id=None;self.smart_query=None;self.tree.clearSelection();self.collection_tree.clearSelection();self.heading.setText({'favorites':'Favorites','owned':'Acquired assets','downloaded':'Downloaded'}.get(scope,'All assets'));self.refresh()
 def tree_selected(self,item,column):
  self.kind,self.subtype=item.data(0,Qt.UserRole);self.kinds=[self.kind];self.sync_types()
  if item.childCount():item.setExpanded(not item.isExpanded())
  self.scope='';self.collection_id=None;self.smart_query=None;self.collection_tree.clearSelection();self.heading.setText(self.subtype or self.kind);self.refresh()
 def select_collection(self,item,column):
  c=item.data(0,Qt.UserRole);self.kind=self.subtype=self.scope='';self.tree.clearSelection();self.heading.setText(c['name']);self.collection_id=c['id'] if c['query'] is None else None;self.smart_query=c['query']
  spec={}
  if c['query']:
   try:spec=json.loads(c['query'])
   except ValueError:spec={'text':c['query']}
  self.kind=spec.get('kind','');self.kinds=spec.get('kinds',[self.kind] if self.kind else []);self.sync_types();self.subtype=spec.get('subtype','');self.scope=spec.get('scope','');self.res_filter.setCurrentIndex(spec.get('resolution',0));self.related.setChecked(spec.get('related',True));self.search.setText(spec.get('text',''));self.refresh()
 def sync_types(self):
  for key,chip in self.type_buttons.items():chip.setChecked(key in self.kinds if key else not self.kinds)
 def toggle_type(self,kind):
  if not kind:self.kinds=[]
  elif kind in self.kinds:self.kinds.remove(kind)
  else:self.kinds.append(kind)
  self.kind=self.kinds[0] if len(self.kinds)==1 else '';self.subtype='';self.tree.clearSelection();self.sync_types()
  if not self.collection_id and not self.smart_query:self.heading.setText({'favorites':'Favorites','owned':'Acquired assets','downloaded':'Downloaded'}.get(self.scope,'All assets'))
  self.refresh()
 def clear_filters(self):
  self.search.clear();self.source_filter.setCurrentIndex(0);self.res_filter.setCurrentIndex(0);self.select_scope('')
 def refresh(self,*args,keep_page=False):
  if not hasattr(self,'grid'):return
  if not keep_page:self.offset=0
  for scope,b in self.scope_buttons.items():b.setChecked(scope==self.scope and not self.kinds and not self.collection_id and not self.smart_query)
  if self.search.text().strip():self.heading.setText('Search results for “'+self.search.text().strip()+'”')
  elif self.collection_id or self.smart_query:pass
  else:self.heading.setText(self.subtype or (' + '.join(self.kinds) if self.kinds else {'favorites':'Favorites','owned':'Acquired assets','downloaded':'Downloaded'}.get(self.scope,'All assets')))
  started=time.perf_counter()
  rows,total,notes=self.catalog.query(self.search.text(),self.kind,self.subtype,self.scope,self.collection_id,[0,2048,4096,8192][self.res_filter.currentIndex()],self.sort.currentText(),120,self.offset,self.related.isChecked(),kinds=self.kinds,source=self.source_filter.currentData())
  self.total=total;self.model.replace(rows);self.grid.scrollToTop()
  trail='LIBRARY  /  '+(self.kind.upper() if self.kind else self.scope.upper() if self.scope else 'ALL ASSETS')
  if self.subtype:trail+='  /  '+self.subtype.upper()
  self.breadcrumb.setText(trail)
  elapsed=(time.perf_counter()-started)*1000
  self.results_label.setText(f'{total:,} assets'+(' · '+self.subtype if self.subtype else '')+('  ·  Related: '+', '.join(notes[:5]) if notes else ''))
  self.results_label.setToolTip(f'Search completed in {elapsed:.0f} ms. Selected types are combined with OR; text and other filters narrow those results.')
  self.previous.setEnabled(self.offset>0);self.next.setEnabled(self.offset+120<total);self.page_label.setText(f'{self.offset+1 if total else 0}–{min(self.offset+120,total)} of {total:,}')
  self.empty.setVisible(not rows);self.grid.setVisible(bool(rows))
  self.empty.setText('No assets match these filters. Try a broader search or enable Related terms.' if self.catalog.count() else 'Your catalog is empty. Import the metadata archive or an existing Bridge library to begin.')
  if rows:self.grid.setCurrentIndex(self.model.index(0))
  else:self.current=None;self.asset_title.setText('No asset selected');self.preview.set_image('');self.details.clear();self.asset_id.clear();self.asset_type.clear();self.quality_info.clear();self.download_button.setEnabled(False)
 def page(self,direction):self.offset=max(0,self.offset+direction*120);self.refresh(keep_page=True)
 def asset_selected(self,index,previous=QModelIndex()):
  if not index.isValid():return
  row=index.data(Qt.UserRole);self.current=self.catalog.get(row['id']);a=self.current;d=a['detail'];self.preview.set_image(a['preview'],a['tiny']);self.asset_title.setText(a['name']);self.asset_type.setText(a['kind']+'  /  '+a['subtype']);self.asset_id.setText(('ATLAS ID  ' if d.get('source') in ('mixamo','polyhaven','ambientcg') else 'QUIXEL ID  ')+d.get('quixel_id',a['id']));self.fav.setText('Favorited' if row.get('favorite') else 'Add to favorites')
  meta=d.get('meta',{});keep=['Length','Width','Height','Scan Area','Texel Density','Tileable'];specs=[f'{k}: {meta[k]}' for k in keep if k in meta]
  lods=sorted({f['lod'] for f in d.get('files',[]) if f['type']=='mesh' and f.get('lod') is not None})
  tris=[f.get('tris',0) or 0 for f in d.get('files',[]) if f['type']=='mesh']
  maps=list(dict.fromkeys(f['type'].title() for f in d.get('files',[]) if f['type']!='mesh'))
  specs=['RESOLUTIONS\n'+' · '.join(resolution(r) for r in d.get('resolutions',[])), 'PHYSICAL DETAILS\n'+('\n'.join(specs) if specs else 'Not specified in source metadata')]+(['GEOMETRY\n'+' · '.join('LOD'+str(l) for l in lods)+(f'\nUp to {max(tris):,} triangles in numbered LODs' if max(tris,default=0) else '')] if lods else [])
  specs+=['TEXTURE MAPS\n'+(', '.join(maps) if maps else 'Not specified'),'TAGS\n'+', '.join(d.get('tags',[])[:28]),'ACCESS\n'+('Acquired in connected Quixel account' if a['id'] in self.live_owned else 'Public source files available' if d.get('source') in PUBLIC else 'Catalog entry · ownership not verified')]
  if d.get('source') in PUBLIC:specs+=['SOURCE\n'+d['source'],'LICENSE\n'+d['license']]
  if d.get('manifest_pending'):specs+=['FILES\nClick Download to fetch file sizes and quality choices. No assets download until confirmed.']
  if d.get('source')=='mixamo' and not d.get('catalog_only'):specs=['SOURCE\nMixamo · local FBX','FILE\n'+human_size(d['size_bytes']),'RIG\nUnverified · validate Humanoid Avatar in Unity','CHARACTER\n'+(d.get('character_id') or 'Not linked'),'LICENSE\n'+d['license']]
  self.download_button.setText('Stage selected FBX…' if d.get('source')=='mixamo' else 'Download asset…')
  if a['local_path']:specs+=['LOCAL LIBRARY\n'+a['local_path']]
  self.open_folder_button.setVisible(bool(a['local_path'] or self.catalog.c.execute("SELECT 1 FROM downloads WHERE asset_id=? AND status='complete'",(a['id'],)).fetchone()))
  self.details.setText(detail_html(specs,d.get('tags',[])));self.download_button.setEnabled(bool(d.get('files') or d.get('local_file') or d.get('manifest_pending')) and not self.busy);self.quality_changed()
 def search_tag(self,tag):
  self.search.setText(tag);self.refresh()
 def quality_changed(self,*args):
  if not self.current:return
  if self.current['detail'].get('source')=='mixamo':
   self.quality_info.setText('Original FBX · '+human_size(self.current['detail'].get('size_bytes',0))+'\nTexture quality not inspected');return
  try:
   plan=build_plan(self.current,self.quality.currentText());lods=sorted({f['lod'] for f in plan['files'] if f['type']=='mesh' and f.get('lod') is not None});raw=any(f.get('mesh_type')=='original' for f in plan['files'])
   geometry=' + source mesh' if raw else ' + '+', '.join('LOD'+str(i) for i in lods) if lods else ''
   self.quality_info.setText(f"{resolution(plan['resolution'])}{geometry}  ·  {len(plan['files'])} files\nEstimated {human_size(plan['bytes'])}"+(' · incomplete size data' if not plan['complete_size'] else ''))
  except ValueError:self.quality_info.setText('Quality information unavailable')
 def image_changed(self,url):self.grid.viewport().update();self.preview.update()
 def toggle_favorite(self):
  if self.current:self.favorite_asset(self.current['id'])
 def favorite_asset(self,asset_id):
  self.catalog.favorite(asset_id)
  for row in self.model.rows:
   if row['id']==asset_id:
    row['favorite']=not row.get('favorite')
    if self.current and self.current['id']==asset_id:self.fav.setText('Favorited' if row['favorite'] else 'Add to favorites')
    break
  self.grid.viewport().update()
 def new_collection(self):
  name,ok=QInputDialog.getText(self,'New collection','Collection name:')
  if ok and name.strip():
   try:self.catalog.collection(name.strip());self.populate_collections()
   except Exception:QMessageBox.information(self,'Collection exists','Choose a different collection name.')
 def save_search(self):
  query=self.search.text().strip()
  if not query:QMessageBox.information(self,'Save a search','Enter a search first. Saved searches update automatically as the catalog grows.');return
  name,ok=QInputDialog.getText(self,'Save search','Name this automatic collection:',text=query.title())
  if ok and name.strip():
   try:self.catalog.collection(name.strip(),json.dumps({'text':query,'kind':self.kind,'kinds':self.kinds,'subtype':self.subtype,'scope':self.scope,'resolution':self.res_filter.currentIndex(),'related':self.related.isChecked()}));self.populate_collections()
   except Exception:QMessageBox.information(self,'Collection exists','Choose another collection name.')
 def collection_menu(self,pos):
  item=self.collection_tree.itemAt(pos)
  if not item:return
  c=item.data(0,Qt.UserRole);menu=QMenu(self);delete=menu.addAction('Delete collection');remove=menu.addAction('Remove selected asset') if c['query'] is None and self.current else None
  action=menu.exec(self.collection_tree.mapToGlobal(pos))
  if action==delete:
   self.catalog.c.execute('DELETE FROM collections WHERE id=?',(c['id'],));self.catalog.c.commit();self.populate_collections();self.select_scope('')
  elif remove and action==remove:
   self.catalog.c.execute('DELETE FROM members WHERE collection_id=? AND asset_id=?',(c['id'],self.current['id']));self.catalog.c.commit();self.refresh()
 def add_to_collection(self):
  if not self.current:return
  collections=[c for c in self.catalog.collections() if c['query'] is None]
  if not collections:self.new_collection();collections=[c for c in self.catalog.collections() if c['query'] is None]
  if not collections:return
  name,ok=QInputDialog.getItem(self,'Add to collection',self.current['name'],[c['name'] for c in collections],0,False)
  if ok:
   c=next(c for c in collections if c['name']==name);self.catalog.add_member(c['id'],self.current['id']);self.show_status('Added to '+name)
 def large_preview(self,*args):
  if not self.current:return
  dialog=QDialog(self);dialog.setWindowTitle(self.current['name']);dialog.resize(900,650);layout=QVBoxLayout(dialog);prev=Preview(self.images);prev.setMaximumHeight(2000);prev.setMinimumHeight(500);prev.set_image(next(iter(self.current['detail'].get('gallery',[])),self.current['preview']),self.current['tiny']);layout.addWidget(prev);layout.addWidget(label(self.current['name'],'assettitle'));layout.addWidget(button('Close',dialog.accept));dialog.exec()
 def open_local(self):
  if not self.current:return
  row=self.catalog.c.execute("SELECT path FROM downloads WHERE asset_id=? AND status='complete' ORDER BY id DESC LIMIT 1",(self.current['id'],)).fetchone()
  path=row[0] if row else self.current['local_path']
  if path:QDesktopServices.openUrl(QUrl.fromLocalFile(path))
 def open_quixel(self):
  if self.current and self.current['detail'].get('source_url'):QDesktopServices.openUrl(QUrl(self.current['detail']['source_url']));return
  if self.current:QDesktopServices.openUrl(QUrl('https://quixel.com/megascans/home?assetId='+quote(self.current['id'])))
 def open_fab(self):
  if self.current:QDesktopServices.openUrl(QUrl('https://www.fab.com/search?q='+quote(self.current['name'])))
 def run_job(self,fn,done):
  job=Job(fn);self.jobs.add(job)
  def success(result):self.jobs.discard(job);done(result)
  def failure(message):self.jobs.discard(job);self.task_finished();QMessageBox.warning(self,'Could not complete action',message)
  job.signals.done.connect(success);job.signals.failed.connect(failure);job.signals.progress.connect(self.task_progress);self.pool.start(job);return job
 def task_progress(self,value):
  done,total,*rest=value
  self.task_metrics={'done':done,'total':total,'stage':rest[0] if rest else ''}
  self.progress.setRange(0,100 if total else 0)
  if total:self.progress.setValue(min(100,int(done*100/total)))
  self.show_status((rest[0]+'  ·  ' if rest else '')+(f'{human_size(done)} / {human_size(total)}' if self.active_download else f'{done:,} records processed'))
 def task_started(self,text):
  self.task_metrics={}
  self.busy=True;self.progress.show();self.progress.setRange(0,0);self.cancel_button.show();self.download_button.setEnabled(False);self.connect_button.setEnabled(False);self.show_status(text)
 def task_finished(self):
  self.busy=False;self.active_download=None;self.progress.hide();self.cancel_button.hide();self.connect_button.setEnabled(True);self.download_button.setEnabled(bool(self.current and (self.current['detail'].get('files') or self.current['detail'].get('local_file') or self.current['detail'].get('manifest_pending'))))
 def cancel_task(self):
  for job in self.jobs:job.cancel.set()
  self.show_status('Cancelling… waiting for the current request to finish.')
 def connect_account(self):
  if self.client:
   self.client=None;self.live_owned=set();self.connect_button.setText('Connect Quixel');self.connection_label.setText('●  Local catalog');self.refresh(keep_page=True);return
  dialog=QDialog(self);dialog.setWindowTitle('Connect your Quixel library');dialog.resize(510,330);l=QVBoxLayout(dialog);l.setContentsMargins(24,24,24,24);l.setSpacing(14)
  l.addWidget(label('Connect Quixel','assettitle'));l.addWidget(label('Sign in to Quixel in your browser, then paste your access token. It stays in memory for this session only. This reads acquired asset IDs; it does not download or claim assets.','muted',True))
  l.addWidget(button('Open Quixel sign-in ↗',lambda:QDesktopServices.openUrl(QUrl('https://quixel.com/megascans/purchased'))))
  l.addWidget(label('In browser developer tools → Network, inspect a Quixel API request and copy the Authorization bearer token. Never share this token.','muted',True))
  token=QLineEdit();token.setEchoMode(QLineEdit.Password);token.setPlaceholderText('Quixel access token');l.addWidget(token)
  l.addWidget(label('Fab-only purchases use the official Fab download flow.','muted',True));buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel);buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);l.addWidget(buttons)
  if dialog.exec()!=QDialog.Accepted:return
  try:client=QuixelClient(token.text())
  except ValueError as ex:QMessageBox.warning(self,'Token required',str(ex));return
  token.clear();self.task_started('Reading acquired asset IDs…')
  def done(ids):
   self.client=client;self.live_owned=ids;self.catalog.set_owned(ids);self.connect_button.setText('Disconnect');self.connection_label.setText(f'●  Quixel connected · {len(ids):,} acquired');self.task_finished();self.show_status('Connected. No asset files downloaded.');self.refresh(keep_page=True)
  self.run_job(lambda progress,cancel:client.acquired(),done)
 def download(self):
  if not self.current or self.busy:return
  if self.current['detail'].get('source')=='mixamo':
   folder=QFileDialog.getExistingDirectory(self,'Choose staging parent folder')
   if not folder:return
   try:
    result=stage(self.catalog,[self.current['id']],Path(folder)/self.current['id'],True);QMessageBox.information(self,'Staged for Unity','FBX and import instructions saved to:\n'+result['destination'])
   except Exception as ex:QMessageBox.warning(self,'Staging failed',str(ex))
   return
  if self.current['detail'].get('manifest_pending'):
   ident=self.current['id'];self.task_started('Fetching file metadata…')
   def fetch(progress,cancel):
    c=Catalog(self.catalog.path)
    try:return hydrate(c,c.get(ident))
    finally:c.close()
   def ready(a):
    self.task_finished();self.current=a;self.download()
   self.run_job(fetch,ready);return
  dialog=DownloadDialog(self,self.current)
  if dialog.exec()!=QDialog.Accepted:return
  asset=self.current;plan=dialog.plan;folder=dialog.folder.text();self.catalog.set_setting('destination',folder);self.task_started('Checking access and preparing selected files…')
  def done(path):
   self.task_finished();self.show_status('Downloaded '+asset['name']);QMessageBox.information(self,'Download complete','Saved to:\n'+path)
  def transfer(progress,cancel):
   from .agent import tracked_download
   worker=Catalog(self.catalog.path)
   try:return tracked_download(worker,asset,plan,folder,HuggingFaceClient() if asset['detail'].get('source')=='huggingface' else PublicClient() if asset['detail'].get('source') in ('polyhaven','ambientcg') else self.client,lambda *v:progress(v),cancel)
   finally:worker.close()
  self.active_download=self.run_job(transfer,done)
 def show_sources(self):
  import html
  dialog=QDialog(self);dialog.setWindowTitle('Atlas sources');dialog.resize(760,650);outer=QVBoxLayout(dialog);scroll=QScrollArea();scroll.setWidgetResizable(True);body=QWidget();layout=QVBoxLayout(body);scroll.setWidget(body);outer.addWidget(scroll)
  for source in sources(self.catalog):
   text=source['name']+' — '+source['status']+'\n'+str(source.get('indexed_assets',source.get('advertised_assets',0)))+' assets'+(' (publisher claim)' if 'advertised_assets' in source else '')+'\n'+source.get('reason','Individual files indexed; availability and quality vary')+'\n'+source['license']
   layout.addWidget(label(text,'muted',True))
   link=label('<a href="'+html.escape(source['url'],quote=True)+'">View source listing</a>');link.setOpenExternalLinks(True);layout.addWidget(link)
   if source['id'].startswith('cger-'):layout.addWidget(button('Open archive in Atlas browser',lambda checked=False,u=source['url']:self.open_archive(u)))
  outer.addWidget(button('Sync public catalogs (metadata only)',lambda:(dialog.accept(),self.sync_public())));outer.addWidget(button('Close',dialog.accept));dialog.exec()
 def open_archive(self,url):
  from .mixamo_browser import SourceBrowser
  self.archive_window=SourceBrowser(self,url);self.archive_window.show()
 def open_mixamo(self):
  from .mixamo_bridge import call
  self.task_started('Opening Mixamo sign-in…')
  def done(result):self.task_finished();self.show_status('Mixamo runs independently. Close its window after signing in; agents can keep using the session.')
  self.run_job(lambda progress,cancel:call(self.catalog.path,'connect'),done)
 def sync_public(self):
  if self.busy:return
  self.task_started('Syncing official catalog metadata…')
  def fetch(progress,cancel):
   from .huggingface import sync
   c=Catalog(self.catalog.path);results=[]
   try:
    for fn in (sync_polyhaven,sync_ambientcg,sync):
     if cancel():break
     results.append(fn(c))
    return results
   finally:c.close()
  def done(result):self.task_finished();self.catalog._vocab=None;self.populate_tree();self.refresh();self.show_status('Catalogs synced. No asset files downloaded.')
  self.run_job(fetch,done)
 def import_mixamo(self):
  path,_=QFileDialog.getOpenFileName(self,'Import downloaded Mixamo FBX','','FBX (*.fbx *.FBX)')
  if not path:return
  kind,ok=QInputDialog.getItem(self,'FBX role','What does this file contain?',['Characters','Animations'],0,False)
  if not ok:return
  character=None
  if kind=='Animations':
   rows,_,_=self.catalog.query(kind='Characters',limit=10000)
   choices=['Not linked']+[r['name']+' · '+r['id'] for r in rows]
   choice,ok=QInputDialog.getItem(self,'Character','Exported for which character?',choices,0,False)
   if not ok:return
   if choice!='Not linked':character=choice.rsplit(' · ',1)[1]
  preview,_=QFileDialog.getOpenFileName(self,'Optional preview image — Cancel to skip','','Images (*.png *.jpg *.jpeg)')
  try:
   a=import_fbx(self.catalog,path,kind,character,preview or None);self.populate_tree();self.search.setText(a['id']);self.refresh();self.show_status('Indexed local FBX. Rig validation remains pending in Unity.')
  except Exception as ex:QMessageBox.warning(self,'Import failed',str(ex))
 def import_menu(self):
  if self.busy:return
  menu=QMenu(self);mixamo=menu.addAction('Import Mixamo character or animation (.fbx)…');browse=menu.addAction('Open Mixamo · rig characters / find animations');archive=menu.addAction('Import metadata archive (.tar.zst)…');local=menu.addAction('Index a local Bridge library…');export=menu.addAction('Export current results to JSON…');action=menu.exec(self.cursor().pos())
  if action==mixamo:self.import_mixamo();return
  if action==browse:QDesktopServices.openUrl(QUrl(GUIDE['url']));return
  if action==export:self.export_results();return
  if action==archive:
   path,_=QFileDialog.getOpenFileName(self,'Metadata archive','','Zstandard metadata (*.tar.zst)')
   if not path:return
   fn=lambda progress,cancel:import_archive(path,self.catalog.path,lambda *v:progress(v),cancel)
  elif action==local:
   path=QFileDialog.getExistingDirectory(self,'Select your downloaded Bridge library')
   if not path:return
   fn=lambda progress,cancel:import_local(path,self.catalog.path,lambda *v:progress(v),cancel)
  else:return
  self.task_started('Indexing metadata only…')
  def done(count):self.task_finished();self.catalog._vocab=None;self.populate_tree();self.refresh();self.show_status('Import complete. '+str(count)+' records processed.')
  self.run_job(fn,done)
 def export_results(self):
  path,_=QFileDialog.getSaveFileName(self,'Export metadata','catalog-results.json','JSON (*.json)')
  if not path:return
  rows,_,_=self.catalog.query(self.search.text(),self.kind,self.subtype,self.scope,self.collection_id,[0,2048,4096,8192][self.res_filter.currentIndex()],self.sort.currentText(),100000,0,self.related.isChecked(),kinds=self.kinds,source=self.source_filter.currentData())
  try:Path(path).write_text(json.dumps([{k:v for k,v in r.items() if k!='tiny'} for r in rows],indent=2),encoding='utf-8');self.show_status(f'Exported {len(rows):,} metadata records.')
  except OSError as ex:QMessageBox.warning(self,'Export failed',str(ex))
 def closeEvent(self,event):
  if self.jobs:
   self.cancel_task();QMessageBox.information(self,'Finishing current task','Cancellation requested. Please close again after the task finishes.');event.ignore();return
  self.catalog.close();event.accept()

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--screenshot');parser.add_argument('--query',default='');parser.add_argument('--offline',action='store_true');args=parser.parse_args()
 app=QApplication(sys.argv[:1]);app.setApplicationName('Atlas');app.setDesktopFileName('atlas');app.setWindowIcon(QIcon(str(Path(__file__).parent/'assets/atlas-icon-v1.png')));app.setStyle('Fusion');app.setStyleSheet(STYLE)
 from .web_catalog import WebCatalogWindow
 window=WebCatalogWindow(offline=args.offline)
 if args.offline:window.page.settings().setAttribute(__import__('PySide6.QtWebEngineCore',fromlist=['QWebEngineSettings']).QWebEngineSettings.LocalContentCanAccessRemoteUrls,False)
 window.show()
 if args.query:
  query=json.dumps(args.query)
  window.view.loadFinished.connect(lambda ok:QTimer.singleShot(500,lambda:window.page.runJavaScript("document.getElementById('search').value="+query+";state.query="+query+";load();")))
 if args.screenshot:
  def capture():window.grab().save(args.screenshot);window.close();app.quit()
  QTimer.singleShot(10000,capture)
 sys.exit(app.exec())

if __name__=='__main__':main()
