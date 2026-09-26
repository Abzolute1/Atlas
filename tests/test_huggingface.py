import pytest
from scanatlas.catalog import Catalog
from scanatlas.huggingface import HuggingFaceClient, sources
from scanatlas.agent import describe
from test_catalog import asset

def test_source_scope_hides_unavailable_metadata(tmp_path):
 c=Catalog(tmp_path/'test.sqlite')
 a=asset('legacy','Grass');b=asset('hf_a','Grass');b['detail'].update(source='huggingface',quixel_id='a',license='Unstated')
 c.upsert(a);c.upsert(b);c.c.commit();c.set_setting('active_source','huggingface')
 assert c.count()==1 and c.get('legacy') is None
 assert c.query('grass')[1]==1
 assert sum(row[2] for row in c.facets())==1
 assert describe(c,c.get('hf_a'))['duplicate_key']=='quixel:a'
 assert all(x['status']=='listing_only' and not x['download_available'] for x in sources(c) if x['id'].startswith('cger-'))
 c.close()

def test_hf_rejects_unexpected_payload_host(tmp_path):
 with pytest.raises(ValueError,match='Unexpected'):
  HuggingFaceClient().download({'detail':{'revision':'abc'}},{'files':[{'name':'a','url':'https://other.example/a'}]},tmp_path)
