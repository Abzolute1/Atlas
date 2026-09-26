import pytest
from scanatlas.catalog import Catalog
from scanatlas.public_sources import sync_polyhaven,sync_ambientcg,hydrate,PublicClient
from scanatlas.downloads import build_plan

def test_official_catalog_and_lazy_plan(tmp_path,monkeypatch):
 c=Catalog(tmp_path/'db');c.set_setting('active_source','huggingface')
 monkeypatch.setattr('scanatlas.public_sources.get',lambda url:{'grass':{'name':'Grass','type':1,'categories':['ground'],'tags':['grass'],'max_resolution':[8192,8192]}})
 assert sync_polyhaven(c)['indexed_assets']==1
 a=c.get('polyhaven_grass');assert a and c.query(source='polyhaven')[1]==1 and not c.query(source='ambientcg')[1]
 with pytest.raises(ValueError,match='metadata'):build_plan(a,'Medium')
 monkeypatch.setattr('scanatlas.public_sources.get',lambda url:{'Diffuse':{'2k':{'jpg':{'url':'https://dl.polyhaven.org/file/grass.jpg','size':42}}}})
 a=hydrate(c,a);p=build_plan(a,'Medium');assert p['bytes']==42 and p['resolution']==2048
 with pytest.raises(ValueError):build_plan(a,'Low')
 assert not c.get(a['id'])['detail']['manifest_pending']

def test_package_quality_and_unknown(tmp_path,monkeypatch):
 c=Catalog(tmp_path/'db')
 monkeypatch.setattr('scanatlas.public_sources.get',lambda url:{'foundAssets':[{'assetId':'A','dataType':'Material','downloadFolders':{'x':[{'fileName':'A_2K-JPG.zip','downloadLink':'https://ambientcg.com/get?file=A_2K-JPG.zip','size':99},{'fileName':'A_4K-JPG.zip','downloadLink':'https://ambientcg.com/get?file=A_4K-JPG.zip','size':999}]}}]})
 sync_ambientcg(c);a=c.get('ambientcg_A');assert build_plan(a,'Medium')['bytes']==99
 a['detail']['files'][0]['resolution']=0
 with pytest.raises(ValueError):build_plan(a,'Medium')

def test_public_url_validation(tmp_path):
 with pytest.raises(ValueError,match='host'):
  PublicClient().download({'detail':{'source':'polyhaven'}},{'files':[{'name':'bad','url':'http://127.0.0.1/file'}]},tmp_path)

def test_pagination_preserves_download_metadata(tmp_path,monkeypatch):
 c=Catalog(tmp_path/'db');urls=[]
 def fetch(url):
  urls.append(url)
  if len(urls)==1:return {'foundAssets':[],'nextPageHttp':'https://ambientcg.com/api/v2/full_json?offset=250&include=fileData'}
  assert 'downloadData%2CimageData' in url
  return {'foundAssets':[]}
 monkeypatch.setattr('scanatlas.public_sources.get',fetch)
 sync_ambientcg(c);assert len(urls)==2
