import json
import pytest
from scanatlas.agent import describe,preview,new_job,tracked_download,job_schema
from scanatlas.catalog import Catalog
from scanatlas.downloads import build_plan
from test_downloads import scan

@pytest.fixture
def catalog(tmp_path):
 c=Catalog(tmp_path/'agent.sqlite');a=scan();a.update(kind='3D Assets',subtype='Rock',categories='rock',tags='rock',maxres=8192,preview='',tiny='');c.upsert(a);c.c.commit();yield c;c.close()

def test_metadata_size_and_file_plan(catalog):
 a=describe(catalog,catalog.get('a'),True)
 assert not a['ownership']['checked_live']
 assert a['qualities']['High']['file_count']>0
 assert a['qualities']['High']['size_bytes']==sum(f['size'] for f in a['qualities']['High']['files'])

def test_vision_manifest_no_network(catalog,tmp_path,monkeypatch):
 monkeypatch.setattr('requests.get',lambda *a,**kw:pytest.fail('Preview must not fetch without flag'))
 result=preview(catalog,['a'],tmp_path/'sheet.png')
 assert result['items'][0]['id']=='a'
 assert result['items'][0]['bounds_xywh']==[0,0,800,650]
 assert result['items'][0]['preview_source']=='unavailable'
 assert json.loads((tmp_path/'sheet.json').read_text())['schema']=='atlas.v1'
 assert (tmp_path/'sheet.png').stat().st_size>100
 with pytest.raises(FileExistsError):preview(catalog,['a'],tmp_path/'sheet.png')

def test_download_failure_and_cancel_status(catalog,tmp_path):
 a=catalog.get('a');p=build_plan(a,'High')
 class Failed:
  def download(self,*args):raise PermissionError('Not acquired')
 with pytest.raises(PermissionError):tracked_download(catalog,a,p,tmp_path,Failed())
 row=catalog.c.execute('SELECT * FROM agent_jobs').fetchone();assert row['status']=='failed' and row['error']=='Not acquired'
 class Cancelled:
  def download(self,a,p,d,progress,cancel):
   assert cancel();raise InterruptedError('cancelled')
 j=new_job(catalog,a,p,tmp_path);catalog.c.execute('UPDATE agent_jobs SET cancel_requested=1 WHERE id=?',(j,));catalog.c.commit()
 with pytest.raises(InterruptedError):tracked_download(catalog,a,p,tmp_path,Cancelled(),job_id=j)
 assert catalog.c.execute('SELECT status FROM agent_jobs WHERE id=?',(j,)).fetchone()[0]=='cancelled'

def test_complete_job_persists_real_paths(catalog,tmp_path):
 a=catalog.get('a');p=build_plan(a,'High')
 class Completed:
  def download(self,a,p,d,progress,cancel):
   for f in p['files']:
    path=tmp_path/f['name'];path.parent.mkdir(exist_ok=True,parents=True);path.write_bytes(b'abc')
   progress(3*len(p['files']),p['bytes'],'last');return str(tmp_path)
 tracked_download(catalog,a,p,tmp_path,Completed())
 row=catalog.c.execute('SELECT * FROM agent_jobs').fetchone()
 assert row['status']=='complete' and row['bytes_done']==3*len(p['files'])
 assert describe(catalog,a)['downloads'][0]['path_exists']
