/* Optional auth: open the page once with ?token=XXXX to store it. */
const _params = new URLSearchParams(location.search);
if (_params.get('token')) localStorage.setItem('zeep_token', _params.get('token'));
let offlineTicket = null;
let offlineIdentifier = '';

function cookieValue(name){
  const item=document.cookie.split('; ').find(v=>v.startsWith(`${name}=`));
  return item?decodeURIComponent(item.slice(name.length+1)):'';
}
function authenticatedHeaders(headers={}){
  const csrf=cookieValue('zeep_csrf');
  return csrf?{...headers,'X-CSRF-Token':csrf}:headers;
}

/* ---- feedback system: toast, persistent flat message, confirmation modal ---- */
const FEEDBACK_META={
  info:{icon:'ℹ',title:'ข้อมูล'},success:{icon:'✓',title:'สำเร็จ'},ok:{icon:'✓',title:'สำเร็จ'},
  warning:{icon:'⚠',title:'โปรดตรวจสอบ'},error:{icon:'!',title:'ไม่สำเร็จ'}
};
function toast(msg, type='info', ms=3200){
  const root = document.getElementById('toasts');
  const t = document.createElement('div');
  const kind=type||'info',meta={...(FEEDBACK_META[kind]||FEEDBACK_META.info)};
  if(kind==='error'&&currentPrincipal?.role!=='admin')meta.title='ลองอีกครั้ง';
  t.className = `toast ${kind}`;
  t.innerHTML=`<span class="toast-icon">${meta.icon}</span><div><div class="toast-title">${meta.title}</div><div class="toast-message"></div></div><button class="toast-close" aria-label="ปิด">×</button>`;
  t.querySelector('.toast-message').textContent=msg;
  const dismiss=()=>{t.classList.add('hide');setTimeout(()=>t.remove(),350)};
  t.querySelector('.toast-close').onclick=dismiss;
  root.appendChild(t);
  setTimeout(dismiss,ms);
}
function setPageMessage(type,title,message){
  const root=document.getElementById('pageMessage');if(!root)return;
  const meta={info:['ℹ'],success:['✓'],warning:['⚠'],danger:['!'],loading:['']}[type]||['ℹ'];
  root.className=`flat-message ${type}`;
  root.innerHTML=`<span class="flat-icon">${meta[0]}</span><div><b></b><span></span></div>`;
  root.querySelector('b').textContent=title;root.querySelector('span:last-child').textContent=message;
}
function setSafetyUserAlert(active,title='',message='',showDoorAction=false,tone='danger'){
  const root=document.getElementById('safetyUserAlert');if(!root)return;
  root.hidden=!active;
  if(!active)return;
  root.className=`safety-user-alert ${tone}`;
  document.getElementById('safetyUserAlertTitle').textContent=title;
  document.getElementById('safetyUserAlertDetail').textContent=message;
  document.getElementById('safetyUserAlertAction').hidden=!showDoorAction;
}
let modalResolve=null;
function confirmAction({title='ยืนยันการทำงาน',message='',confirmText='ยืนยัน',tone='warning',icon='!'}){
  if(modalResolve)modalResolve(false);
  const layer=document.getElementById('confirmModal'),card=document.getElementById('confirmCard'),accept=document.getElementById('confirmAccept');
  document.getElementById('confirmTitle').textContent=title;document.getElementById('confirmMessage').textContent=message;
  document.getElementById('confirmIcon').textContent=icon;accept.textContent=confirmText;accept.className=`btn ${tone==='danger'?'danger':'primary'}`;
  card.className=`modal-card ${tone==='danger'?'danger':''}`;layer.classList.remove('hide');accept.focus();
  return new Promise(resolve=>{
    modalResolve=resolve;
    const finish=value=>{layer.classList.add('hide');modalResolve=null;document.onkeydown=null;resolve(value)};
    accept.onclick=()=>finish(true);document.getElementById('confirmCancel').onclick=()=>finish(false);
    layer.onclick=e=>{if(e.target===layer)finish(false)};
    document.onkeydown=e=>{if(e.key==='Escape'){document.onkeydown=null;finish(false)}};
  });
}

/* ---- command feedback: explicit pending overlay + short ACK/ERROR flash ---- */
let deviceInteractionSequence=0;
const deviceInteractionTimers=new WeakMap();

