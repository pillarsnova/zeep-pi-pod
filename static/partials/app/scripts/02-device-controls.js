/* ---- track metadata: แสดงชื่อ/คำอธิบายภาษาคน แทนชื่อไฟล์ดิบ ---- */
const TRACK_META = [
  {re:/Night-Delta-Mix/i,       title:'กลางดึก', desc:'เสียงสำหรับช่วงกลางดึก', badge:null},
  {re:/WindDown-Theta-Mix/i,    title:'ก่อนนอน', desc:'เสียงสำหรับช่วงก่อนนอน', badge:null},
  {re:/Nap-ThetaAlpha-Mix/i,    title:'งีบสั้น', desc:'เสียงสำหรับช่วงงีบ', badge:null},
  {re:/Relax-Alpha-Mix/i,       title:'ผ่อนคลาย', desc:'เสียงสำหรับพักผ่อน', badge:null},
  {re:/Rain-Pink-Mix/i,         title:'เสียงฝน', desc:'บรรยากาศเสียงฝน', badge:null},
];
function trackMeta(name){
  for (const m of TRACK_META) if (m.re.test(name)) return m;
  return {title: name.replace(/\.[^.]+$/,'').replace(/[-_]+/g,' '), desc:'ไฟล์เสียงในเครื่อง', badge:null};
}
let selectedTrack = null;
// The bedside player owns the playback policy. The Pi handles repeat-one
// natively; queue mode advances only after a natural end reported by the Pi.
let unifiedAudioMode = 'repeat_one';
let unifiedAudioModeInitialized = false;
let unifiedAudioPendingTrack = null;
let unifiedAudioRequestSequence = 0;
const trackEls = {};
function selectGender(g){
  selectedGender = g;
  document.querySelectorAll('#genderSeg button').forEach(b=>b.classList.toggle('sel', b.dataset.g === g));
  renderLoginBaseline();
}

