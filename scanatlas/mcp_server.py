"""Stdio MCP adapter for narrow Atlas commands, backed by the same JSON CLI."""
import json,subprocess,sys
TOOLS={
 'atlas_unity_configure':{'description':'Connect a Unity project and install the Atlas Editor importer plus the optional Unity Pipeline CLI package when available. Existing assets/scenes are preserved. New open projects are detected automatically.','properties':{'project':{'type':'string'}},'required':['project']},
 'atlas_unity_import':{'description':'Import downloaded Atlas assets into Unity. Dry-run unless execute=true. Uses the sole open Unity project by default, otherwise the saved project; pass project to choose explicitly. Copies assets, safely extracts ZIPs, queues materials/rigs/prefabs; no scene edits. Unity must open the target project to process the queue. Poll atlas_unity_status; queued is not complete.','properties':{'id':{'type':'string'},'project':{'type':'string'},'quality':{'type':'string','enum':['Low','Medium','High','Ultra']},'source':{'type':'string'},'rig':{'type':'string','enum':['auto','generic','humanoid','none']},'execute':{'type':'boolean'}},'required':['id']},
 'atlas_unity_status':{'description':'Read durable Unity import reports: queued/processing/complete/failed, material/prefab paths and warnings. Works with Atlas UI closed.','properties':{'job':{'type':'string'},'project':{'type':'string'}}},
 'atlas_mixamo_export':{'description':'Export one indexed Mixamo catalog ID through the signed-in background session. Dry-run unless execute=true. Optional character must be a downloaded character with a verified catalog link. Poll atlas_mixamo_status for transfer completion.','properties':{'id':{'type':'string'},'destination':{'type':'string'},'character':{'type':'string'},'execute':{'type':'boolean'}},'required':['id','destination']},
 'atlas_mixamo_catalog_sync':{'description':'Refresh the full Mixamo metadata index. No FBX downloads.','properties':{}},
 'atlas_search':{'description':'Search Atlas without opening its UI. Use scope=my-assets for saved personal assets such as FPS arms. Returns IDs, source, previews and file metadata.','properties':{'query':{'type':'string'},'source':{'type':'string'},'scope':{'type':'string','enum':['favorites','owned','downloaded','my-assets']},'types':{'type':'array','items':{'type':'string'}},'limit':{'type':'integer','minimum':1,'maximum':100}}},
 'atlas_inspect':{'description':'Inspect a catalog asset by returned ID.','properties':{'id':{'type':'string'}},'required':['id']},
 'atlas_plan':{'description':'Resolve exact selected files and size without downloading assets.','properties':{'id':{'type':'string'},'quality':{'type':'string','enum':['Low','Medium','High','Ultra']}},'required':['id']},
 'atlas_download':{'description':'Plan or download one catalog asset to an existing destination folder. Default Medium/2K, dry run unless execute=true. Execution returns a background job; poll atlas_status.','properties':{'id':{'type':'string'},'destination':{'type':'string'},'quality':{'type':'string','enum':['Low','Medium','High','Ultra']},'execute':{'type':'boolean'}},'required':['id','destination']},
 'atlas_status':{'description':'Read durable catalog download progress, errors and final paths.','properties':{'job':{'type':'string'},'asset':{'type':'string'}}},
 'atlas_preview':{'description':'Create a labeled contact sheet for up to 24 catalog IDs. fetch_previews retrieves only thumbnails.','properties':{'ids':{'type':'array','items':{'type':'string'},'minItems':1,'maxItems':24},'output':{'type':'string'},'fetch_previews':{'type':'boolean'}},'required':['ids','output']},
 'atlas_stage':{'description':'Plan or copy imported Mixamo FBXs into a NEW staging directory, checking hashes.','properties':{'ids':{'type':'array','items':{'type':'string'},'minItems':1},'destination':{'type':'string'},'execute':{'type':'boolean'}},'required':['ids','destination']},
 'atlas_mixamo_connect':{'description':'Open the background Mixamo service sign-in window for the user. Closing the window hides it; Atlas catalog UI is not needed.','properties':{}},
 'atlas_mixamo_status':{'description':'Read Mixamo browser readiness, visible cards, selection, export settings and agent download jobs. Auto-starts the background Mixamo service. The user must sign in once per service session. No credentials returned.','properties':{}},
 'atlas_mixamo_search':{'description':'Search Mixamo in the signed-in Atlas session. Inspect returned state and settled fields; ready is a UI observation, not an entitlement check.','properties':{'query':{'type':'string'},'type':{'type':'string','enum':['Characters','Animations']},'page':{'type':'integer','minimum':1}},'required':['query']},
 'atlas_mixamo_select':{'description':'Select a ref returned by the current Mixamo search page.','properties':{'ref':{'type':'string'}},'required':['ref']},
 'atlas_mixamo_prepare_download':{'description':'Open export options for the selected character/animation; no files downloaded.','properties':{}},
 'atlas_mixamo_download':{'description':'Plan or execute the selected Mixamo FBX export and automatically catalog it. execute defaults false. Size is unknown until transfer; Original quality only. Poll status for completion and asset_id.','properties':{'destination':{'type':'string'},'type':{'type':'string','enum':['Characters','Animations']},'character':{'type':'string'},'execute':{'type':'boolean'}},'required':['destination']},
 'atlas_mixamo_preview':{'description':'Save the ready Mixamo view as a PNG for vision; refuses login pages.','properties':{'output':{'type':'string'}},'required':['output']},
}
def command(name,a):
 if name not in TOOLS:raise ValueError('Unknown tool')
 if name=='atlas_unity_configure':return ['unity-configure',a['project']]
 if name=='atlas_unity_status':return ['unity-status']+(['--job',a['job']] if a.get('job') else [])+(['--project',a['project']] if a.get('project') else [])
 if name=='atlas_unity_import':
  args=['unity-import',a['id'],'--quality',a.get('quality','Medium'),'--rig',a.get('rig','auto')]
  for flag in ('project','source'):
   if a.get(flag):args+=['--'+flag,a[flag]]
  return args+(['--execute'] if a.get('execute') else [])
 if name=='atlas_mixamo_catalog_sync':return ['sync-mixamo']
 if name=='atlas_mixamo_export':return ['mixamo-export',a['id'],'--destination',a['destination']]+(['--character',a['character']] if a.get('character') else [])+(['--execute'] if a.get('execute') else [])
 if name=='atlas_search':
  args=['search',a.get('query',''),'--brief','--limit',str(a.get('limit',20))]
  if a.get('source'):args+=['--source',a['source']]
  if a.get('scope'):args+=['--scope',a['scope']]
  for t in a.get('types',[]):args+=['--type',t]
  return args
 if name=='atlas_download':
  return ['download',a['id'],'--destination',a['destination'],'--quality',a.get('quality','Medium')]+(['--execute','--background'] if a.get('execute') else [])
 if name=='atlas_status':return ['status']+(['--job',a['job']] if a.get('job') else [])+(['--asset',a['asset']] if a.get('asset') else [])
 if name=='atlas_preview':return ['preview',*a['ids'],'--output',a['output']]+(['--fetch-previews'] if a.get('fetch_previews') else [])
 if name=='atlas_stage':return ['stage',*a['ids'],'--destination',a['destination']]+(['--execute'] if a.get('execute') else [])
 if name=='atlas_inspect':return ['inspect',a['id']]
 if name=='atlas_plan':return ['plan',a['id'],'--quality',a.get('quality','Medium')]
 action=name.removeprefix('atlas_mixamo_').replace('_','-');args=['mixamo',action]
 if action=='search':args += [a.get('query',''),'--type',a.get('type','Animations'),'--page',str(a.get('page',1))]
 if action=='select':args += [a['ref']]
 if action=='preview':args += ['--output',a['output']]
 if action=='download':
  args += ['--destination',a['destination'],'--type',a.get('type','Animations')]
  if a.get('character'):args+=['--character',a['character']]
  if a.get('execute'):args+=['--execute']
 return args

