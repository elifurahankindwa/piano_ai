const $=id=>document.getElementById(id),au=$('au'),roll=$('roll'),kb=$('kb');
const COL={left:'#4aa3ff',right:'#ff9f43',unknown:'#b39ddb'},NAMES=['C','C#','D','D#','E','F','F#','G','G#','A','A#','B'];
const isB=p=>[1,3,6,8,10].includes(p%12);let wi={},c=0;for(let p=21;p<=108;p++){wi[p]=c;if(!isB(p))c++}
let P=null,notes=[],chords=[],sel=null,A=0,B=0,loop=false,SPAN=8;
// Time-bucketed index so the render loop touches only notes near the playhead.
// Without this a 25-minute song (~17k notes) makes every frame scan the whole
// list, which stutters badly.
const BUCKET=1;
let buckets=[],nbuckets=0;
function indexNotes(){
 const ns=[...notes].sort((a,b)=>a.start-b.start);buckets=[];nbuckets=0;
 if(!ns.length)return;
 // Buckets must cover the furthest END, not the last start: a note can begin
 // in the final bucket and sound past it, and querying near the end of the
 // project would otherwise fall outside the index.
 let maxEnd=0;for(const n of ns)if(n.end>maxEnd)maxEnd=n.end;
 nbuckets=Math.floor(maxEnd/BUCKET)+1;
 for(let i=0;i<nbuckets;i++)buckets.push([]);
 for(const n of ns){
  // a long note must appear in every bucket it sounds through
  let a=Math.floor(n.start/BUCKET),b=Math.floor(Math.max(n.end-1e-9,n.start)/BUCKET);
  if(a<0)a=0;if(a>=nbuckets)a=nbuckets-1;
  if(b>=nbuckets)b=nbuckets-1;
  for(let i=a;i<=b;i++)buckets[i].push(n);
 }
}
// Notes whose span overlaps [from,to).
function notesIn(from,to){
 const out=[];
 if(!nbuckets)return out;
 let a=Math.floor(from/BUCKET),b=Math.floor(to/BUCKET);
 if(a<0)a=0;if(b>=nbuckets)b=nbuckets-1;
 // Clamp the low end too; otherwise a query past the last bucket leaves
 // a>b and the loop below silently yields nothing.
 if(a>b)return out;
 const seen=new Set();
 for(let i=a;i<=b;i++)for(const n of buckets[i]){
  if(seen.has(n.id))continue;
  if(n.start<to&&n.end>from){seen.add(n.id);out.push(n)}}
 return out;
}
// Notes sounding at an instant.
function notesAt(t){return notesIn(t,t+1e-9).filter(n=>n.start<=t&&t<n.end)}
const api=(u,o)=>fetch('/api/v1'+u,o).then(async r=>{if(!r.ok)throw new Error((await r.json().catch(()=>({}))).detail||r.statusText);return r.status==204?null:r.json()});
const fmt=t=>`${Math.floor(t/60)}:${String(Math.floor(t%60)).padStart(2,'0')}`;
$('file').onchange=async e=>{const f=e.target.files[0];if(!f)return;$('status').className='mut';$('status').textContent='Uploading…';
 try{const fd=new FormData();fd.append('file',f);const r=await api('/projects',{method:'POST',body:fd});poll(r.project_id)}
 catch(x){$('status').className='err';$('status').textContent=x.message}};