/* ---- outputs: build once, update in place (avoid re-render stealing taps) ---- */
const outputEls = {};
function buildOutputs(){
  const root = document.getElementById('outputs');
  Object.keys(names).forEach(k=>{
    const d = document.createElement('div'); d.className = 'toggle';
    const info = document.createElement('div'); info.className = 'output-info';
    const icon = document.createElement('span'); icon.className = 'device-icon';
    icon.setAttribute('aria-hidden','true');
    icon.innerHTML = `<svg class="ui-icon"><use href="#ui-icon-${outputIcons[k]||'center'}"/></svg>`;
    const copy = document.createElement('div');
    const titleWrap = document.createElement('div');
    const title = document.createElement('b'); title.textContent = names[k];
    titleWrap.appendChild(title);
    if (editableLabels.has(k)){
      const edit = document.createElement('button');
      edit.className = 'edit-btn'; edit.textContent = '✎ แก้ชื่อ';
      edit.onclick = ()=>startEditLabel(k);
      titleWrap.appendChild(edit);
    }
    const sub = document.createElement('div'); sub.className = 'muted';
    copy.appendChild(titleWrap); copy.appendChild(sub);
    info.appendChild(icon); info.appendChild(copy);
    const btn = document.createElement('button'); btn.className = 'btn';
    if (pulseOutputs.has(k)){
      btn.onclick = ()=>runOutputAction(k, btn, true);
      btn.textContent = 'OFF'; sub.textContent = 'กดเพื่อพ่น 5 วินาที';
    } else {
      btn.onclick = ()=>runOutputAction(k, btn, false);
      btn.textContent = 'OFF'; sub.textContent = 'GPIO LOW';
    }
    d.appendChild(info); d.appendChild(btn);
    root.appendChild(d);
    outputEls[k] = {title, sub, btn, editing:false};
  });
}
async function runOutputAction(k, btn, pulse){
  const targetOn = !current.gpio?.[k];
  // Let the whole control card respond immediately. The confirmed device
  // state still comes from Pi/ESP telemetry; this intent is visual feedback
  // while the HTTP command is in flight.
  if(btn){
    btn.dataset.interactionIntent=pulse?'pulse':targetOn?'on':'off';
    btn.dataset.interactionTarget=k;
    btn.dataset.interactionLabel=pulse?`พ่น ${currentLabel(k)}`:`${targetOn?'เปิด':'ปิด'} ${currentLabel(k)}`;
  }
  if(pulse)setComfortCommandFeedback(k,'pending');
  const result = await withBusy(btn, ()=>pulse
    ? post(`/api/pulse/${k}`)
    : post(`/api/output/${k}`, {on:targetOn}));
  if (!result){
    if(pulse)setComfortCommandFeedback(k,'error',2600);
    flashCommandResult(btn,false);
    return;
  }
  const label = currentLabel(k);
  if(pulse)setComfortCommandFeedback(k,'success',1800);
  const successMessage=pulse
    ?(currentPrincipal?.role==='admin'?`${label}: ส่งคำสั่ง Pulse แล้ว`:`เริ่มพ่น ${label} แล้ว`)
    :`${label}: ${targetOn ? 'เปิด' : 'ปิด'}แล้ว`;
  toast(successMessage,'ok',2400);
  flashCommandResult(btn,true);
}
function updateOutputs(gpio={}){
  const gpioOk = !!current.system?.gpio_available;
  const safetyLatched = !!current.safety?.latched;
  const adminView=currentPrincipal?.role==='admin';
  Object.keys(names).forEach(k=>{
    const on = !!gpio[k];
    const el = outputEls[k];
    const {sub, btn} = el;
    if (!el.editing) el.title.textContent = currentLabel(k);
    if (!gpioOk || (safetyLatched && !(k==='led' && !on))){
      // นโยบาย: ไม่มี mock — เชื่อมต่อไม่ได้ = สั่งไม่ได้ ปุ่มปิดจริง
      sub.textContent = adminView
        ?'GPIO เชื่อมต่อไม่ได้'
        :safetyLatched?'โหมดปลอดภัย':'กำลังเชื่อมต่อ';
      btn.textContent = adminView?'OFF':'—';
      btn.disabled = true;
      btn.classList.remove('on');
      return;
    }
    if (pulseOutputs.has(k)){
      // ปุ่มพ่นแสดง OFF ปกติ → ON ระหว่างพ่น → กลับ OFF เอง
      sub.textContent = on ? 'กำลังพ่น…' : 'กดเพื่อพ่น 5 วินาที';
      // While busy, the pressed button owns its own state — don't fight it.
      if (!btn.classList.contains('busy')){
        btn.textContent = adminView?(on?'ON':'OFF'):(on?'กำลังพ่น':'พ่น');
        btn.disabled = on;
      }
    } else {
      sub.textContent = adminView?`GPIO ${on ? 'HIGH' : 'LOW'}`:(on?'เปิดอยู่':'ปิดอยู่');
      if (!btn.classList.contains('busy')){
        btn.textContent = adminView?(on?'ON':'OFF'):(on?'ปิด':'เปิด');
        btn.disabled = false;
      }
    }
    btn.classList.toggle('on', on);
  });
}

