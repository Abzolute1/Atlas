let api=null,state={query:'',types:[],subtype:'',source:'',scope:'',offset:0,collection:null};
let request=0,total=0,current=null,allFacets=[],quality='Medium',restoreScroll=0,selectedId=null,pendingSelection=null,timer;
const names={polyhaven:'Poly Haven',ambientcg:'ambientCG',huggingface:'Hugging Face',mixamo:'Mixamo'};
const kindOrder=['3D Assets','3D Plants','Surfaces','Decals','Atlases','HDRIs','Characters','Animations','Brushes','Imperfections','Displacements','Other'];
const kindName=k=>k==='3D Assets'?'3D Models':k;
const $=id=>document.getElementById(id);
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const size=n=>n==null?'Unknown':n<1048576?(n/1024).toFixed(1)+' KiB':(n/1048576).toFixed(1)+' MiB';
function send(action,data={}){if(api)api.request(JSON.stringify({action,...data}));}
function closeDetails(){document.querySelector('.layout').classList.remove('detail-open');document.querySelectorAll('.card.selected').forEach(e=>e.classList.remove('selected'));}
function load(preserveScroll=false){
 restoreScroll=preserveScroll?$('grid').scrollTop:0;
 if(!preserveScroll)closeDetails();
 request++;send('search',{...state,sort:$('sort').value,request});
}
function baseState(){return {query:'',types:[],subtype:'',source:'',scope:'',offset:0,collection:null}}
function navigate(values){clearTimeout(timer);state={...baseState(),...values};$('search').value='';$('sort').value='Relevance';load()}
function scope(value){navigate({scope:value})}
function browseType(value){navigate({types:[value]})}
function browseCategory(kind,subtype){navigate({types:[kind],subtype})}
function source(value){navigate({source:value})}
function clearQuery(){clearTimeout(timer);state.query='';state.offset=0;$('search').value='';load()}
function type(value){state.types=state.types.includes(value)?state.types.filter(x=>x!==value):[...state.types,value];state.subtype='';state.offset=0;load()}
function filterSubtype(value){state.subtype=value;state.offset=0;load()}
function reset(){navigate({})}
function page(dir){state.offset=Math.max(0,state.offset+60*dir);load()}
function toast(t){$('toast').textContent=t;$('toast').style.display='block';setTimeout(()=>$('toast').style.display='none',6000)}
function choose(id,open=true){
 selectedId=id;if(open)document.querySelector('.layout').classList.add('detail-open');
 send('inspect',{id});document.querySelectorAll('.card').forEach(e=>e.classList.toggle('selected',document.querySelector('.layout').classList.contains('detail-open')&&e.dataset.id===id));
}
const previewResults=new Map(),previewRequests=new Set();
function previewFailure(box,id,message){let label=box.querySelector('.placeholder');if(!label)return;label.hidden=false;label.replaceChildren(document.createTextNode(message));let retry=document.createElement('button');retry.className='btn';retry.style.cssText='display:block;margin:8px auto;padding:4px 10px;font-size:11px';retry.textContent='Retry preview';retry.onclick=e=>{e.stopPropagation();previewResults.delete(id+':static');label.textContent='Loading preview';requestPreview(id)};label.append(retry)}
function applyPreview(id,result){if(result.variant==='animated'){if(current?.id!==id)return;let img=document.querySelector('.hero img');if(img&&result.url)img.src=result.url;else if(!result.url)toast('Animation preview could not load');return}document.querySelectorAll('[data-preview-id]').forEach(box=>{if(box.dataset.previewId!==id)return;let img=box.querySelector('img'),label=box.querySelector('.placeholder');if(result.url){if(!img){img=document.createElement('img');img.alt=box.dataset.previewName||'';box.append(img)}img.onload=()=>{img.classList.add('loaded');if(label)label.hidden=true};img.onerror=()=>previewFailure(box,id,'Cached preview could not load');img.src=result.url;}else if(label){if(['missing','not_cached'].includes(result.status))label.textContent=result.status==='missing'?'Source has no preview':'Not cached · offline';else previewFailure(box,id,'Preview could not load');}});}
function requestPreview(id,variant='static'){let key=id+':'+variant;let result=previewResults.get(key);if(result&&result.url){applyPreview(id,result);return}if(previewRequests.has(key))return;previewRequests.add(key);send('preview',{id,variant});}
const previewObserver=new IntersectionObserver(entries=>{entries.forEach(e=>{if(e.isIntersecting){requestPreview(e.target.dataset.previewId);previewObserver.unobserve(e.target)}})},{rootMargin:'180px'});

