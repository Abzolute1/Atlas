import pytest,json
from scanatlas.catalog import Catalog
from scanatlas.mixamo_catalog import record,sync,export,reconcile,select
from scanatlas.mixamo import import_fbx,stage
from scanatlas.agent import describe,brief


def product(id='motion-1',name='Rifle Run',kind='Motion'):
 return dict(id=id,type=kind,name=name,description='Running with a rifle',category='',thumbnail=f'https://d99n9xvb9513w.cloudfront.net/thumbnails/motions/{id}/static.png',thumbnail_animated=f'https://d99n9xvb9513w.cloudfront.net/thumbnails/motions/{id}/animated.gif')


def response(items,total=None,pages=1):
 return {'results':items,'pagination':{'num_results':len(items) if total is None else total,'num_pages':pages}}


def test_remote_entries_are_browsable_but_not_local_files(tmp_path,monkeypatch):
 c=Catalog(tmp_path/'db');a=record(product(),'today');c.upsert(a);c.c.commit()
 assert c.query('rifle',source='mixamo')[1]==1 and c.query(scope='downloaded')[1]==0
 for d in [describe(c,a,True),brief(a)]:
  assert d['availability']['state']=='remote_catalog' and d['next_action']=='mixamo-export'
 assert describe(c,a)['download_access']=='mixamo_session'
 with pytest.raises(ValueError,match='catalog entry'):stage(c,[a['id']],tmp_path/'staged',True)
 def fail(*args,**kwargs):raise AssertionError('Dry-run must not touch Mixamo session')
 monkeypatch.setattr('scanatlas.mixamo_bridge.call',fail)
 assert export(c,a,tmp_path)['dry_run']
 assert not (tmp_path/'staged').exists()


def test_sync_unions_repeated_pages_and_preserves_local_import(tmp_path,monkeypatch):
 c=Catalog(tmp_path/'db');p=tmp_path/'local.fbx';p.write_bytes(b'Kaydara FBX Binary local test');local=import_fbx(c,p,'Characters')
 count=0
 def page(kind,number=1,**kwargs):
  nonlocal count
  if kind=='Character':return response([product('char','Soldier','Character')])
  count+=1
  # The second sweep fills a product missed by unstable source pagination.
  return response([product('a') if count<3 else product('b')],total=2,pages=2)
 monkeypatch.setattr('scanatlas.mixamo_catalog.page',page)
 r=sync(c);assert r['indexed_assets']==3 and count==3
 assert c.get(local['id']) and c.count()==4
 assert c.query(scope='downloaded')[1]==1


def test_partial_sync_leaves_previous_index_intact(tmp_path,monkeypatch):
 c=Catalog(tmp_path/'db');a=record(product(),'before');c.upsert(a);c.c.commit()
 monkeypatch.setattr('scanatlas.mixamo_catalog.page',lambda *a,**kw:response([product('duplicate')],total=2,pages=1))
 with pytest.raises(ValueError,match='incomplete'):sync(c)
 assert c.count()==1 and c.get(a['id'])['detail']['indexed_at']=='before'


def test_selection_uses_exact_reference_for_duplicate_names(tmp_path,monkeypatch):
 c=Catalog(tmp_path/'db');a=record(product('second'),'today')
 monkeypatch.setattr('scanatlas.mixamo_catalog.page',lambda *a,**kw:response([product('first'),product('second')]))
 calls=[]
 def bridge(db,action,**args):
  calls.append((action,args))
  if action=='select':return {'selection':'Rifle Run on Swat Guy'}
  return {'state':'ready','jobs':{},'items':[{'ref':'motions:first'},{'ref':'motions:second'}]}
 result=select(c,a,bridge);assert result['source_ref']=='motions:second'
 assert calls[-1]==('select',{'ref':'motions:second'})


def test_reconcile_preserves_import_and_attaches_catalog_identity(tmp_path):
 c=Catalog(tmp_path/'db');remote=record(product(),'today');c.upsert(remote);c.c.commit()
 p=tmp_path/'download.fbx';p.write_bytes(b'Kaydara FBX Binary imported animation');a=import_fbx(c,p,'Animations')
 c.c.execute('CREATE TABLE mixamo_catalog_exports(job_id TEXT PRIMARY KEY,catalog_id TEXT,character_id TEXT,imported_id TEXT)')
 c.c.execute('INSERT INTO mixamo_catalog_exports(job_id,catalog_id) VALUES(?,?)',('job',remote['id']));c.c.commit()
 reconcile(c,{'job':{'status':'complete','asset_id':a['id'],'plan':{'selection':'Rifle Run on Soldier'}}})
 updated=c.get(a['id']);assert updated['detail']['catalog_id']==remote['id']
 assert updated['detail']['sha256']==a['detail']['sha256'] and updated['preview']==remote['preview']
 assert updated['name']=='Rifle Run on Soldier' and c.query(scope='downloaded')[1]==1
