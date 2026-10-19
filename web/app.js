'use strict';
const $=id=>document.getElementById(id);
const state={jobs:[],selected:null,result:null,image:null,view:'result',filter:'all',pad:0,editing:false,dirty:false,voidSelection:null,history:[],token:0};
let templates=[];let registration=null;
let toastTimer;
function toast(message){$('toast').textContent=message;$('toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').hidden=true,6000);}
async function api(url,options={}){const response=await fetch(url,options);if(!response.ok){let message;try{const body=await response.json();message=typeof body.detail==='string'?body.detail:JSON.stringify(body.detail);}catch{message=`요청 실패 (${response.status})`;}throw Error(message);}return response.json();}
function text(tag,content,className){const el=document.createElement(tag);el.textContent=content;if(className)el.className=className;return el;}
function sourceLabel(kind){return kind==='reviewed'?'판독 자료':kind==='edited'?'수정 결과':'자동 분석';}
function renderList(){
  const query=$('search').value.trim().toLowerCase();const list=$('fileList');list.replaceChildren();
  const filtered=state.jobs.filter(job=>(state.filter==='all'||(state.filter==='reviewed'?job.kind==='reviewed':job.kind!=='reviewed'))&&job.name.toLowerCase().includes(query));
  for(const job of filtered){
    const button=document.createElement('button');button.className='file-row'+(job.id===state.selected?' active':'');button.dataset.id=job.id;button.title=job.name;
    const img=document.createElement('img');img.src=`/api/jobs/${job.id}/image`;img.loading='lazy';img.alt='';button.append(img);
    const meta=text('div','','file-meta');meta.append(text('strong',job.name),text('small',sourceLabel(job.kind)));button.append(meta);
    const label=job.status==='done'?'완료':job.status==='error'?'확인 필요':job.status==='running'?'분석 중':job.status==='needs_template'?'패드 등록 필요':'대기';button.append(text('span',label,'file-state'+(job.status==='error'?' error':'')));
    button.onclick=()=>select(job.id);list.append(button);
  }
  if(!filtered.length)list.append(text('p',query?'일치하는 이미지가 없습니다.':'이미지를 추가해 주세요.','status'));
  $('imageCount').textContent=state.jobs.length;$('total').textContent=state.jobs.length;
  $('completed').textContent=state.jobs.filter(j=>j.status==='done').length;
  $('pending').textContent=state.jobs.filter(j=>['queued','running'].includes(j.status)).length;
}
async function refresh(){
  try{
    const jobs=await api('/api/jobs');jobs.sort((a,b)=>b.created-a.created);const old=state.jobs.find(j=>j.id===state.selected);state.jobs=jobs;renderList();
    $('connection').textContent='분석 서버 연결됨';$('connection').classList.remove('offline');
    if(!state.selected&&jobs.length)await select(jobs[0].id);
    else {const current=jobs.find(j=>j.id===state.selected);if(current&&old&&current.status!==old.status&&!state.editing&&!registration)await select(current.id);}
  }catch(error){$('connection').textContent='서버 연결 확인 필요';$('connection').classList.add('offline');if(!state.selected)setStatus(error.message,true);}
}
function setStatus(message,error=false){$('status').textContent=message;$('status').classList.toggle('error',error);}
async function select(id){
  registration=null;$('registration').hidden=true;const token=++state.token;state.selected=id;state.editing=false;state.dirty=false;state.voidSelection=null;state.history=[];state.result=null;state.image=null;state.pad=0;updateEditing();renderCards();renderList();
  $('download').disabled=true;$('editToggle').disabled=true;$('reanalyze').disabled=true;
  $('busy').hidden=false;$('busyLabel').textContent='이미지를 불러오는 중입니다';$('emptyState').hidden=true;$('stage').classList.remove('empty');
  try{
    const job=await api(`/api/jobs/${id}`);if(token!==state.token)return;
    $('selectedName').textContent=job.name;$('sourceTag').textContent=sourceLabel(job.kind);
    const image=new Image();image.src=`/api/jobs/${id}/image`;await image.decode();if(token!==state.token)return;
    state.image=image;state.result=job.result;
    $('dimensions').textContent=`${image.naturalWidth.toLocaleString()} × ${image.naturalHeight.toLocaleString()} px`;
    $('reanalyze').disabled=['queued','running'].includes(job.status);
    if(job.status==='done'){
      $('busy').hidden=true;$('download').disabled=false;$('editToggle').disabled=false;
      setStatus(job.kind==='reviewed'?'원본과 대조한 고객 자료의 판독 결과입니다. 새 자동 분석은 「다시 분석」을 사용하세요.':job.result.edited?'수정한 영역으로 면적 비율을 다시 계산했습니다.':`등록 패드 ${job.result.pads.length}개 분석 완료 · 정렬된 경계를 원본과 비교하세요.`);
    }else if(job.status==='needs_template'){
      $('busy').hidden=true;setStatus('검사 설정을 선택하고 다시 분석하거나, 현재 사진으로 패드를 등록하세요.');
    }else if(job.status==='error'){
      $('busy').hidden=true;setStatus(job.error||'분석하지 못했습니다.',true);
    }else{
      $('busyLabel').textContent=job.status==='queued'?'순서대로 분석하고 있습니다':'패드와 보이드를 찾고 있습니다';setStatus('자동 분석 중 · 결과가 준비되면 화면에 표시합니다.');
    }
    renderCards();draw();
  }catch(error){if(token!==state.token)return;$('busy').hidden=true;setStatus(error.message,true);}
}
function path(ctx,points){ctx.beginPath();points.forEach(([x,y],i)=>i?ctx.lineTo(x,y):ctx.moveTo(x,y));ctx.closePath();}
function drawBase(){
  if(!state.image){$('stage').classList.add('empty');return;}
  for(const id of ['originalCanvas','resultCanvas']){const canvas=$(id);canvas.width=state.image.naturalWidth;canvas.height=state.image.naturalHeight;canvas.getContext('2d').drawImage(state.image,0,0);}
  if(!state.result)return;
  const ctx=$('resultCanvas').getContext('2d'),scale=state.image.naturalWidth/1032;
  state.result.pads.forEach((pad,pi)=>{
    ctx.save();path(ctx,pad.polygon);ctx.clip();ctx.fillStyle='#00ff28';
    pad.voids.forEach((v,vi)=>{path(ctx,v.polygon);ctx.fill();if(state.editing&&state.voidSelection?.[0]===pi&&state.voidSelection?.[1]===vi){ctx.strokeStyle='white';ctx.lineWidth=4*scale;ctx.stroke();}});ctx.restore();
    path(ctx,pad.polygon);ctx.strokeStyle=pi===state.pad?'#a4ffd1':'#00ff28';ctx.lineWidth=(pi===state.pad?3:1.8)*scale;ctx.setLineDash([7*scale,5*scale]);ctx.stroke();ctx.setLineDash([]);
    const xs=pad.polygon.map(p=>p[0]),ys=pad.polygon.map(p=>p[1]);const cx=(Math.min(...xs)+Math.max(...xs))/2,cy=Math.min(state.image.naturalHeight-40*scale,Math.max(...ys)+15*scale);
    const label=state.dirty?`${pad.id} 수정 중`:`${pad.id} ${pad.ratio.toFixed(1)}%`;ctx.font=`bold ${28*scale}px "Segoe UI",sans-serif`;ctx.textBaseline='top';const width=ctx.measureText(label).width;
    ctx.fillStyle='#08110de0';ctx.fillRect(cx-width/2-6*scale,cy-2*scale,width+12*scale,35*scale);ctx.fillStyle='#00ff28';ctx.fillText(label,cx-width/2,cy);
  });
}
function renderCards(){
  const container=$('padCards');container.replaceChildren();
  $('ledSummary').textContent=state.result?.led_results&&!state.dirty?Object.entries(state.result.led_results).map(([led,value])=>`${led} 최대 ${value.toFixed(2)}%`).join(' · '):'';
  for(let i=0;i<(state.result?.pads.length||0);i++){
    const pad=state.result?.pads[i];const card=document.createElement('button');card.className='pad-card'+(i===state.pad?' active':'');card.disabled=!pad;
    const top=text('div','','pad-top');const id=text('span',`P${i+1}`,'pad-id');id.append(text('span',pad?.led||'등록 패드','pad-position'));const ratio=text('span',pad&&!state.dirty?pad.ratio.toFixed(1):'—','pad-ratio');ratio.append(text('small','%'));top.append(id,ratio);
    const detail=text('div','','pad-details');detail.append(text('span',pad?`보이드 ${pad.count}개`:'분석 대기'),text('span',pad&&!state.dirty?`${pad.void_area.toLocaleString()} / ${pad.pad_area.toLocaleString()} px²`:'—'));
    const bar=text('div','','pad-bar');const fill=document.createElement('i');fill.style.width=pad?`${Math.min(100,pad.ratio)}%`:'0';bar.append(fill);card.append(top,detail,bar);
    card.onclick=()=>{state.pad=i;renderCards();draw();if(pad.warning)setStatus(pad.warning,true);};container.append(card);
  }
}
function setView(view){state.view=view;$('stage').classList.toggle('compare',view==='compare');$('stage').classList.toggle('original',view==='original');document.querySelectorAll('[data-view]').forEach(b=>b.classList.toggle('active',b.dataset.view===view));}
document.querySelectorAll('[data-view]').forEach(b=>b.onclick=()=>setView(b.dataset.view));
document.querySelectorAll('[data-filter]').forEach(b=>b.onclick=()=>{state.filter=b.dataset.filter;document.querySelectorAll('[data-filter]').forEach(x=>x.classList.toggle('active',x===b));renderList();});
$('search').oninput=renderList;
async function upload(files){
  let first;const failures=[];$('files').disabled=true;
  try{for(const file of files){if(file.size>32*1024*1024){failures.push(`${file.name}: 최대 32 MB입니다.`);continue;}setStatus(`${file.name} 업로드 중…`);try{const result=await api(`/api/import?name=${encodeURIComponent(file.name)}${$('templateSelect').value?'&template_id='+encodeURIComponent($('templateSelect').value):''}`,{method:'POST',headers:{'Content-Type':'application/octet-stream'},body:file});first??=result.ids[0];failures.push(...result.errors);}catch(error){failures.push(error.message);}}
    await refresh();if(first)await select(first);if(failures.length)toast(failures.join('\n'));else if(first)toast($('templateSelect').value?'등록된 패드로 분석합니다.':'업로드 완료. 현재 사진으로 패드를 등록하세요.');
  }finally{$('files').disabled=false;$('files').value='';}
}
$('files').onchange=e=>upload([...e.target.files]);$('emptyUpload').onclick=()=>$('files').click();
$('dropzone').onclick=()=>$('files').click();$('dropzone').onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();$('files').click();}};
for(const name of ['dragenter','dragover'])$('dropzone').addEventListener(name,e=>{e.preventDefault();$('dropzone').classList.add('drag');});
for(const name of ['dragleave','drop'])$('dropzone').addEventListener(name,e=>{e.preventDefault();$('dropzone').classList.remove('drag');if(name==='drop')upload([...e.dataTransfer.files]);});
$('download').onclick=()=>{if(state.selected&&!state.dirty){const a=document.createElement('a');a.href=`/api/jobs/${state.selected}/export.png`;a.download='';a.click();}};
$('expand').onclick=async()=>{try{if(document.fullscreenElement)await document.exitFullscreen();else await $('stage').requestFullscreen();}catch{toast('이 브라우저에서는 전체 화면을 지원하지 않습니다.');}};
$('sensitivity').oninput=e=>$('sensitivityValue').textContent=Number(e.target.value).toFixed(2);
$('reanalyze').onclick=async()=>{if(!state.selected)return;if(!$('templateSelect').value){toast('검사 설정을 먼저 선택하거나 패드를 등록하세요.');return;}try{const result=await api(`/api/jobs/${state.selected}/analyze`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({sensitivity:Number($('sensitivity').value),template_id:$('templateSelect').value})});await refresh();await select(result.id);}catch(e){toast(e.message);}};
function updateEditing(){$('editPanel').hidden=!state.editing;$('editToggle').hidden=state.editing;$('stage').classList.toggle('editing',state.editing);$('download').disabled=!state.result||state.editing;}
$('editToggle').onclick=()=>{state.editing=true;state.history=[];setView('result');updateEditing();setStatus('선택 삭제 또는 드래그로 보이드를 추가한 후 「수정 적용 및 재계산」을 누르세요.');};
$('cancelEdits').onclick=()=>select(state.selected);
function saveHistory(){state.history.push(JSON.stringify(state.result));if(state.history.length>30)state.history.shift();}
function dirty(){state.dirty=true;state.voidSelection=null;renderCards();draw();setStatus('수정 중 · 적용하면 면적과 비율을 다시 계산합니다.');}
function contains(x,y,points){let hit=false;for(let i=0,j=points.length-1;i<points.length;j=i++){const a=points[i],b=points[j];if((a[1]>y)!==(b[1]>y)&&x<(b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0])hit=!hit;}return hit;}
function imagePoint(event){const box=$('resultCanvas').getBoundingClientRect();return [(event.clientX-box.left)*$('resultCanvas').width/box.width,(event.clientY-box.top)*$('resultCanvas').height/box.height];}
let start;
$('resultCanvas').onpointerdown=e=>{if(!registration&&state.editing){start=imagePoint(e);$('resultCanvas').setPointerCapture(e.pointerId);}};
$('resultCanvas').onpointerup=e=>{
  if(registration){const p=imagePoint(e);registration.points.push(p);draw();return;}
  if(!state.result)return;const point=imagePoint(e);const pi=state.result.pads.findIndex(p=>contains(...point,p.polygon));
  if(!state.editing){if(pi>=0){state.pad=pi;renderCards();draw();}return;}
  if(!start)return;const origin=start;start=null;
  const radius=Math.min(Math.hypot(point[0]-origin[0],point[1]-origin[1]),origin[0],origin[1],state.result.width-origin[0],state.result.height-origin[1]);
  if(radius>6){const target=state.result.pads.findIndex(p=>contains(...origin,p.polygon));if(target<0){toast('패드 안에서 드래그를 시작하세요.');return;}saveHistory();const polygon=Array.from({length:64},(_,i)=>[origin[0]+radius*Math.cos(i*Math.PI/32),origin[1]+radius*Math.sin(i*Math.PI/32)]);state.result.pads[target].voids.push({polygon});dirty();}
  else if(pi>=0){state.pad=pi;const vi=state.result.pads[pi].voids.findIndex(v=>contains(...point,v.polygon));state.voidSelection=vi>=0?[pi,vi]:null;draw();renderCards();}
};
$('resultCanvas').onpointercancel=()=>{start=null;};
$('deleteVoid').onclick=()=>{if(!state.voidSelection){toast('삭제할 보이드를 먼저 클릭하세요.');return;}saveHistory();const [pi,vi]=state.voidSelection;state.result.pads[pi].voids.splice(vi,1);dirty();};
$('undo').onclick=()=>{if(!state.history.length)return;state.result=JSON.parse(state.history.pop());dirty();};
$('saveEdits').onclick=async()=>{if(!state.result)return;$('saveEdits').disabled=true;try{const body={pads:state.result.pads.map(p=>({id:p.id,voids:p.voids.map(v=>({polygon:v.polygon}))}))};const result=await api(`/api/jobs/${state.selected}/edits`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});state.editing=false;await refresh();await select(result.id);toast('수정한 영역으로 면적 비율을 다시 계산했습니다.');}catch(error){toast(error.message);}finally{$('saveEdits').disabled=false;}};