function deviceInteractionLabel(control){
  if(!control)return 'คำสั่งอุปกรณ์';
  const raw=control.dataset?.interactionLabel
    ||control.dataset?.controlLabel
    ||control.getAttribute?.('aria-label')
    ||control.getAttribute?.('title')
    ||control.textContent
    ||'คำสั่งอุปกรณ์';
  return String(raw).replace(/\s+/g,' ').trim().slice(0,72);
}

function ensureDeviceInteractionFeedback(zone){
  let feedback=zone.querySelector(':scope > .device-interaction-feedback');
  if(feedback)return feedback;
  feedback=document.createElement('div');
  feedback.className='device-interaction-feedback';
  feedback.setAttribute('role','status');
  feedback.setAttribute('aria-live','polite');
  const icon=document.createElement('span');
  icon.className='device-interaction-icon';
  icon.setAttribute('aria-hidden','true');
  icon.innerHTML='<svg class="ui-icon"><use href="#ui-icon-refresh"/></svg>';
  const copy=document.createElement('b');
  feedback.append(icon,copy);
  zone.appendChild(feedback);
  return feedback;
}

// Every user-facing device card shares one command lifecycle.  The floating
// feedback is intentionally separate from the confirmed sensor/status label:
// PENDING is the request in flight, SUCCESS is the API acknowledgement, and
// ERROR means no acknowledgement was received.
function setDeviceInteraction(control,state){
  const zone=control?.closest?.('.device-zone');
  if(!zone)return;
  let token=control.dataset.interactionToken;
  if(state==='pending'){
    token=String(++deviceInteractionSequence);
    control.dataset.interactionToken=token;
    zone.dataset.interactionToken=token;
    clearTimeout(deviceInteractionTimers.get(zone));
  }else if(!token||zone.dataset.interactionToken!==token){
    return;
  }

  const feedback=ensureDeviceInteractionFeedback(zone);
  const label=deviceInteractionLabel(control);
  const intent=control.dataset.interactionIntent||'command';
  const target=control.dataset.interactionTarget||'';
  const adminView=currentPrincipal?.role==='admin';
  const meta={
    pending:{icon:'refresh',text:`กำลังส่ง · ${label}`},
    success:{icon:'check',text:`รับคำสั่งแล้ว · ${label}`},
    error:{icon:'alert',text:adminView?`ส่งไม่สำเร็จ · ${label}`:`ยังไม่ตอบสนอง · ลองอีกครั้ง`},
  }[state];
  if(!meta)return;

  zone.classList.remove('interaction-pending','interaction-success','interaction-error');
  zone.classList.add(`interaction-${state}`);
  zone.dataset.interactionIntent=intent;
  if(target)zone.dataset.interactionTarget=target;else delete zone.dataset.interactionTarget;
  zone.setAttribute('aria-busy',state==='pending'?'true':'false');
  feedback.dataset.state=state;
  setUiIconReference(feedback.querySelector('.device-interaction-icon .ui-icon'),meta.icon);
  feedback.querySelector('b').textContent=meta.text;

  if(state!=='pending'){
    const completedToken=token;
    const timer=setTimeout(()=>{
      if(zone.dataset.interactionToken!==completedToken)return;
      zone.classList.remove('interaction-pending','interaction-success','interaction-error');
      zone.removeAttribute('aria-busy');
      delete zone.dataset.interactionIntent;
      delete zone.dataset.interactionTarget;
      delete zone.dataset.interactionToken;
      delete control.dataset.interactionToken;
    },state==='success'?1500:2200);
    deviceInteractionTimers.set(zone,timer);
  }
}

function commandProgressOverlay(control){
  if(!control||control.tagName!=='BUTTON')return null;
  const overlay=document.createElement('span');
  overlay.className='command-progress-overlay';
  if(control.getBoundingClientRect().width<96)overlay.classList.add('compact');
  const spinner=document.createElement('i');spinner.setAttribute('aria-hidden','true');
  const label=document.createElement('b');label.textContent='กำลังทำงาน';
  overlay.append(spinner,label);control.appendChild(overlay);
  return overlay;
}
function flashCommandResult(control,ok){
  if(!control||control.tagName!=='BUTTON')return;
  const className=ok?'command-ok':'command-failed';
  control.classList.remove('command-ok','command-failed');
  requestAnimationFrame(()=>control.classList.add(className));
  setTimeout(()=>control.classList.remove(className),ok?850:1100);
}
async function withBusy(btn, fn){
  if (btn && btn.classList.contains('busy')) return null;
  let progress=null;
  if (btn){
    btn.classList.add('busy');btn.disabled=true;btn.setAttribute('aria-busy','true');
    progress=commandProgressOverlay(btn);
    setDeviceInteraction(btn,'pending');
  }
  try {
    const result=await fn();
    setDeviceInteraction(btn,result===null||result===false?'error':'success');
    return result;
  } catch(error) {
    setDeviceInteraction(btn,'error');
    throw error;
  }
  finally {
    if(btn){progress?.remove();btn.classList.remove('busy');btn.disabled=false;btn.removeAttribute('aria-busy');}
  }
}

