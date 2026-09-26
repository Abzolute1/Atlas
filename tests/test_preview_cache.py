import pytest
import requests
from PySide6.QtGui import QImage,QColor
from scanatlas.preview_cache import resolve,cache_path,MAX_IMAGE

class Response:
 def __init__(self,data):self.data=data;self.headers={}
 def __enter__(self):return self
 def __exit__(self,*args):pass
 def raise_for_status(self):pass
 def iter_content(self,n):yield self.data


def test_shared_cache_reuses_first_fetch_without_network(tmp_path,monkeypatch):
 im=QImage(32,32,QImage.Format_RGB32);im.fill(QColor('red'));im.save(str(tmp_path/'source.png'))
 url='https://cdn.polyhaven.com/test-thumb.png';calls=[]
 def request(*args,**kwargs):calls.append(args);return Response((tmp_path/'source.png').read_bytes())
 monkeypatch.setattr('scanatlas.preview_cache.requests.get',request)
 root=tmp_path/'cache'
 path,status=resolve(url,root);assert status=='online_preview' and not QImage(str(path)).isNull()
 assert resolve(url,root)==(path,'cache')
 assert resolve(url,root,fetch=False)==(path,'cache')
 assert len(calls)==1


def test_bad_and_oversized_responses_are_not_cached(tmp_path,monkeypatch):
 url='https://cdn.polyhaven.com/test-invalid.png'
 monkeypatch.setattr('scanatlas.preview_cache.requests.get',lambda *a,**kw:Response(b'not an image'))
 with pytest.raises(ValueError,match='readable'):resolve(url,tmp_path)
 assert not cache_path(url,tmp_path).exists()
 monkeypatch.setattr('scanatlas.preview_cache.requests.get',lambda *a,**kw:Response(b'x'*(MAX_IMAGE+1)))
 with pytest.raises(ValueError,match='8 MiB'):resolve(url,tmp_path)
 assert not cache_path(url,tmp_path).exists()


def test_local_and_offline_never_fetch(tmp_path,monkeypatch):
 def fail(*a,**kw):raise AssertionError('Network request was unexpected')
 monkeypatch.setattr('scanatlas.preview_cache.requests.get',fail)
 local=tmp_path/'render.png';local.write_bytes(b'local')
 assert resolve(str(local),tmp_path)==(local,'local_preview')
 assert resolve('https://cdn.polyhaven.com/uncached.png',tmp_path,False)==(None,'not_cached')
 with pytest.raises(ValueError,match='host'):resolve('https://unrelated.example/asset.zip',tmp_path)


def test_corrupt_cache_is_replaced_and_offline_does_not_fetch(tmp_path,monkeypatch):
 url='https://cdn.polyhaven.com/corrupt.png';target=cache_path(url,tmp_path)
 target.write_bytes(b'broken image')
 monkeypatch.setattr('scanatlas.preview_cache.requests.get',lambda *a,**kw:pytest.fail('Offline must not fetch'))
 assert resolve(url,tmp_path,False)==(None,'not_cached')
 assert not target.exists()
 target.write_bytes(b'broken image')
 im=QImage(8,8,QImage.Format_RGB32);im.fill(QColor('blue'));im.save(str(tmp_path/'valid.png'))
 monkeypatch.setattr('scanatlas.preview_cache.requests.get',lambda *a,**kw:Response((tmp_path/'valid.png').read_bytes()))
 path,status=resolve(url,tmp_path)
 assert status=='online_preview' and not QImage(str(path)).isNull()


@pytest.mark.parametrize('failure',['timeout','503','404'])
def test_retry_only_temporary_errors_once(tmp_path,monkeypatch,failure):
 calls=[];im=QImage(8,8,QImage.Format_RGB32);im.fill(QColor('blue'));im.save(str(tmp_path/'valid.png'))
 def request(*a,**kw):
  calls.append(a)
  if len(calls)==1:
   if failure=='timeout':raise requests.Timeout('temporary timeout')
   response=requests.Response();response.status_code=int(failure)
   raise requests.HTTPError(response=response)
  return Response((tmp_path/'valid.png').read_bytes())
 monkeypatch.setattr('scanatlas.preview_cache.requests.get',request)
 monkeypatch.setattr('scanatlas.preview_cache.time.sleep',lambda _:None)
 if failure=='404':
  with pytest.raises(requests.HTTPError):resolve('https://cdn.polyhaven.com/retry.png',tmp_path)
  assert len(calls)==1
 else:
  assert resolve('https://cdn.polyhaven.com/retry.png',tmp_path)[1]=='online_preview'
  assert len(calls)==2


def test_retry_stops_after_second_failure(tmp_path,monkeypatch):
 calls=[]
 def request(*a,**kw):calls.append(a);raise requests.ConnectionError('offline')
 monkeypatch.setattr('scanatlas.preview_cache.requests.get',request)
 monkeypatch.setattr('scanatlas.preview_cache.time.sleep',lambda _:None)
 with pytest.raises(requests.ConnectionError):resolve('https://cdn.polyhaven.com/retry.png',tmp_path)
 assert len(calls)==2
