import json
from types import SimpleNamespace
from threading import Event
import pytest
from scanatlas.catalog import Catalog
from scanatlas.web_catalog import category_tiles,Bridge
from test_catalog import asset

@pytest.fixture
def catalog(tmp_path):
 c=Catalog(tmp_path/'catalog.sqlite')
 def add(id,kind,subtype,source='polyhaven',local=False,remote=False,preview=True):
  a=asset(id,id,kind=kind,subtype=subtype);a['detail'].update(source=source,catalog_only=remote)
  a['preview']='https://cdn.polyhaven.com/'+id+'.png' if preview else ''
  if local:a['local_path']='/local/'+id
  c.upsert(a)
 add('public-grass','Surfaces','Grass');add('local-grass','Surfaces','Grass',local=True)
 add('stone','Surfaces','Stone');add('unpictured','Surfaces','Stone',preview=False)
 add('swat','Characters','Mixamo','mixamo',remote=True)
 add('legacy','3D Assets','Rock','quixel')
 c.set_setting('active_source','huggingface');c.c.commit()
 yield c
 c.close()

def test_overviews_use_real_counts_and_prefer_local_representatives(catalog):
 before=catalog.c.total_changes
 tiles=category_tiles(catalog,{},catalog.facets())
 assert [(t['label'],t['count']) for t in tiles]==[('Surfaces',4),('Characters',1)]
 assert tiles[0]['id']=='local-grass' and tiles[0]['preview'].endswith('local-grass.png')
 subtypes=category_tiles(catalog,{'types':['Surfaces']},catalog.facets())
 assert [(t['subtype'],t['count']) for t in subtypes]==[('Grass',2),('Stone',2)]
 assert category_tiles(catalog,{'types':['Characters']},catalog.facets())==[]
 assert catalog.c.total_changes==before

@pytest.mark.parametrize('filters',[{'query':'grass'},{'source':'polyhaven'},{'scope':'my-assets'},{'collection':1},{'subtype':'Grass'},{'offset':60},{'types':['Surfaces','Characters']}])
def test_overviews_do_not_appear_in_filtered_results(catalog,filters):
 assert category_tiles(catalog,filters,catalog.facets())==[]

def test_overviews_are_bounded_and_omit_categories_without_previews(catalog):
 for n in range(20):
  a=asset('extra'+str(n),'Extra',kind='Kind'+str(n));a['detail']['source']='polyhaven';a['preview']='https://cdn.polyhaven.com/extra.png';catalog.upsert(a)
 a=asset('blank','Blank',kind='No preview');a['detail']['source']='polyhaven';catalog.upsert(a);catalog.c.commit()
 tiles=category_tiles(catalog,{},catalog.facets())
 assert len(tiles)==12 and all(t['preview'] and t['kind']!='No preview' for t in tiles)

def test_bridge_filters_subtype_and_keeps_category_preview_jobs(catalog):
 output=[];tile_job=SimpleNamespace(asset_id='swat',cancel=Event());other_job=SimpleNamespace(asset_id='gone',cancel=Event())
 fake=SimpleNamespace(w=SimpleNamespace(native=SimpleNamespace(catalog=catalog),preview_jobs=[tile_job,other_job]),send=lambda action,**values:output.append(dict(action=action,**values)))
 Bridge.request(fake,json.dumps({'action':'search','types':['Surfaces'],'subtype':'Stone','request':1}))
 assert output[-1]['total']==2 and {a['id'] for a in output[-1]['items']}=={'stone','unpictured'}
 assert output[-1]['browse_categories']==[]
 for n in range(65):
  a=asset('filler'+str(n),'A filler '+str(n),kind='Surfaces',subtype='Grass');a['detail']['source']='polyhaven';catalog.upsert(a)
 catalog.c.commit()
 tile_job.cancel.clear();Bridge.request(fake,json.dumps({'action':'search','request':2}))
 assert len(output[-1]['items'])==60 and 'swat' not in {a['id'] for a in output[-1]['items']}
 assert not tile_job.cancel.is_set() and other_job.cancel.is_set()
 assert len(output[-1]['browse_categories'])==2
