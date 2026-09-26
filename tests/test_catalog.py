import json
import pytest
from scanatlas.catalog import Catalog

def asset(id,name,tags='',kind='3D Plants',subtype='Grass',res=4096):
 return dict(id=id,name=name,kind=kind,subtype=subtype,categories=kind+' / '+subtype,tags=tags,maxres=res,preview='',tiny='',detail={'files':[]})

@pytest.fixture
def db(tmp_path):
 c=Catalog(tmp_path/'test.sqlite')
 for a in [asset('a1','Wild Grass','grass green'),asset('b2','Meadow Turf','lawn meadow',subtype='Turf'),asset('c3','Dry Grass','grass dry'),asset('d4','Concrete Wall','concrete',kind='Surfaces',subtype='Concrete'),asset('e5','Grass Covered Ground','grass soil',kind='Surfaces',subtype='Ground',res=2048)]:c.upsert(a)
 c.c.commit();yield c;c.close()

def ids(result):return {a['id'] for a in result[0]}

def test_rank_and_related_concepts(db):
 result=db.query('grass');assert result[1]==4
 assert 'b2' in ids(result)
 assert result[0][-1]['id']=='b2' # exact-name fragments rank before related results
 assert db.query('grass',related=False)[1]==3

def test_typo_and_id(db):
 assert db.query('grsas')[1]>=3
 assert ids(db.query('A1'))=={'a1'}

def test_filters_phrases_and_exclusions(db):
 assert ids(db.query('grass',kind='Surfaces',minres=4096))==set()
 assert ids(db.query('"dry grass"'))=={'c3'}
 assert 'c3' not in ids(db.query('grass -dry'))
 assert ids(db.query('dry grass'))=={'c3'}
 for q in ['*','"','OR','grass" OR 1=1 --','(((((','-dry']:
  db.query(q)

def test_collections_favorites_and_persistence(db):
 cid=db.collection('Ground');db.add_member(cid,'e5');db.favorite('a1')
 assert ids(db.query(collection=cid))=={'e5'}
 assert ids(db.query(scope='favorites'))=={'a1'}
 db.set_owned({'b2'});assert ids(db.query(scope='owned'))=={'b2'}
 db.record_download('c3','Low','/test');assert ids(db.query(scope='downloaded'))=={'c3'}
 reopened=Catalog(db.path);assert reopened.collections()[0]['name']=='Ground';reopened.close()

def test_update_does_not_duplicate_fts_or_lose_local_path(db):
 a=asset('a1','Changed Grass');a['local_path']='/owned/library';db.upsert(a);db.c.commit()
 db.upsert(asset('a1','New Grass'));db.c.commit()
 assert db.count()==5
 assert db.get('a1')['local_path']=='/owned/library'
 assert db.c.execute('SELECT count(*) FROM search').fetchone()[0]==5

def test_pagination_sort(db):
 first=db.query(limit=2,sort='Name A–Z');second=db.query(limit=2,offset=2,sort='Name A–Z')
 assert first[1]==5 and not ids(first)&ids(second)


def test_multiple_types_are_union_with_other_filters(db):
 assert ids(db.query('grass',kinds=['3D Plants','Surfaces']))=={'a1','b2','c3','e5'}
 assert ids(db.query('grass',kinds=['3D Plants','Surfaces'],minres=4096))=={'a1','b2','c3'}
 assert ids(db.query('grass',kinds=['Surfaces','Decals']))=={'e5'}
 assert ids(db.query('grass',kinds=["Surfaces') OR 1=1 --"]))==set()
 db.favorite('e5');assert ids(db.query('grass',kinds=['3D Plants','Surfaces'],scope='favorites'))=={'e5'}