async function poll(id){notes=[];chords=[];sel=null;au.removeAttribute('src');
 for(;;){P=await api('/projects/'+id);$('status').textContent=`${P.filename}: ${P.status} (${P.stage}, ${Math.round(P.progress*100)}%)`;
  if(P.status==='failed'){$('status').className='err';$('status').textContent='Failed: '+P.error;return}
  if(P.status==='completed')break;await new Promise(r=>setTimeout(r,1000))}
 [notes,chords]=await Promise.all([api(`/projects/${id}/notes`),api(`/projects/${id}/chords`)]);indexNotes();showKey(P.key);
 au.src=`/api/v1/projects/${id}/audio`;au.playbackRate=+$('speed').value;
 $('status').textContent=`${P.filename}: ${notes.length} notes (${P.model})`;
 $('exp').innerHTML=['json','csv'].map(k=>`<a style="color:var(--L)" href="/api/v1/projects/${id}/export/${k}">${k.toUpperCase()}</a>`).join(' · ')+' · <a href="#" id="mid" style="color:var(--L)">MIDI</a> · <a href="#" id="vid" style="color:var(--L)">VIDEO</a>';
 $('mid').onclick=async e=>{e.preventDefault();const b=await(await fetch(`/api/v1/projects/${id}/export/midi`,{method:'POST'})).blob();const a=document.createElement('a');a.href=URL.createObjectURL(b);a.download=id+'.mid';a.click()};
 $('vid').onclick=e=>{e.preventDefault();$('vbox').scrollIntoView({behavior:'smooth',block:'center'})};
 initVideo(id)}
// --- Video export -------------------------------------------------------------
// Rendering happens on the server (a browser can only capture its own canvas in
// real time), so the panel picks the options, starts the job and polls it.
const fmtDur=s=>s<60?`${Math.round(s)}s`:`${Math.round(s/60)} min`;
async function initVideo(id){
 try{
  $('vdl').hidden=true;$('vgo').disabled=false;
  const o=await api(`/projects/${id}/export/video/presets`);
  const fill=(el,items,sel)=>{el.innerHTML=items.map(i=>`<option value="${i.id}">${i.label}</option>`).join('');el.value=sel};
  fill($('vres'),o.resolutions,'1080p30');fill($('vcodec'),o.codecs,'h264');fill($('vqual'),o.qualities,'high');
  $('vbox').hidden=false;$('vstat').className='mut';
  if(!o.ffmpeg.available){$('vgo').disabled=true;$('vstat').textContent='Video export needs ffmpeg on the server.';return}
  $('vto').placeholder=Math.round(P.duration||0)+'s';
  const st=await api(`/projects/${id}/export/video`);
  if(st.file)showDl();   // a finished render stays downloadable, even if a newer one failed
  if(st.status==='rendering'||st.status==='queued'){pollVideo();return}
  if(st.status==='done')showVideo(st);else if(st.status==='failed'){$('vstat').className='err';$('vstat').textContent='Last render failed: '+st.error}
 }catch(x){$('vstat').className='err';$('vstat').textContent=x.message}}
function showDl(){$('vdl').href=`/api/v1/projects/${P.id}/export/video/file`;$('vdl').hidden=false}
function showVideo(st){
 $('vstat').className='mut';
 $('vstat').textContent=`Done · ${st.width}×${st.height} · ${(st.bytes/1e6).toFixed(1)} MB`+(st.name?` · ${st.name}`:'');
 showDl();$('vgo').disabled=false}
$('vgo').onclick=async()=>{
 const q=new URLSearchParams({resolution:$('vres').value,quality:$('vqual').value,codec:$('vcodec').value});
 if($('vfrom').value!=='')q.set('start',$('vfrom').value);
 if($('vto').value!=='')q.set('end',$('vto').value);
 $('vgo').disabled=true;$('vstat').className='mut';$('vstat').textContent='Starting…';
 try{const r=await api(`/projects/${P.id}/export/video?${q}`,{method:'POST'});pollVideo(r.note)}
 catch(x){$('vstat').className='err';$('vstat').textContent=x.message;$('vgo').disabled=false}};
async function pollVideo(note){
 let st;
 try{st=await api(`/projects/${P.id}/export/video`)}
 catch(x){$('vstat').className='err';$('vstat').textContent=x.message;$('vgo').disabled=false;return}
 if(st.status==='queued'){$('vstat').textContent='Queued…';setTimeout(()=>pollVideo(note),600);return}
 if(st.status==='rendering'){
  $('vstat').textContent=`Rendering ${st.width}×${st.height} · ${st.fps} fps · ${Math.round((st.progress||0)*100)}%`+(st.eta_seconds?` · ~${fmtDur(st.eta_seconds)} left`:'')+(note?` · ${note}`:'');
  setTimeout(()=>pollVideo(note),1500);return}
 if(st.status==='done'){showVideo(st);return}
 if(st.status==='failed'){
  $('vstat').className='err';$('vstat').textContent='Render failed: '+(st.error||'unknown error');$('vgo').disabled=false;
  if(st.file)showDl();   // the previous render is still downloadable
  return}
 $('vstat').className='mut';$('vstat').textContent='No render running.';$('vgo').disabled=false}