function render(r){
 if(r.request!==request)return;
 total=r.total;allFacets=r.facets;
 $('searchclear').hidden=!state.query;$('searchhint').hidden=!!state.query;
 let counts={};r.facets.forEach(([k,s,n])=>counts[k]=(counts[k]||0)+n);
 counts.Characters=counts.Characters||0;counts.Animations=counts.Animations||0;
 let sum=Object.values(counts).reduce((a,b)=>a+b,0);
 $('allcount').textContent=sum.toLocaleString();$('categories').replaceChildren();$('typemenu').replaceChildren();
 const selectedFacets=state.types.length===1?r.facets.filter(([k,s,n])=>k===state.types[0]&&s).sort((a,b)=>b[2]-a[2]||a[1].localeCompare(b[1])):[];
 kindOrder.filter(k=>k in counts).forEach(k=>{
  let n=counts[k],b=document.createElement('button');b.className='nav'+(state.types.includes(k)?' active':'');
  b.innerHTML=esc(kindName(k))+'<span class="count">'+n.toLocaleString()+'</span>';b.dataset.kind=k;
  b.title='Browse all '+n.toLocaleString()+' '+k.toLowerCase();b.onclick=()=>browseType(k);$('categories').append(b);
  if(state.types.length===1&&state.types[0]===k&&selectedFacets.length>1){
   let list=document.createElement('div');list.className='subnav';
   let groups=selectedFacets.slice(0,8);
   if(state.subtype&&!groups.some(x=>x[1]===state.subtype))groups=[selectedFacets.find(x=>x[1]===state.subtype),...groups.slice(0,7)].filter(Boolean);
   groups.forEach(([kind,sub,n])=>{
    let item=document.createElement('button');item.className='nav'+(state.subtype===sub?' active':'');
    item.innerHTML='<span>'+esc(sub)+'</span><span class="count">'+n.toLocaleString()+'</span>';
    item.onclick=()=>browseCategory(kind,sub);list.append(item);
   });$('categories').append(list);
  }
  let label=document.createElement('label'),check=document.createElement('input');check.type='checkbox';check.checked=state.types.includes(k);
  check.onchange=()=>type(k);label.append(check,document.createTextNode(kindName(k)));$('typemenu').append(label);
 });
 $('typebutton').textContent=state.types.length===1?kindName(state.types[0])+' ▾':state.types.length?state.types.length+' asset types ▾':'All asset types ▾';
 $('subtype').replaceChildren(new Option('All categories',''));
 selectedFacets.slice().sort((a,b)=>a[1].localeCompare(b[1])).forEach(([k,s,n])=>$('subtype').add(new Option(s+' ('+n.toLocaleString()+')',s)));
 $('subtype').disabled=selectedFacets.length<=1;$('subtype').value=state.subtype||'';
 $('collections').replaceChildren();
 (r.collections||[]).forEach(col=>{
  let b=document.createElement('button');b.className='nav'+(state.collection===col.id?' active':'');b.textContent=col.name;
  b.onclick=()=>{
   clearTimeout(timer);state=baseState();
   if(col.query){try{let q=JSON.parse(col.query);state.query=q.text||q.query||'';state.types=q.kinds||q.types||[];state.subtype=q.subtype||'';state.source=q.source||''}catch(e){toast('Collection query unavailable')}}
   else state.collection=col.id;
   $('search').value=state.query;load();
  };$('collections').append(b);
 });
 $('sources').replaceChildren();$('provider').replaceChildren(new Option('All sources',''));
 r.sources.filter(s=>s.source).forEach(s=>{
  let b=document.createElement('button');b.className='nav'+(state.source===s.source?' active':'');
  b.innerHTML=esc(names[s.source]||s.source)+'<span class="count">'+s.count.toLocaleString()+'</span>';
  b.onclick=()=>source(s.source);$('sources').append(b);$('provider').add(new Option(names[s.source]||s.source,s.source));
 });$('provider').value=state.source;
 document.querySelectorAll('[data-scope]').forEach(e=>e.classList.toggle('active',e.dataset.scope===state.scope&&(!!state.scope||!state.types.length&&!state.source&&!state.collection)));
 $('title').textContent=state.query?'Results for “'+state.query+'”':state.subtype?kindName(state.types[0])+' / '+state.subtype:state.types.length?state.types.map(kindName).join(' + '):state.source?names[state.source]:state.scope==='my-assets'?'My assets':state.scope==='favorites'?'Favorites':state.scope==='downloaded'?'On this computer':'All assets';
 let categoryTotal=state.types.length?state.types.reduce((n,k)=>n+(counts[k]||0),0):sum;
 let filtered=!!(state.query||state.subtype||state.source||state.scope||state.collection);
 $('summary').textContent=total.toLocaleString()+(filtered?' matching assets':' assets')+(filtered?' · '+categoryTotal.toLocaleString()+(state.types.length?' in selected asset types':' in the full catalog'):' across your connected libraries');
 $('activefilters').replaceChildren();let filters=[];
 if(state.query)filters.push(['Search: '+state.query,clearQuery]);
 state.types.forEach(t=>filters.push([kindName(t),()=>type(t)]));
 if(state.subtype)filters.push([state.subtype,()=>filterSubtype('')]);
 if(state.source)filters.push([names[state.source]||state.source,()=>{state.source='';state.offset=0;load()}]);
 if(state.scope)filters.push([{'my-assets':'My assets',favorites:'Favorites',downloaded:'On this computer'}[state.scope]||state.scope,()=>{state.scope='';state.offset=0;load()}]);
 filters.forEach(([text,remove])=>{let chip=document.createElement('button');chip.className='tagfilter';chip.textContent=text+' ×';chip.setAttribute('aria-label','Remove '+text);chip.onclick=remove;$('activefilters').append(chip)});
 previewObserver.disconnect();$('grid').replaceChildren();
 let tiles=(r.browse_categories||[]).slice(0,8);
 if(!state.types.length)tiles.sort((a,b)=>kindOrder.indexOf(a.kind)-kindOrder.indexOf(b.kind));
 if(tiles.length){
  let section=document.createElement('section');section.className='browse-section';section.setAttribute('aria-label','Browse categories');
  section.innerHTML='<h2 class="browse-heading">CATEGORIES</h2><div class="browse-grid"></div>';
  tiles.forEach(t=>{
   let tile=document.createElement('button');tile.className='category-tile';tile.setAttribute('aria-label','Browse '+t.label+', '+t.count+' assets');
   tile.onclick=()=>browseCategory(t.kind,t.subtype);
   tile.innerHTML='<div class="picture"><span class="placeholder">Loading preview</span></div><div class="category-copy"><strong>'+esc(t.label)+'</strong><small>'+t.count.toLocaleString()+' assets</small></div>';
   let pic=tile.querySelector('.picture');pic.dataset.previewId=t.id;pic.dataset.previewName=t.label;
   section.querySelector('.browse-grid').append(tile);previewObserver.observe(pic);
  });$('grid').append(section);
  let heading=document.createElement('h2');heading.className='grid-heading';heading.innerHTML='ALL ASSETS <span>'+total.toLocaleString()+'</span>';$('grid').append(heading);
 }
 for(let a of r.items){
  let card=document.createElement('article');card.className='card'+(document.querySelector('.detail-open')&&current?.id===a.id?' selected':'');card.dataset.id=a.id;card.tabIndex=0;
  card.setAttribute('role','button');card.setAttribute('aria-label',a.name+' · '+(names[a.source]||a.source||'Local library')+' · View asset');
  card.onclick=()=>choose(a.id);card.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();choose(a.id)}};
  card.innerHTML='<div class="picture"><div class="placeholder"><b>◇</b>'+(a.preview?'Loading preview':'No preview supplied')+'</div>'+(a.source==='mixamo'?'<span class="entry-status">'+(a.catalog_only?'Online catalog':'Downloaded')+'</span>':'')+(a.maxres?'<span class="badge">'+Math.round(a.maxres/1024)+'K</span>':'')+'</div><div class="cardbody"><span class="name">'+esc(a.name)+'</span><div class="cardmeta"><span>'+esc(kindName(a.kind))+'</span><span class="provider">'+esc(names[a.source]||a.source)+'</span></div></div>';
  let picture=card.querySelector('.picture');picture.dataset.previewId=a.id;picture.dataset.previewName=a.name;
  $('grid').append(card);if(a.preview)previewObserver.observe(picture);
 }
 if(!r.items.length){current=null;selectedId=null;closeDetails();$('details').innerHTML='<div class="empty">No asset selected.</div>';$('grid').innerHTML='<div class="empty">No assets match these filters.<br><br><button class="btn" onclick="reset()">Browse all assets</button></div>'}
 $('prev').disabled=state.offset===0;$('next').disabled=state.offset+60>=total;
 $('pagination').textContent=(total?state.offset+1:0)+'–'+Math.min(state.offset+60,total)+' of '+total.toLocaleString()+' · Page '+(total?Math.floor(state.offset/60)+1:0)+' of '+Math.ceil(total/60);
 $('grid').scrollTop=restoreScroll;
 if(pendingSelection&&r.items.some(a=>a.id===pendingSelection)){choose(pendingSelection);pendingSelection=null}else if(r.items.length&&(!current||!r.items.some(a=>a.id===current.id)))choose(r.items[0].id,false);
}
function inspect(a){if(selectedId&&a.id!==selectedId)return;current=a;let d=a.source_detail||{},remote=!!d.catalog_only,local=a.source==='mixamo'&&!remote,pending=d.manifest_pending;let tags=(d.tags||[]).filter(t=>t&&!/^\d+$/.test(t)).slice(0,16);$('details').innerHTML='<div class="detail-top"><span>ASSET DETAILS</span><button onclick="closeDetails()" aria-label="Close asset details">×</button></div><div class="hero">'+'<span class="placeholder">'+(a.preview_url?'Loading preview':'No preview supplied')+'</span>'+'</div><h2>'+esc(a.name)+'</h2><div class="origin">'+esc(a.kind)+' / '+esc(a.subtype)+'</div><div><span class="license">'+esc(a.license==='CC0'?'CC0 · Free to use':a.source==='huggingface'?'License unverified':a.my_asset?'Personal asset · Mixamo terms':remote?'Mixamo · online catalog':'Local library')+'</span></div><div class="detail-actions"><button class="btn" id="fav">♡ Favorite</button><button class="btn" id="opensrc">Source ↗</button></div><div class="spec"><h3>ASSET INFORMATION</h3><dl><dt>Provider</dt><dd>'+esc(names[a.source]||a.source)+'</dd><dt>Resolution</dt><dd>'+esc((a.resolutions||[]).filter(x=>x).map(x=>Math.round(x/1024)+'K').join(' · ')||'Not specified')+'</dd><dt>Asset ID</dt><dd style="font-size:10px">'+esc(a.id)+'</dd><dt>Availability</dt><dd>'+esc(remote?'Export through Mixamo':local?'Local FBX':pending?'Loading file options…':d.files?.length?'Public download':'See source')+'</dd></dl><h3>TAGS</h3><div class="tags" id="tags"></div></div><div class="downloadbox"><select id="quality" aria-label="Download quality">'+(local||remote?'<option>Original FBX</option>':['Low','Medium','High','Ultra'].map(q=>'<option '+(q===quality?'selected':'')+'>'+q+'</option>').join(''))+'</select><div class="size"><span id="filecount"></span><strong id="size"></strong></div><button class="primary" id="download">'+(remote?'Export FBX…':local?'Choose staging folder':'Choose folder & download')+'</button><div class="muted small" id="downloadnote" style="padding-top:8px;line-height:1.5"></div><div class="unity-box"><button id="unityimport" class="btn" disabled>Import to Unity</button><div id="unityprogress" class="import-progress" hidden><div class="progress-heading"><span id="unitystage"></span><strong id="unitypercent"></strong></div><progress id="unitybar" max="100" aria-label="Unity import estimated progress"></progress></div><p id="unitynote">Checking local files…</p></div></div>';if(d.description){let desc=document.createElement('p');desc.className='muted small';desc.textContent=d.description;document.querySelector('.origin').after(desc)}let hero=document.querySelector('.hero');hero.dataset.previewId=a.id;hero.dataset.previewName=a.name;if(a.preview_url)requestPreview(a.id);if(remote&&d.animated_preview&&d.animated_preview!==a.preview_url){let play=document.createElement('button');play.className='btn';play.style.marginTop='8px';play.textContent='▶ Play animation preview';play.onclick=()=>requestPreview(a.id,'animated');hero.after(play)}if(d.preview_status==='local_render'&&d.gallery?.length>1){let strip=document.createElement('div');strip.className='pose-strip';d.gallery.forEach((url,i)=>{let b=document.createElement('button');b.className='btn';b.textContent='Pose '+(i+1);b.setAttribute('aria-label','Show animation pose '+(i+1));b.onclick=()=>document.querySelector('.hero img').src=url;strip.append(b)});document.querySelector('.hero').after(strip)}$('fav').onclick=()=>send('favorite',{id:a.id});$('opensrc').onclick=()=>send('source',{id:a.id});tags.forEach(t=>{let b=document.createElement('button');b.textContent=t;b.onclick=()=>{$('search').value=t;state.query=t;state.offset=0;load()};$('tags').append(b)});$('quality').onchange=()=>{quality=$('quality').value;plan()};$('download').onclick=()=>send('download',{id:a.id,quality});$('unityimport').onclick=()=>send('unity_import',{id:a.id,quality:unityQuality()});plan();}
function unityQuality(){return ['Low','Medium','High','Ultra'].includes(quality)?quality:'Medium'}
function plan(){send('unity_context',{id:current.id,quality:unityQuality()});let a=current,remote=!!a.source_detail?.catalog_only,local=a.source==='mixamo'&&!remote,p=a.qualities?.[quality];$('size').textContent=remote?'Known after export':local?size(a.availability?.size_bytes):p?.size_bytes!=null?size(p.size_bytes):a.file_metadata_pending?'Loading…':'Unavailable';$('filecount').textContent=remote?'FBX for Unity':local?(a.availability?.file_count||1)+' local files':p?.file_count?p.file_count+' file'+(p.file_count>1?'s':''):'';$('download').disabled=remote?!a.source_detail.export_supported:!local&&!p?.file_count;$('downloadnote').textContent=remote?(a.source_detail.export_supported?'Uses your signed-in Mixamo session. Downloads only this selection.':'Animation pack listing. Choose its individual clips for export.'):local?'Rig compatibility must be checked in Unity.':p?.reason||((p?.resolution?Math.round(p.resolution/1024)+'K textures. ':'')+(p?.archive_requires_extraction?'ZIP package · Import to Unity extracts it automatically.':'Only selected files will download.'));}
new QWebChannel(qt.webChannelTransport,channel=>{api=channel.objects.atlas;api.result.connect(raw=>{let r=JSON.parse(raw);if(r.action==='preview'){previewRequests.delete(r.id+':'+r.variant);if(r.status==='cancelled'){if([...document.querySelectorAll('[data-preview-id]')].some(e=>e.dataset.previewId===r.id))requestPreview(r.id,r.variant);}else{previewResults.set(r.id+':'+r.variant,r);applyPreview(r.id,r);}}else if(r.action==='unity_context')unityContext(r);else if(r.action==='asset_downloaded'){if(r.id){state={...baseState(),query:r.id};$('search').value=r.id;pendingSelection=r.id;load()}}else if(r.action==='search')render(r);else if(r.action==='collection_saved')load();else if(r.action==='catalog_changed'){previewResults.clear();load(true);if(current)choose(current.id,false);}else if(r.action==='inspect')inspect(r.asset);else if(r.action==='notice'||r.action==='error'||r.action==='metadata_error')toast(r.message);else if(r.action==='favorite')toast(r.favorite?'Added to favorites':'Removed from favorites');else if(r.action==='status')taskStatus(r)});load()});$('search').oninput=()=>{clearTimeout(timer);timer=setTimeout(()=>{state.query=$('search').value;state.offset=0;load()},170)};document.addEventListener('keydown',e=>{if(e.ctrlKey&&e.key==='f'){e.preventDefault();$('search').focus()}if(e.key==='Escape'){$('typemenu').classList.remove('open');closeDetails()}});

