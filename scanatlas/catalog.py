from __future__ import annotations
import difflib
import json
import os
import re
import sqlite3
from pathlib import Path

DATA = Path(os.environ.get('SCANATLAS_DATA', Path.home() / '.local/share/scanatlas'))
TYPES = ['3D Assets', '3D Plants', 'Surfaces', 'Decals', 'Atlases', 'Brushes', 'Imperfections', 'Displacements', 'Characters', 'Animations', 'HDRIs', 'Other']
# Curated related concepts supplement source tags. They are not inferred visual labels.
CONCEPTS = [
 ['walk','walking','locomotion','stroll'], ['run','running','jog','sprint'],
 ['idle','standing','stand'], ['npc','character','characters','human','humanoid'],
 ['grass','grasses','grassy','lawn','turf','meadow','sedge','reeds','reed','hay'],
 ['rock','rocks','stone','boulder','cliff','gravel','pebble','sandstone'],
 ['wood','wooden','timber','lumber','plank','log','stump'],
 ['forest','woodland','undergrowth'], ['fern','ferns','bracken','fiddlehead'],
 ['moss','mossy','lichen'],
 ['leaf','leaves','leafy','foliage'], ['dirt','soil','mud','earth','ground'],
 ['damage','damaged','broken','cracked','crack','fractured'],
 ['metal','metallic','steel','iron','copper','aluminum'],
 ['snow','snowy','ice','icy','frost','frozen'],
 ['debris','rubble','rubbish','litter','trash'],
 ['dry','dried','dead','withered'], ['wet','damp','moist'],
 ['plant','plants','vegetation','botanical'],
 ['brick','bricks','masonry'], ['pavement','paving','sidewalk','cobblestone'],
]

def words(text):
 return re.findall(r'[\w]+', text.casefold(), flags=re.UNICODE)

def connection(path=None):
 path = Path(path or DATA / 'catalog.sqlite')
 path.parent.mkdir(parents=True, exist_ok=True)
 c = sqlite3.connect(path, timeout=30)
 c.row_factory = sqlite3.Row
 c.execute('PRAGMA journal_mode=WAL')
 c.execute('PRAGMA foreign_keys=ON')
 return c