async function quickOutputAction(name, btn){
  return runOutputAction(name, btn, false);
}
function quickAirconTemp(value, btn){
  if(!Number.isInteger(value)||value<AIRCON_DESIRED_TEMPERATURE_MIN_C||value>AIRCON_DESIRED_TEMPERATURE_MAX_C){
    toast(`เลือกอุณหภูมิได้ ${AIRCON_DESIRED_TEMPERATURE_MIN_C}–${AIRCON_DESIRED_TEMPERATURE_MAX_C} °C`,'error');
    return;
  }
  // Send the user-facing value. The Pi API is the single source of truth that
  // applies the -5 °C bias before publishing the command to ESP32 Aircon.
  airconCommand(`temp ${value}`, btn);
}
function quickDeviceNote(device, fallback){
  if(!device)return `${fallback} · รอข้อมูล`;
  const status=String(device.status||'no_data').replace('_',' ');
  const age=Number(device.data_age_s);
  return `${device.model||fallback} · ${status}${Number.isFinite(age)?` · ${age.toFixed(1)}s`:''}`;
}
function setQuickMetric(valueId, noteId, value, unit, device, digits=0){
  const valueEl=document.getElementById(valueId),noteEl=document.getElementById(noteId);
  if(!valueEl||!noteEl)return;
  const hasValue=value!==null&&value!==undefined&&value!==''&&typeof value!=='boolean';
  const number=hasValue?Number(value):NaN;
  const suffix=unit?` ${unit}`:'';
  valueEl.textContent=Number.isFinite(number)?`${number.toFixed(digits)}${suffix}`:`--${suffix}`;
  noteEl.textContent=quickDeviceNote(device,noteEl.dataset.fallback||noteEl.textContent.split(' · ')[0]);
}
function soundDisplayMetric(environment={}){
  const raw=environment.sound_dba_est;
  if(typeof raw==='number'&&Number.isFinite(raw)&&raw>=30&&raw<=130){
    return {value:raw,unit:'dBA',digits:1,source:'esp32'};
  }
  return {value:null,unit:'dBA',digits:1,source:'missing'};
}
function renderControlCenter(environment={},aircon={},bed={},safety={},gpio={},system={}){
  const devices=environment.devices||{};
  setQuickMetric('quickTemp','quickTempNote',environment.temperature_c,'°C',devices.sht3x_dis,1);
  setQuickMetric('quickHumidity','quickHumidityNote',environment.humidity_rh,'%RH',devices.sht3x_dis,1);
  setQuickMetric('quickCo2','quickCo2Note',environment.co2_ppm,'ppm',devices.mhz19c,0);
  setQuickMetric('quickPm25','quickPm25Note',environment.pm2_5_ug_m3,'µg/m³',devices.pms7003,1);
  setQuickMetric('quickVoc','quickVocNote',environment.voc_index,'',devices.sgp40,0);
  const soundMetric=soundDisplayMetric(environment);
  setQuickMetric('quickSound','quickSoundNote',soundMetric.value,soundMetric.unit,devices.sph0645,soundMetric.digits);

  const health=document.getElementById('quickEnvironmentStatus');
  const live=Number(environment.live_count)||0,total=Number(environment.total_count)||6;
  let healthClass='success',healthText=`Sensor พร้อม ${live}/${total}`;
  if(safety.latched){healthClass='danger';healthText='EMERGENCY · Safety locked';}
  else if(live===0){healthClass='danger';healthText='Sensor ไม่พร้อม';}
  else if(live<total||!safety.ready){healthClass='warning';healthText=`ใช้งานแบบจำกัด · Sensor ${live}/${total}`;}
  health.className=`control-health ${healthClass}`;health.textContent=healthText;

  const airconState=document.getElementById('quickAirconState');
  if(airconState)airconState.textContent=aircon.connected&&!aircon.stale
    ? `Online · ${aircon.power===true?'ON':aircon.power===false?'OFF':'ไม่ทราบสถานะ'}`
    : aircon.stale?'ESP32 Aircon · Stale':'ESP32 Aircon · Offline';
  const stopState=document.getElementById('quickStopState');
  if(stopState)stopState.textContent='Audio · Aircon';

  const gpioOk=!!system.gpio_available,roomOn=!!gpio.led,starOn=!!gpio.star_light,roomBtn=document.getElementById('quickRoomLightBtn'),starBtn=document.getElementById('quickStarLightBtn');
  document.getElementById('quickLightState').textContent=`ไฟเพดาน ${gpioOk?(roomOn?'ON':'OFF'):'Unavailable'} · ไฟดาว ${gpioOk?(starOn?'ON':'OFF'):'Unavailable'}`;
  roomBtn.textContent=roomOn?'ปิดไฟห้อง':'เปิดไฟห้อง';
  roomBtn.classList.toggle('quick-active',roomOn);
  if(!roomBtn.classList.contains('busy'))roomBtn.disabled=!gpioOk||(!!safety.latched&&roomOn);
  if(starBtn){
    starBtn.textContent=starOn?'ปิดไฟดาว':'เปิดไฟดาว';
    starBtn.classList.toggle('quick-active',starOn);
    if(!starBtn.classList.contains('busy'))starBtn.disabled=!gpioOk||!!safety.latched;
  }

  [['quickRedFaceBtn','red_light_face'],['quickRedBodyBtn','red_light_body'],['quickRedLegBtn','red_light_leg']].forEach(([id,name])=>{
    const button=document.getElementById(id),on=!!gpio[name];
    button.classList.toggle('quick-active',on);
    button.setAttribute('aria-pressed',on?'true':'false');
    if(!button.classList.contains('busy'))button.disabled=!gpioOk||!!safety.latched;
  });
}