def serve(database=None):
 for line in sys.stdin:
  try:
   req=json.loads(line);ident=req.get('id');method=req.get('method')
   if ident is None:continue
   if method=='initialize':result={'protocolVersion':'2024-11-05','capabilities':{'tools':{}},'serverInfo':{'name':'atlas','version':'0.6.2'},'instructions':'Atlas catalog commands work without a UI. Mixamo local search includes the full online catalog plus downloaded imports. availability.state=remote_catalog means use atlas_mixamo_export, not stage. Stage only local_file assets. Animation packs are listings; export individual clips. For personal FPS arms search scope=my-assets, inspect the returned ID and source_detail, then stage the complete package and read CODEX_README.md. Mixamo commands auto-start a background session: connect opens Adobe sign-in for the user, status checks readiness. Search returns current-page refs, select then prepare_download, inspect options, dry-run download then execute. Never claim rig compatibility before Unity validation. Default environment textures to Medium/2K.'}
   elif method=='ping':result={}
   elif method=='tools/list':result={'tools':[{'name':n,'description':d['description'],'inputSchema':{'type':'object','properties':d['properties'],'required':d.get('required',[]),'additionalProperties':False}} for n,d in TOOLS.items()]}
   elif method=='tools/call':
    params=req['params'];args=command(params['name'],params.get('arguments',{}));cmd=[sys.executable,'-m','scanatlas.agent']+(['--database',str(database)] if database else [])+args
    p=subprocess.run(cmd,capture_output=True,text=True,timeout=60);result={'content':[{'type':'text','text':p.stdout or p.stderr}],'isError':p.returncode!=0}
   else:
    print(json.dumps({'jsonrpc':'2.0','id':ident,'error':{'code':-32601,'message':'Method not found'}}),flush=True);continue
   print(json.dumps({'jsonrpc':'2.0','id':ident,'result':result}),flush=True)
  except Exception as ex:print(json.dumps({'jsonrpc':'2.0','id':req.get('id') if isinstance(locals().get('req'),dict) else None,'error':{'code':-32603,'message':str(ex)}}),flush=True)