class Catalog:
 def __init__(self, path=None):
  self.path = Path(path or DATA / 'catalog.sqlite')
  self.c = connection(self.path)
  self.c.executescript('''
CREATE TABLE IF NOT EXISTS assets(
 id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT, subtype TEXT, categories TEXT,
 tags TEXT, maxres INTEGER, preview TEXT, tiny TEXT, detail TEXT, local_path TEXT DEFAULT '');
CREATE VIRTUAL TABLE IF NOT EXISTS search USING fts5(id UNINDEXED,name,tags,categories, tokenize='porter unicode61');
CREATE VIRTUAL TABLE IF NOT EXISTS vocabulary USING fts5vocab(search,'row');
CREATE TABLE IF NOT EXISTS favorites(id TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS collections(id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, query TEXT);
CREATE TABLE IF NOT EXISTS members(collection_id INTEGER,asset_id TEXT, PRIMARY KEY(collection_id,asset_id),FOREIGN KEY(collection_id) REFERENCES collections(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS owned(id TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS downloads(id INTEGER PRIMARY KEY,asset_id TEXT,quality TEXT,path TEXT,status TEXT,created TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS assets_kind_subtype ON assets(kind,subtype);
CREATE INDEX IF NOT EXISTS assets_source ON assets(json_extract(detail,'$.source'));
CREATE INDEX IF NOT EXISTS downloads_asset ON downloads(asset_id);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);
''')
  self.c.commit()
  self._vocab = None
 def close(self): self.c.close()
 def source_clause(self):return "json_extract(detail,'$.source') IN ('huggingface','mixamo','polyhaven','ambientcg')" if self.setting('active_source')=='huggingface' else '1'
 def count(self): return self.c.execute('SELECT count(*) FROM assets WHERE '+self.source_clause()).fetchone()[0]
 def setting(self,key,default=''):
  row=self.c.execute('SELECT value FROM settings WHERE key=?',(key,)).fetchone()
  return row[0] if row else default
 def set_setting(self,key,value):
  self.c.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',(key,str(value)));self.c.commit()
 def get(self,asset_id):
  r=self.c.execute('SELECT * FROM assets WHERE id=? AND '+self.source_clause(),(asset_id,)).fetchone()
  if not r:return None
  d=dict(r);d['detail']=json.loads(d['detail']);return d
 def upsert(self, d):
  old=self.c.execute('SELECT rowid,local_path FROM assets WHERE id=?',(d['id'],)).fetchone()
  fields=['id','name','kind','subtype','categories','tags','maxres','preview','tiny','detail','local_path']
  values=[d.get(k,'') for k in fields]
  values[-2]=json.dumps(d['detail'],separators=(',',':'))
  if old:
   self.c.execute('DELETE FROM search WHERE rowid=?',(old[0],))
   if not values[-1]:values[-1]=old[1]
  self.c.execute('INSERT INTO assets('+','.join(fields)+') VALUES('+','.join('?' for _ in fields)+') ON CONFLICT(id) DO UPDATE SET '+','.join(f'{k}=excluded.{k}' for k in fields[1:]),values)
  rowid=self.c.execute('SELECT rowid FROM assets WHERE id=?',(d['id'],)).fetchone()[0]
  self.c.execute('INSERT INTO search(rowid,id,name,tags,categories) VALUES(?,?,?,?,?)',(rowid,d['id'],d['name'],d['tags'],d['categories']+' '+d['kind']))
  self._vocab=None
 def facets(self):
  return [tuple(r) for r in self.c.execute('SELECT kind,subtype,count(*) FROM assets WHERE '+self.source_clause()+' GROUP BY kind,subtype ORDER BY kind,subtype')]
 def query(self, text='',kind='',subtype='',scope='',collection=None,minres=0,sort='Relevance',limit=100,offset=0,related=True,kinds=None,source=''):
  text=text.strip()[:300]; notes=[]; params=[]; where=['a.maxres>=?',self.source_clause()];params.append(minres)
  join=''; rank=''
  exact_id = self.c.execute('SELECT id FROM assets WHERE lower(id)=?', (text.casefold(),)).fetchone() if text else None
  if exact_id:
   where.append('a.id=?');params.append(exact_id[0])
  if text and not exact_id:
   # Quoted phrases stay exact; every positive term/group must match.
   pieces=re.findall(r'(-?)"([^"]+)"|(-?)([\w]+)',text)
   groups=[];exclude=[]
   for minus,phrase,negative,token in pieces[:16]:
    if phrase:
     clean=' '.join(words(phrase)); clause='"'+clean+'"'
     if not clean:continue
    else:
     token=token.casefold(); terms=[token]
     if related and not negative:
      if self._vocab is None:self._vocab={r[0] for r in self.c.execute('SELECT term FROM vocabulary')}
      if token not in self._vocab and len(token)>3:
       close=difflib.get_close_matches(token,self._vocab,n=2,cutoff=.76)
       terms+=close;notes.extend(close)
      for family in CONCEPTS:
       if any(t in family for t in terms):terms+=family; notes.extend(t for t in family if t!=token);break
     clause='('+' OR '.join('"'+t+'"*' for t in dict.fromkeys(terms))+')'
    (exclude if minus or negative else groups).append(clause)
   if groups:
    match=' AND '.join(groups)
    for ex in exclude:match=f'({match}) NOT {ex}'
    join=' JOIN search ON search.rowid=a.rowid '
    where.append('search MATCH ?');params.append(match)
    rank='bm25(search,0,8,3,1)'
   else:
    where.append('(a.name LIKE ? OR a.id LIKE ?)');params += ['%'+text+'%']*2
  selected=list(dict.fromkeys(kinds or ([kind] if kind else [])))
  if selected:
   where.append('a.kind IN ('+','.join('?' for _ in selected)+')');params.extend(selected)
  if source:where.append("json_extract(a.detail,'$.source')=?");params.append(source)
  if subtype:where.append('a.subtype=?');params.append(subtype)
  if scope=='favorites':where.append('a.id IN (SELECT id FROM favorites)')
  if scope=='owned':where.append('a.id IN (SELECT id FROM owned)')
  if scope=='downloaded':where.append("(a.local_path<>'' OR a.id IN (SELECT asset_id FROM downloads WHERE status='complete'))")
  if scope=='my-assets':where.append("json_extract(a.detail,'$.my_asset')=1")
  if collection:where.append('a.id IN (SELECT asset_id FROM members WHERE collection_id=?)');params.append(collection)
  base=' FROM assets a '+join+' WHERE '+' AND '.join(where)
  total=self.c.execute('SELECT count(*)'+base,params).fetchone()[0]
  order={'Name A–Z':'a.name COLLATE NOCASE','Name Z–A':'a.name COLLATE NOCASE DESC','Highest resolution':'a.maxres DESC,a.name'}.get(sort)
  if not order:
   order=("CASE WHEN lower(a.name)=? OR lower(a.id)=? THEN 0 WHEN lower(a.name) LIKE ? THEN 1 ELSE 2 END,"+rank+',a.name') if rank else 'a.name COLLATE NOCASE'
  order+=',a.id' # Stable pagination when names/ranks tie.
  query_params=list(params)
  if rank and sort=='Relevance':query_params += [text.lower(),text.lower(),'%'+text.lower()+'%']
  rows=self.c.execute('SELECT a.id,a.name,a.kind,a.subtype,a.maxres,a.preview,a.tiny,json_extract(a.detail,"$.source") source,json_extract(a.detail,"$.catalog_only") catalog_only,EXISTS(SELECT 1 FROM favorites f WHERE f.id=a.id) favorite'+base+' ORDER BY '+order+' LIMIT ? OFFSET ?',query_params+[limit,offset]).fetchall()
  return [dict(r) for r in rows],total,list(dict.fromkeys(notes))
 def favorite(self,asset_id):
  exists=self.c.execute('SELECT 1 FROM favorites WHERE id=?',(asset_id,)).fetchone()
  self.c.execute('DELETE FROM favorites WHERE id=?' if exists else 'INSERT INTO favorites VALUES(?)',(asset_id,));self.c.commit()
  return not exists
 def collections(self):return [dict(r) for r in self.c.execute('SELECT * FROM collections ORDER BY name')]
 def collection(self,name,query=None):
  cur=self.c.execute('INSERT INTO collections(name,query) VALUES(?,?)',(name,query));self.c.commit();return cur.lastrowid
 def add_member(self,collection_id,asset_id):
  self.c.execute('INSERT OR IGNORE INTO members VALUES(?,?)',(collection_id,asset_id));self.c.commit()
 def set_owned(self,ids):
  with self.c:
   self.c.execute('DELETE FROM owned');self.c.executemany('INSERT OR IGNORE INTO owned VALUES(?)',((i,) for i in ids))
 def record_download(self,asset_id,quality,path):
  self.c.execute('INSERT INTO downloads(asset_id,quality,path,status) VALUES(?,?,?,?)',(asset_id,quality,str(path),'complete'));self.c.commit()