function renderSmartResponse(response={}){
  const panel=document.getElementById('smartResponsePanel');
  if(!panel)return;
  const status=String(response.status||'blocked');
  const badge=document.getElementById('smartModeBadge');
  badge.className=`smart-mode ${status==='stable'?'stable':status==='critical'?'critical':''}`;
  badge.textContent=response.mode==='shadow'?'SHADOW · OBSERVE ONLY':'SMART RESPONSE · OFFLINE';
  document.getElementById('smartResponseSummary').textContent=response.summary||'ยังไม่ได้รับผลประเมินจาก Pi';
  document.getElementById('smartResponsePhase').textContent=`${response.phase_label||'ไม่ทราบ Phase'} · ${response.policy_version||'รอ policy'} · ${response.cadence_s||1}s`;
  const readiness=document.getElementById('smartResponseReadiness');
  const blockers=Array.isArray(response.blockers)?response.blockers:[];
  readiness.textContent=blockers.length?`Auto Response · LOCKED (${blockers.length})`:'Auto Response · SHADOW READY';
  readiness.classList.toggle('safe',!blockers.length);
  readiness.classList.toggle('lock',!!blockers.length);

  const root=document.getElementById('smartRecommendations');
  root.replaceChildren();
  const levels={critical:0,blocked:1,attention:2,watch:3,stable:4};
  const items=(Array.isArray(response.recommendations)?response.recommendations:[])
    .slice().sort((a,b)=>(levels[a.level]??9)-(levels[b.level]??9)).slice(0,6);
  if(!items.length){
    const item=document.createElement('div');item.className='smart-recommendation blocked';
    const title=document.createElement('b');title.textContent='รอข้อมูลจาก Pi';
    const detail=document.createElement('span');detail.textContent='ยังไม่มีคำแนะนำจาก Smart Response policy';
    item.append(title,detail);root.appendChild(item);
  }else items.forEach(rec=>{
    const item=document.createElement('div');item.className=`smart-recommendation ${rec.level||'watch'}`;
    const title=document.createElement('b');title.textContent=rec.title||rec.domain||'คำแนะนำ';
    const detail=document.createElement('span');detail.textContent=rec.suggestion?`${rec.detail} · ${rec.suggestion}`:rec.detail||'';
    item.append(title,detail);root.appendChild(item);
  });

  const blockerRoot=document.getElementById('smartBlockers');
  blockerRoot.replaceChildren();
  const blockerSummary=document.getElementById('smartBlockerSummary');
  blockerSummary.textContent=blockers.length
    ? `เงื่อนไขที่ต้องแก้ก่อนเปิด Auto Response · ${blockers.length} รายการ`
    : 'ไม่มี Hardware blocker · ระบบยังคงอยู่ใน Shadow Mode';
  if(!blockers.length){
    const chip=document.createElement('span');chip.className='smart-blocker';chip.textContent='ยังไม่อนุญาต Actuation จนกว่าจะผ่านการทดสอบและอนุมัติ policy';blockerRoot.appendChild(chip);
  }else blockers.forEach(blocker=>{
    const chip=document.createElement('span');chip.className='smart-blocker';chip.textContent=blocker.message||blocker.code;blockerRoot.appendChild(chip);
  });
}
