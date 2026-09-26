"""Shared, bounded preview cache for the desktop and agent contact sheets."""
import hashlib,os,tempfile,threading,time
from pathlib import Path
from urllib.parse import urlparse
import requests
from .catalog import DATA

MAX_IMAGE=8*1024*1024
MAX_CACHE=256*1024*1024
_prune_lock=threading.Lock()
_last_prune=0
_validated={}

def cache_path(url,root=None):
 return Path(root or DATA/'previews')/(hashlib.sha256(url.encode()).hexdigest()+'.img')

def allowed(url):
 return url.startswith('https://') and (urlparse(url).hostname in {'cdn.polyhaven.com','acg-media.struffelproductions.com','ddinktqu5prvc.cloudfront.net','d99n9xvb9513w.cloudfront.net'} or (url.startswith('https://www.mixamo.com/api/v1/characters/') and '/assets/thumbnails/' in url and url.endswith('.png')) or url.startswith('https://huggingface.co/datasets/Sl8th/Megascans/resolve/'))

def prune(root):
 global _last_prune
 # No directory scan on launch or cache hits; at most once/minute after writes.
 with _prune_lock:
  if time.monotonic()-_last_prune<60:return
  _last_prune=time.monotonic()
  entries=[]
  for p in root.glob('*.img'):
   try:s=p.stat();entries.append((s.st_mtime,s.st_size,p))
   except FileNotFoundError:pass
  total=sum(size for _,size,_ in entries)
  for _,size,p in sorted(entries):
   if total<=MAX_CACHE:break
   p.unlink(missing_ok=True);total-=size

def resolve(url,root=None,fetch=True):
 """Only URLs already stored as catalog previews may be passed here."""
 if not url:return None,'missing'
 if url.startswith('/'):
  return (Path(url),'local_preview') if Path(url).is_file() else (None,'missing')
 target=cache_path(url,root)
 from PySide6.QtGui import QImage
 try:
  stat=target.stat();signature=(stat.st_size,stat.st_mtime_ns)
  if stat.st_size and (_validated.get(target)==signature or not QImage(str(target)).isNull()):
   os.utime(target,None);stat=target.stat();_validated[target]=(stat.st_size,stat.st_mtime_ns)
   return target,'cache'
  target.unlink(missing_ok=True);_validated.pop(target,None)
 except FileNotFoundError:pass
 if not fetch:return None,'not_cached'
 if not allowed(url):raise ValueError('Preview host is not supported')
 # Retry a temporary connection/CDN failure once, without caching failed responses.
 for attempt in range(2):
  try:
   with requests.get(url,stream=True,timeout=(5,12),headers={'User-Agent':'Atlas (asset preview cache)'}) as response:
    response.raise_for_status()
    if int(response.headers.get('Content-Length') or 0)>MAX_IMAGE:raise ValueError('Preview exceeds 8 MiB')
    data=bytearray()
    for chunk in response.iter_content(65536):
     data.extend(chunk)
     if len(data)>MAX_IMAGE:raise ValueError('Preview exceeds 8 MiB')
   break
  except requests.RequestException as error:
   temporary=isinstance(error,(requests.Timeout,requests.ConnectionError,requests.exceptions.ChunkedEncodingError)) or (isinstance(error,requests.HTTPError) and error.response is not None and error.response.status_code in {408,425,429,500,502,503,504})
   if attempt or not temporary:raise
   time.sleep(.2)
 image=QImage.fromData(bytes(data))
 if image.isNull():raise ValueError('Source did not return a readable preview image')
 target.parent.mkdir(parents=True,exist_ok=True)
 fd,name=tempfile.mkstemp(prefix='.preview-',dir=target.parent)
 try:
  with os.fdopen(fd,'wb') as stream:stream.write(data)
  os.replace(name,target)
  stat=target.stat();_validated[target]=(stat.st_size,stat.st_mtime_ns)
 finally:Path(name).unlink(missing_ok=True)
 prune(target.parent)
 return target,'online_preview'