document.addEventListener('click',e=>{if(!e.target.closest('.types'))$('typemenu').classList.remove('open')});

function unityContext(r){
 const project=r.project?.valid?r.project.project:null;
 const projectName=project?project.split(/[\\/]/).pop():'';
 const connected=r.project?.source==='open';
 $('unityproject').textContent=project?'Unity · '+projectName+(connected?' · Open':''):'Connect Unity';
 $('unityproject').title=project?(connected?'Connected to open Unity project: ':'Selected Unity project: ')+project:(r.project?.note||'Choose a Unity project');
 if(!current||r.id!==current.id||r.quality!==unityQuality()||!$('unityimport'))return;
 const job=r.job,ready=!!r.local?.available;
 $('unityimport').onclick=job?.status==='complete'?()=>send('unity_folder',{job:job.job_id}):()=>send('unity_import',{id:current.id,quality:unityQuality()});
 $('unityimport').title=job?.status==='complete'?'Open the imported files and generated prefabs':'';
 $('unityimport').disabled=!ready||['queued','processing'].includes(job?.status);
 $('unityimport').textContent=job?.status==='complete'?'Imported to Unity ✓':job?.status==='processing'?'Unity is importing…':job?.status==='queued'?'Waiting for Unity…':'Import to Unity';
 let note=!ready?(r.local?.reason||'Download this quality first.'):project?(connected?'Imports into the open '+projectName+' project.':'Copies into '+projectName+' / Assets / Atlas.'):(r.project?.note||'Choose your Unity project on the first import.');
 if(job?.status==='queued')note=job.editor_wakeup?.note||job.note||'Open this project in Unity. Materials, rigs and prefabs are prepared automatically.';
 if(job?.status==='processing')note='Unity is preparing materials, models and animation clips.';
 if(job?.status==='complete')note=(job.prefabs?.length||0)+' prefabs · '+(job.materials?.length||0)+' materials · '+(job.animations?.length||0)+' clips · '+(job.textures?.length||0)+' textures.'+(job.warnings?.length?' '+job.warnings.join(' '):' Ready in Assets / Atlas.');
 if(job?.status==='failed')note='Import failed: '+(job.error||'See Unity import report.');
 $('unitynote').textContent=note;
 const visible=!!job;
 $('unityprogress').hidden=!visible;
 if(visible){
  const percent=job.status==='complete'?100:job.progress_percent;
  $('unitystage').textContent=job.stage||({queued:'Waiting for Unity',processing:'Importing',complete:'Complete',failed:'Failed'}[job.status]||'Importing');
  setProgress('unitybar','unitypercent',percent,job.status!=='complete');
 }

}
setInterval(()=>send('unity_context',{id:current?.id,quality:unityQuality()}),2000);

function setProgress(barId,labelId,value,estimated=false){
 const bar=$(barId),known=typeof value==='number'&&Number.isFinite(value);
 if(known){const pct=Math.max(0,Math.min(100,value));bar.value=pct;$(labelId).textContent=Math.floor(pct)+'%'+(estimated?' estimated':'');bar.setAttribute('aria-valuetext',$(labelId).textContent)}
 else{bar.removeAttribute('value');bar.setAttribute('aria-valuetext','Working, total unknown');$(labelId).textContent='Working…'}
}
function taskStatus(r){
 $('status').textContent=r.busy?r.text:'Atlas 0.6.2 · '+r.count.toLocaleString()+' catalog entries';
 $('activity').hidden=!r.activity;
 if(!r.activity)return;
 $('activitylabel').textContent=r.activity.label;
 $('activitydetail').textContent=r.activity.detail;
 setProgress('activitybar','activitypercent',r.activity.percent,!!r.activity.estimated);
}