async function post(url, body){
  const adminView=currentPrincipal?.role==='admin';
  if (!serverReachable){ toast(adminView?'ส่งคำสั่งไม่ได้ — network/server ยังไม่เชื่อมต่อ':'ระบบยังไม่พร้อมรับคำสั่ง กรุณาลองอีกครั้ง', 'error'); return null; }
  const opt = {method:'POST', headers:authenticatedHeaders({'Content-Type':'application/json'})};
  if (body !== undefined) opt.body = JSON.stringify(body);
  let r;
  try { r = await fetch(url, opt); }
  catch { toast(adminView?'ส่งคำสั่งไม่ได้ — เชื่อมต่อ server ไม่ได้':'ยังเชื่อมต่อระบบไม่ได้ กรุณาลองอีกครั้ง', 'error'); return null; }
  if (!r.ok){
    if (r.status === 429){ toast('คำสั่งก่อนหน้ายังทำงานอยู่ — รอสักครู่', '', 1800); return null; }
    let msg = '';
    if(adminView){
      try { const d=await r.json(),detail=d.detail;msg=typeof detail==='string'?detail:(detail?.message||JSON.stringify(detail)); } catch { msg = await r.text(); }
    }
    if (r.status === 401) msg = adminView?'Session เข้าสู่ระบบหมดอายุ กรุณาเข้าสู่ระบบใหม่':'กรุณาเข้าสู่ระบบอีกครั้ง';
    if(!adminView)msg=({403:'บัญชีนี้ยังใช้คำสั่งนี้ไม่ได้',404:'ยังไม่พบฟังก์ชันที่เลือก',409:'สถานะเพิ่งเปลี่ยน กรุณาลองอีกครั้ง',422:'กรุณาตรวจค่าที่เลือกแล้วลองอีกครั้ง'})[r.status]
      ||(r.status>=500?'ระบบกำลังกลับมาทำงาน กรุณาลองอีกครั้ง':'ทำรายการไม่สำเร็จ กรุณาลองอีกครั้ง');
    toast(msg || `HTTP ${r.status}`, 'error');
    return null;
  }
  return await r.json();
}

/* ---- Admin Control Debug: raw command trace without optimistic ACK ---- */
const debugCommandEntries=[];
let debugCommandSequence=0;

function debugJson(value){
  if(value===undefined)return '—';
  try{return JSON.stringify(value,null,2);}catch{return String(value);}
}

function renderDebugCommandLog(){
  const root=document.getElementById('debugCommandLog');if(!root)return;
  root.replaceChildren();
  if(!debugCommandEntries.length){
    const empty=document.createElement('div');empty.className='debug-log-empty';
    empty.append('ยังไม่มีคำสั่งทดสอบ',document.createElement('br'));
    const note=document.createElement('small');note.textContent='เมื่อกดปุ่ม ระบบจะแสดง Endpoint, Payload, Response และเวลาตอบกลับที่นี่';
    empty.appendChild(note);root.appendChild(empty);return;
  }
  debugCommandEntries.forEach(entry=>{
    const article=document.createElement('article');article.className=`debug-log-entry ${entry.status}`;
    const head=document.createElement('div');head.className='debug-log-entry-head';
    const identity=document.createElement('div');
    const device=document.createElement('span');device.textContent=`#${entry.id} · ${entry.device}`;
    const command=document.createElement('b');command.textContent=entry.command;
    identity.append(device,command);
    const badge=document.createElement('strong');badge.textContent=entry.status==='pending'?'SENT':entry.status==='ack'?'ACK':'ERROR';
    head.append(identity,badge);
    const route=document.createElement('code');route.textContent=`POST ${entry.endpoint}`;
    const meta=document.createElement('div');meta.className='debug-log-meta';
    const at=new Date(entry.timestamp).toLocaleTimeString('th-TH',{hour12:false});
    meta.textContent=`${at}${entry.httpStatus?` · HTTP ${entry.httpStatus}`:''}${Number.isFinite(entry.latencyMs)?` · ${entry.latencyMs} ms`:''}`;
    const payloadTitle=document.createElement('span');payloadTitle.textContent='PAYLOAD';
    const payload=document.createElement('pre');payload.textContent=debugJson(entry.payload);
    const responseTitle=document.createElement('span');responseTitle.textContent='RESPONSE';
    const response=document.createElement('pre');response.textContent=entry.status==='pending'?'รอการตอบกลับ…':debugJson(entry.response);
    article.append(head,route,meta,payloadTitle,payload,responseTitle,response);
    root.appendChild(article);
  });
}

