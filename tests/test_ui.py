import os
os.environ['QT_QPA_PLATFORM']='offscreen'
from PySide6.QtWidgets import QApplication
from scanatlas.app import Window,DownloadDialog,STYLE
from scanatlas.catalog import Catalog
from test_downloads import scan


def test_browsing_has_no_asset_requests_and_download_requires_connection(tmp_path,monkeypatch):
 monkeypatch.setattr('scanatlas.downloads.requests.Session.request',lambda *a,**k:(_ for _ in ()).throw(AssertionError('Browsing must not contact asset API')))
 app=QApplication.instance() or QApplication([]);app.setStyleSheet(STYLE)
 c=Catalog(tmp_path/'ui.sqlite');a=scan();a.update(kind='3D Assets',subtype='Rock',categories='3d nature rock',tags='rock stone',maxres=8192,preview='',tiny='');a['detail']['resolutions']=[1024,2048,4096,8192];c.upsert(a);c.c.commit()
 w=Window(c);w.images.online=False;w.show();app.processEvents()
 assert w.model.rowCount()==1
 w.search.setText('rock');w.refresh();app.processEvents();assert w.current['id']=='a'
 dialog=DownloadDialog(w,w.current);assert not dialog.start.isEnabled();assert dialog.plan['resolution']==2048
 w.tree_selected(w.tree.topLevelItem(0),0);assert w.kind=='3D Assets'
 w.toggle_favorite();assert c.query(scope='favorites')[1]==1
 w.close();app.processEvents()


def test_type_chips_combine_and_saved_search_restores(tmp_path,monkeypatch):
 import json
 from test_catalog import asset
 from PySide6.QtWidgets import QInputDialog
 app=QApplication.instance() or QApplication([])
 c=Catalog(tmp_path/'types.sqlite')
 for a in [asset('a','Grass'),asset('b','Grass Ground',kind='Surfaces'),asset('c','Grass Decal',kind='Decals')]:c.upsert(a)
 c.c.commit();w=Window(c);w.images.online=False;w.search.setText('grass');w.refresh()
 w.type_buttons['3D Plants'].click();assert w.total==1
 w.type_buttons['Surfaces'].click();assert w.total==2
 assert {r['kind'] for r in w.model.rows}=={'3D Plants','Surfaces'}
 assert not w.type_buttons[''].isChecked()
 monkeypatch.setattr(QInputDialog,'getText',lambda *a,**kw:('Grass selection',True))
 w.save_search();assert json.loads(c.collections()[0]['query'])['kinds']==['3D Plants','Surfaces']
 w.select_scope('');assert w.total==3 and w.type_buttons[''].isChecked()
 w.select_collection(w.collection_tree.topLevelItem(0),0);assert w.total==2
 assert w.type_buttons['3D Plants'].isChecked() and w.type_buttons['Surfaces'].isChecked()
 w.tree_selected(w.tree.topLevelItem(0),0);assert len(w.kinds)==1
 w.type_buttons[''].click();assert w.total==3 and not w.subtype
 w.close();app.processEvents()