// Key is an estimate: it always reports a best-scoring key, even for material
// with no real tonal centre, so a low confidence or a near-tie is shown rather
// than hidden behind a confident-looking label.
function showKey(k){
 if(!k){$('key').textContent='–';$('kconf').textContent='';$('kwarn').textContent='';return}
 $('key').textContent=k.name;
 const pct=Math.round(k.confidence*100);
 $('kconf').textContent=`confidence ${pct}%${k.runner_up?` · next: ${k.runner_up}`:''}`;
 const warns=[];
 if(k.ambiguous)warns.push('Weak match — this audio may not have a clear tonal centre.');
 else if(pct<75)warns.push('Moderate match — treat as a rough guide.');
 if(k.relative_minor)warns.push(`Shares material with ${k.relative_minor}.`);
 if(k.relative_major)warns.push(`Shares material with ${k.relative_major}.`);
 $('kwarn').textContent=warns.join(' ')}
$('play').onclick=()=>au.paused?au.play():au.pause();au.onplay=()=>$('play').textContent='❚❚';au.onpause=()=>$('play').textContent='▶';
$('back').onclick=()=>au.currentTime=Math.max(0,au.currentTime-5);$('fwd').onclick=()=>au.currentTime+=5;
$('seek').oninput=e=>au.currentTime=e.target.value/1000*(au.duration||0);$('speed').onchange=e=>au.playbackRate=+e.target.value;$('vol').oninput=e=>au.volume=+e.target.value;
$('a').onclick=()=>{A=au.currentTime};$('b').onclick=()=>{B=au.currentTime};
$('lp').onclick=()=>{loop=!loop&&B>A;$('lp').textContent='Loop: '+(loop?`${fmt(A)}–${fmt(B)}`:'off')};
function fit(cv){const r=devicePixelRatio||1,w=cv.clientWidth,h=cv.clientHeight;if(cv.width!==w*r||cv.height!==h*r){cv.width=w*r;cv.height=h*r}const g=cv.getContext('2d');g.setTransform(r,0,0,r,0,0);return[g,w,h]}
const col=n=>COL[n.hand]||COL.unknown;
function frame(){requestAnimationFrame(frame);const t=au.currentTime||0;
 if(loop&&t>=B)au.currentTime=A;
 const act=notesAt(t);
 // roll: notes fall down the lane of their key and disappear at the keyboard line
 // the playhead is exactly that line, so notes vanish where the line sits
 let[g,w,h]=fit(roll);g.fillStyle='#0f1115';g.fillRect(0,0,w,h);const rw=w/52,rb=rw*.6,t0=t,LN=2,nh0=h-LN,yOf=s=>nh0-(s-t0)/SPAN*nh0;
 const kx=p=>isB(p)?wi[p]*rw-rb/2:wi[p]*rw+.5,kw=p=>isB(p)?rb:rw-1;
 for(let p=21;p<=108;p++){if(isB(p)){g.fillStyle='#14171d';g.fillRect(kx(p),0,kw(p),nh0)}}
 for(let s=Math.ceil(t0);s<t0+SPAN;s++){const y=yOf(s);g.fillStyle='#232834';g.fillRect(0,y,w,1)}
 const visible=notesIn(t0,t0+SPAN);
 for(const n of visible){const yB=Math.min(nh0,yOf(n.start)),yT=Math.max(0,yOf(n.end)),nh=Math.max(1,yB-yT);
  g.globalAlpha=(n.confidence!=null&&n.confidence<.5)?.4:1;g.fillStyle=col(n);g.fillRect(kx(n.pitch),yT,kw(n.pitch),nh);
  if(n.start<=t&&t<n.end){g.strokeStyle='#fff';g.strokeRect(kx(n.pitch),yT,kw(n.pitch),nh)}
  if(sel===n.id){g.strokeStyle='#0f0';g.lineWidth=2;g.strokeRect(kx(n.pitch)-1,yT-1,kw(n.pitch)+2,nh+2);g.lineWidth=1}}
 g.globalAlpha=1;g.fillStyle='#fff';g.fillRect(0,nh0,w,LN);
 // keyboard
 [g,w,h]=fit(kb);const ww=w/52,bw=ww*.6,bh=h*.62,map={};act.forEach(n=>map[n.pitch]=n);g.clearRect(0,0,w,h);
 for(let p=21;p<=108;p++)if(!isB(p)){const n=map[p];g.fillStyle=n?col(n):'#f2f2f2';g.fillRect(wi[p]*ww+.5,0,ww-1,h);if(p%12==0){g.fillStyle='#555';g.font='10px sans-serif';g.fillText('C'+(p/12-1),wi[p]*ww+3,h-4)}}
 for(let p=21;p<=108;p++)if(isB(p)){const n=map[p];g.fillStyle=n?col(n):'#1a1a1a';g.fillRect(wi[p]*ww-bw/2,0,bw,bh)}
 const ch=chords.find(c=>c.start<=t&&t<c.end);$('chord').textContent=ch?ch.symbol+(ch.inversion?` (inv ${ch.inversion})`:''):'–';
 $('cconf').textContent=ch?`match score ${ch.confidence}`:'';
 $('now').textContent=act.map(n=>n.note_name).join(' ')||'–';
 $('time').textContent=`${fmt(t)} / ${fmt(au.duration||0)}`;if(document.activeElement!==$('seek'))$('seek').value=au.duration?t/au.duration*1000:0}