function clearDebugCommandLog(){
  debugCommandEntries.length=0;
  renderDebugCommandLog();
}

async function debugSend(btn,device,command,endpoint,payload){
  if(currentPrincipal?.role!=='admin'){
    toast('Control Debug ใช้ได้เฉพาะผู้ดูแลระบบ','error');
    return null;
  }
  const entry={
    id:++debugCommandSequence,device,command,endpoint,payload,
    timestamp:Date.now(),status:'pending',httpStatus:null,latencyMs:null,response:null,
  };
  debugCommandEntries.unshift(entry);
  if(debugCommandEntries.length>100)debugCommandEntries.length=100;
  renderDebugCommandLog();
  return withBusy(btn,async()=>{
    const started=performance.now();
    try{
      const options={method:'POST',headers:authenticatedHeaders({'Content-Type':'application/json'})};
      if(payload!==undefined)options.body=JSON.stringify(payload);
      const response=await fetch(endpoint,options);
      const raw=await response.text();
      let data=null;
      if(raw){try{data=JSON.parse(raw);}catch{data={text:raw};}}
      entry.httpStatus=response.status;
      entry.latencyMs=Math.round(performance.now()-started);
      entry.response=data;
      entry.status=response.ok?'ack':'error';
      toast(response.ok?`${device}: ${command} ได้รับ ACK แล้ว`:`${device}: ${command} ไม่สำเร็จ (HTTP ${response.status})`,response.ok?'ok':'error',3000);
      return response.ok?data:null;
    }catch(error){
      entry.latencyMs=Math.round(performance.now()-started);
      entry.response={error:error instanceof Error?error.message:String(error)};
      entry.status='error';
      toast(`${device}: ส่ง ${command} ไม่ได้`,'error');
      return null;
    }finally{
      renderDebugCommandLog();
    }
  });
}

function debugAirconTemperature(btn){
  const desired=Number(document.getElementById('debugAirconTemp')?.value);
  if(!Number.isInteger(desired)||desired<AIRCON_DEBUG_TEMPERATURE_MIN_C||desired>AIRCON_DEBUG_TEMPERATURE_MAX_C){toast(`Control Debug เลือกอุณหภูมิ ${AIRCON_DEBUG_TEMPERATURE_MIN_C}–${AIRCON_DEBUG_TEMPERATURE_MAX_C} °C`,'error');return;}
  return debugSend(btn,'ESP32 Aircon',`direct temp ${desired}`,'/api/aircon/command',{command:`temp ${desired}`,direct:true});
}

async function debugAirconFanLevel(btn){
  const result=await debugSend(btn,'ESP32 Aircon','fan next 1–5','/api/aircon/command',{command:'fan'});
  if(result?.aircon){
    current.aircon=result.aircon;
    renderAircon(current.aircon);
  }
  return result;
}

async function debugSetAirconFanReference(btn){
  const level=Number(document.getElementById('debugAirconFanReference')?.value);
  if(!Number.isInteger(level)||level<1||level>5){toast('ระดับพัดลมอ้างอิงต้องอยู่ระหว่าง 1–5','error');return null;}
  const result=await debugSend(btn,'ESP32 Aircon',`set fan reference ${level}`,'/api/admin/aircon/fan-level-reference',{level});
  if(result?.aircon){
    current.aircon=result.aircon;
    renderAircon(current.aircon);
    toast(`บันทึกระดับพัดลมอ้างอิง ${level}/5 แล้ว · ไม่มีการยิง IR`,'ok',3500);
  }
  return result;
}

function debugPlayTrack(btn){
  const track=document.getElementById('debugTrackSelect')?.value;
  if(!track){toast('ยังไม่มีไฟล์เสียงสำหรับทดสอบ','error');return;}
  return debugSend(btn,'Pi Audio',`play ${track}`,'/api/music/play',{track,loop:false,user_initiated:true});
}

function debugVolumeCommand(btn){
  const volume=Number(document.getElementById('debugVolume')?.value);
  return debugSend(btn,'Pi Audio',`volume ${volume}`,'/api/music/volume',{volume});
}