function draw(){
 drawBase();if(!registration||!state.image)return;
 const c=$('resultCanvas').getContext('2d');c.lineWidth=Math.max(2,state.image.naturalWidth/350);c.font=`bold ${Math.max(16,state.image.naturalWidth/45)}px sans-serif`;
 for(const pad of registration.pads){path(c,pad.polygon);c.strokeStyle='#68e6b8';c.stroke();c.fillStyle='#68e6b8';c.fillText(`${pad.id} / ${pad.led}`,pad.polygon[0][0],pad.polygon[0][1]);}
 if(registration.points.length){c.strokeStyle='#ffce69';c.beginPath();registration.points.forEach(([x,y],i)=>{if(i)c.lineTo(x,y);else c.moveTo(x,y);});c.stroke();for(const [x,y] of registration.points){c.fillStyle='#ffce69';c.fillRect(x-3,y-3,6,6);}}
}
async function loadTemplates(selected){
 templates=await api('/api/templates');const selector=$('templateSelect');const previous=selected||selector.value;selector.replaceChildren(new Option('새 제품 — 패드 등록 필요',''));
 for(const t of templates)selector.add(new Option(`${t.name} (${t.pads.length}패드)`,t.id));selector.value=previous;
}
function showRegistered(){
 const list=$('registeredPads');list.replaceChildren();
 registration.pads.forEach((pad,i)=>{const row=text('div',`${pad.id} · ${pad.led} `);const remove=text('button','삭제','button ghost');remove.onclick=()=>{registration.pads.splice(i,1);registration.pads.forEach((p,j)=>p.id=`P${j+1}`);showRegistered();draw();};row.append(remove);list.append(row);});
}
$('registerPads').onclick=()=>{
 if(!state.image){toast('기준으로 사용할 사진을 먼저 올리세요.');return;}
 if(state.editing){toast('보이드 수정을 저장하거나 취소한 뒤 등록하세요.');return;}
 registration={pads:[],points:[]};state.result=null;renderCards();$('registration').hidden=false;setView('result');$('busy').hidden=true;$('download').disabled=true;$('editToggle').disabled=true;$('reanalyze').disabled=true;showRegistered();draw();setStatus('패드 둘레를 차례로 클릭한 뒤 패드 확정을 누르세요.');
};
$('finishPad').onclick=()=>{
 if(!registration)return;const led=$('ledName').value.trim();
 if(registration.points.length<3||!led){toast('LED번호와 3개 이상의 꼭짓점이 필요합니다.');return;}
 registration.pads.push({id:`P${registration.pads.length+1}`,led,polygon:registration.points});registration.points=[];showRegistered();draw();
};
$('undoPoint').onclick=()=>{if(registration){registration.points.pop();draw();}};
$('cancelRegistration').onclick=()=>select(state.selected);
$('saveTemplate').onclick=async()=>{
 if(!registration)return;if(registration.points.length){toast('작성 중인 패드를 먼저 확정하세요.');return;}
 const name=$('templateName').value.trim();if(!name||!registration.pads.length){toast('설정 이름과 패드를 입력하세요.');return;}
 $('saveTemplate').disabled=true;
 try{const template=await api('/api/templates',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name,job_id:state.selected,pads:registration.pads})});await loadTemplates(template.id);registration=null;$('registration').hidden=true;await $('reanalyze').onclick();}
 catch(e){toast(e.message);}finally{$('saveTemplate').disabled=false;}
};
$('stage').classList.add('empty');$('busy').hidden=true;renderCards();loadTemplates().catch(e=>toast(e.message));refresh();setInterval(refresh,3000);

// Development only: defer reload while the inspector has unsaved work.
let devVersion=null;
async function checkDevelopmentVersion(){
 try{
  const info=await api('/api/dev/version');if(!info.enabled)return;
  if(devVersion===null){devVersion=info.version;return;}
  if(info.version!==devVersion){
   if(registration||state.editing||state.dirty||$('files').disabled){
    setStatus('개발 업데이트가 준비됐습니다. 현재 편집을 저장하거나 취소하면 자동 반영됩니다.');return;
   }
   window.location.reload();
  }
 }catch{} // The development server may briefly restart between polls.
}
checkDevelopmentVersion();setInterval(checkDevelopmentVersion,2500);