roll.onclick=e=>{const r=roll.getBoundingClientRect(),t=(au.currentTime||0),w=roll.clientWidth,h=roll.clientHeight,
 x=(e.clientX-r.left)/r.width*w,y=(e.clientY-r.top)/r.height*h,ww=w/52,bw=ww*.6;
 let p=null;for(let q=21;q<=108;q++)if(isB(q)){const x0=wi[q]*ww-bw/2;if(x>=x0&&x<=x0+bw){p=q;break}}
 if(p==null)for(let q=21;q<=108;q++)if(!isB(q)){const x0=wi[q]*ww+.5;if(x>=x0&&x<=x0+ww-1){p=q;break}}
 const tt=t+(1-y/h)*SPAN,n=p!=null&&notesAt(tt).find(n=>n.pitch===p);
 if(n){sel=n.id;showSel(n)}else{sel=null;$('sel').textContent='Click a note in the roll';$('selbtns').innerHTML='';au.currentTime=Math.max(0,au.duration?Math.min(tt,au.duration):tt)}};
function showSel(n){$('sel').textContent=`${n.note_name} · ${n.start.toFixed(2)}–${n.end.toFixed(2)}s · vel ${n.velocity} · conf ${n.confidence??'n/a'} · hand ${n.hand}${n.user_edited?' (edited)':''}`;
 $('selbtns').innerHTML=['left','right'].map(h=>`<button data-h="${h}">${h}</button>`).join(' ')+' <button data-d="1">delete</button>';
 $('selbtns').onclick=async e=>{const b=e.target.dataset;if(b.d){await api(`/projects/${P.id}/notes/${n.id}`,{method:'DELETE'});sel=null;$('selbtns').innerHTML='';$('sel').textContent='Deleted'}
  else if(b.h)await api(`/projects/${P.id}/notes/${n.id}`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({hand:b.h})});
  [notes,chords]=await Promise.all([api(`/projects/${P.id}/notes`),api(`/projects/${P.id}/chords`)]);indexNotes();const m=notes.find(x=>x.id===n.id);if(m)showSel(m)}}
roll.addEventListener('wheel',e=>{e.preventDefault();SPAN=Math.min(30,Math.max(2,SPAN*(e.deltaY>0?1.1:.9)))},{passive:false});
document.addEventListener('keydown',e=>{if(e.code==='Space'&&e.target.tagName!=='INPUT'&&e.target.tagName!=='BUTTON'){e.preventDefault();$('play').click()}});
frame();
