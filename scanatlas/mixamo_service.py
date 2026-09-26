"""Mixamo session helper: independent of the Atlas catalog window."""
import os,subprocess,sys,time,socket
from pathlib import Path
from .mixamo_bridge import endpoint

def available(path):
 try:
  with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as s:s.settimeout(.1);s.connect(path)
  return True
 except (FileNotFoundError,ConnectionRefusedError,socket.timeout):return False

def ensure(database):
 path=endpoint(database)
 if available(path):return
 # Serialize simultaneous MCP clients, and never launch a shell.
 import fcntl
 with open(path+'.lock','a') as lock:
  os.chmod(path+'.lock',0o600);fcntl.flock(lock,fcntl.LOCK_EX)
  if available(path):return
  process=subprocess.Popen([sys.executable,'-m','scanatlas.mixamo_service','--database',str(Path(database).resolve())],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
  for _ in range(150):
   if available(path):return
   if process.poll() is not None:raise RuntimeError('Mixamo background service could not start. Run atlas mixamo-service to see startup diagnostics.')
   time.sleep(.1)
  raise RuntimeError('Mixamo background service did not become ready. Run atlas mixamo-service for diagnostics.')

def main(database=None):
 if database is None:
  import argparse
  parser=argparse.ArgumentParser();parser.add_argument('--database',type=Path);database=parser.parse_args().database
 if not os.environ.get('DISPLAY') and not os.environ.get('WAYLAND_DISPLAY'):os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
 from PySide6.QtWidgets import QApplication
 from PySide6.QtCore import QTimer
 from .catalog import Catalog
 from .mixamo_browser import MixamoBrowser
 from .app import STYLE
 app=QApplication(sys.argv[:1]);app.setApplicationName('Atlas Mixamo service');app.setQuitOnLastWindowClosed(False);app.setStyle('Fusion');app.setStyleSheet(STYLE)
 c=Catalog(database);browser=MixamoBrowser(None,c)
 if not browser.agent_bridge.available:c.close();return
 app.aboutToQuit.connect(browser.shutdown)
 app.exec();c.close()

if __name__=='__main__':main()
