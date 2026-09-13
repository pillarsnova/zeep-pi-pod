/* ---------- audio visualizer: Spotify-style animated bars ---------- */
const vizPhases = Array.from({length:44}, ()=>Math.random()*Math.PI*2);
let vizLevel = 0;
function drawViz(ts){
  const c = document.getElementById('audioViz');
  if (c){
    const dpr = window.devicePixelRatio || 1;
    const w = c.clientWidth, h = c.clientHeight;
    if (w && (c.width !== Math.round(w*dpr) || c.height !== Math.round(h*dpr))){
      c.width = Math.round(w*dpr); c.height = Math.round(h*dpr);
    }
    const x = c.getContext('2d');
    x.setTransform(dpr,0,0,dpr,0,0);
    x.clearRect(0,0,w,h);
    const m = current.music || {};
    const target = (m.playing && !m.paused) ? 1 : 0.07;
    vizLevel += (target - vizLevel) * 0.055;      // smooth attack/decay
    const t = ts/1000, n = vizPhases.length, bw = w/n;
    const grad = x.createLinearGradient(0,0,w,0);
    grad.addColorStop(0,'#0fa8c9'); grad.addColorStop(.55,'#19e3ff'); grad.addColorStop(1,'#a78bfa');
    x.fillStyle = grad;
    for (let i = 0; i < n; i++){
      const wave = Math.sin(t*2.1 + vizPhases[i])*.5
                 + Math.sin(t*3.7 + i*.9)*.3
                 + Math.sin(t*1.3 + i*2.3)*.2;
      const amp = (0.22 + 0.78*Math.abs(wave)) * vizLevel;
      const bh = Math.max(3, amp*(h-10));
      x.beginPath();
      x.roundRect(i*bw + bw*0.24, h-5-bh, bw*0.52, bh, 3);
      x.fill();
    }
  }
  requestAnimationFrame(drawViz);
}
requestAnimationFrame(drawViz);

let booted = false;
function dismissBoot(){
  if (booted) return;
  booted = true;
  const el = document.getElementById('boot');
  el.classList.add('hide');
  setTimeout(()=>el.remove(), 600);
}

function render(s, source='ws'){
  dismissBoot();
  lastServerUpdateAt = Date.now();
  serverReachable = true;
  current = s;
  featureReportShare = !!s.features?.session_report_share;
  const e = s.sensor?.esp32 || {}, h2 = s.sensor?.sensorhub2 || {}, a = s.aircon || {}, bedctl = s.bed_control || {}, b = s.sensor?.bcg || {}, m = s.music || {}, sys = s.system || {};
  const environment=renderEnvironmentSensors(s.sensor?.environment,e,h2,b);
  renderSystemHealth(sys);
  renderSafety(s.safety || {});
  if(document.body.dataset.view==='monitor')evaluateMonitorAlerts(e,h2,environment,b,sys);

  // ---- per-person session: overlay, user pill, logout button ----
  const se = s.session || {};
  const sessionChanged = se.active !== sessionState.active || se.session_id !== sessionState.session_id;
  sessionState = se;
  renderAdminOccupantActions(se);
  const loginEl = document.getElementById('login');
  if (loginEl){
    loginEl.classList.toggle('hide', !!currentPrincipal);
    loginEl.setAttribute('aria-hidden',currentPrincipal?'true':'false');
  }
  const userPill = document.getElementById('userPill');
  const topUserAvatar = document.getElementById('topUserAvatar');
  const topUserName = document.getElementById('topUserName');
  const topUserMeta = document.getElementById('topUserMeta');
  const topUserState = document.getElementById('topUserState');
  const logoutBtn = document.getElementById('logoutBtn');
  if (se.active){
    userPill.className = `top-user ${se.recording?'live':'waiting'}`;
    const shownAccount=identityLabel(se);
    topUserAvatar.textContent=String(shownAccount).trim().slice(0,1).toUpperCase();
    topUserName.textContent=shownAccount;
    if (se.recording){
      topUserMeta.textContent=currentPrincipal?.role==='admin'
        ?`${genderTh(se.gender)} · ${displayAge(se)} · บันทึกแล้ว ${se.samples??0} จุด`
        :`${genderTh(se.gender)} · ${displayAge(se)} · กำลังบันทึกการพัก`;
      topUserState.textContent='● กำลังบันทึก';
    } else {
      topUserMeta.textContent=currentPrincipal?.role==='admin'
        ?`${genderTh(se.gender)} · ${displayAge(se)} · ${sessionStartGateText(se,sys)}`
        :`${genderTh(se.gender)} · ${displayAge(se)} · กำลังเตรียมเริ่มบันทึก`;
      topUserState.textContent=currentPrincipal?.role==='admin'?'รอ HR / RR':'กำลังเตรียม';
    }
    logoutBtn.style.display = currentPrincipal?.role==='user'&&authPod.owns_active_session?'':'none';
  } else {
    userPill.className = 'top-user';
    topUserAvatar.textContent='Z';
    topUserName.textContent=currentPrincipal?.role==='admin'?'ยังไม่มีผู้ใช้งาน':'พร้อมเริ่มการพัก';
    topUserMeta.textContent=currentPrincipal?.role==='admin'
      ?'เริ่ม Session เพื่อดูข้อมูลการใช้งาน'
      :'เข้าสู่ระบบเพื่อดูข้อมูลการพักของคุณ';
    topUserState.textContent=currentPrincipal?.role==='admin'?'NO SESSION':'ยังไม่เริ่ม';
    logoutBtn.style.display = 'none';
  }
  const environmentLive=Number(environment.live_count)||0,environmentTotal=Number(environment.total_count)||6;
  const safetyFaults=Array.isArray(s.safety?.faults)?s.safety.faults:[];
  const userSafetyFaults=safetyFaults.filter(f=>
    f.severity==='critical'
    ||['gpio_unavailable','esp32_no_data','esp32_stale','co2_unavailable','temperature_unavailable'].includes(f.code));
  setSafetyUserAlert(false);
  if(s.safety?.latched){
    const title='ระบบเข้าสู่โหมดปลอดภัย';
    const detail=se.active
      ?'กรุณาหยุดการพัก เปิดประตูออกจาก ZEEP และแจ้งทีมงานทันที'
      :'กรุณารอให้ทีมงานตรวจสาเหตุก่อนเริ่มใช้งานครั้งถัดไป';
    setPageMessage('danger',title,detail);
    setSafetyUserAlert(true,title,detail,se.active);
  }else if(se.active&&userSafetyFaults.length){
    if(currentPrincipal?.role==='admin'){
      setPageMessage('danger','พบเหตุด้านความปลอดภัยที่ต้องดูแล',userSafetyFaults.map(f=>f.message||f.code).join(' · '));
    }else{
      setPageMessage('danger','ระบบตรวจวัดที่จำเป็นขาดการเชื่อมต่อ','กรุณาหยุดการพัก เปิดประตูออกจาก ZEEP และแจ้งทีมงานทันที');
    }
    setSafetyUserAlert(
      true,
      'พบเหตุด้านความปลอดภัยที่ต้องดูแล',
      currentPrincipal?.role==='admin'
        ?'กรุณาหยุด Session ช่วยผู้ใช้งานเปิดประตูออกจาก ZEEP และตรวจสอบระบบทันที'
        :'กรุณาหยุดการพัก เปิดประตูออกจาก ZEEP และแจ้งทีมงานทันที',
      true,
    );
  }else if(!se.active&&userSafetyFaults.length){
    if(currentPrincipal?.role==='admin'){
      setPageMessage('warning','ระบบยังไม่พร้อมเริ่ม Session',userSafetyFaults.map(f=>f.message||f.code).join(' · '));
    }else{
      setPageMessage('warning','ระบบกำลังตรวจความพร้อม','กรุณารอทีมงานตรวจระบบให้เรียบร้อยก่อนเริ่มการพัก');
    }
    setSafetyUserAlert(
      true,
      'ระบบกำลังตรวจความพร้อม',
      'กรุณารอให้ทีมงานตรวจระบบให้เรียบร้อยก่อนเริ่มการพัก',
      false,
      'warning',
    );
  }else if(!environmentLive&&!b.connected){
    if(currentPrincipal?.role==='admin'){
      setPageMessage('danger','เซ็นเซอร์ไม่พร้อม','Sensor Hub ทั้งสองชุดและ BCG ยังไม่มีข้อมูลสด กรุณาตรวจหน้า Monitor');
    }else{
      setPageMessage('info','ระบบกำลังเชื่อมต่อข้อมูล','กรุณารอทีมงานตรวจการเชื่อมต่อสักครู่');
    }
  }else if(!se.active){
    setPageMessage('info',currentPrincipal?.role==='admin'?'ตู้ว่างและพร้อมตรวจสอบ':'การพักครั้งนี้สิ้นสุดแล้ว',currentPrincipal?.role==='admin'?'ยังไม่มีผู้ใช้งานในตู้นี้':'ดูประวัติการใช้งานได้ หรือออกจากบัญชีเพื่อเริ่มการพักครั้งใหม่');
  }else if(!se.recording){
    if(currentPrincipal?.role==='admin'){
      setPageMessage('warning','รอสัญญาณชีพก่อนบันทึก',`${sessionStartGateText(se,sys)} · ระบบจะยังไม่สร้าง Timeline จนกว่า HR และ RR จะพร้อม`);
    }else{
      setPageMessage('info','กำลังเตรียมบันทึกการพัก','กรุณานอนในท่าสบายสักครู่ ระบบจะเริ่มให้อัตโนมัติ');
    }
  }else if(environmentLive<environmentTotal||!b.connected){
    const missing=Object.values(environment.devices||{}).filter(d=>d.status!=='live').map(d=>d.model).concat(b.connected?[]:['BCG']).join(', ');
    if(currentPrincipal?.role==='admin'){
      setPageMessage('warning','Session กำลังบันทึก แต่ข้อมูลบางส่วนไม่พร้อม',`${missing||'Sensor'} ไม่อยู่ในสถานะ Live`);
    }else{
      setPageMessage('info','กำลังเชื่อมต่อข้อมูลบางส่วน','การพักยังดำเนินต่อได้ และระบบจะเก็บข้อมูลที่พร้อมตามปกติ');
    }
  }else{
    setPageMessage(
      'success',
      currentPrincipal?.role==='admin'?'Session กำลังบันทึก':'กำลังบันทึกการพัก',
      currentPrincipal?.role==='admin'
        ?'Sensor สิ่งแวดล้อม 6/6 และ BCG ส่งข้อมูลสดตามปกติ'
        :'ระบบพร้อมแล้ว พักผ่อนได้ตามสบาย',
    );
  }
  if (sessionChanged && se.active){
    const sel = document.getElementById('historyUser');
    if (sel){ sel.value = se.account_key||se.email||se.username; refreshHistory(); }
  }

  const espOk = !!e.connected;
  const espAge = Number(e.data_age_s);
  const espFallback = !!e.fallback_active;
  const espAgeText = Number.isFinite(espAge) ? `${espAge.toFixed(1)} วินาที` : 'ไม่ทราบอายุ';
  const hub2Ok = !!h2.connected;
  const hub2Age = Number(h2.data_age_s);
  const hub2Fallback = !!h2.fallback_active;
  const hub2AgeText = Number.isFinite(hub2Age) ? `${hub2Age.toFixed(1)} วินาที` : 'ไม่ทราบอายุ';
  const bcgAge = Number(b.data_age_s);
  const bcgFallback = !!b.fallback_active;
  const bcgAgeText = Number.isFinite(bcgAge) ? `${bcgAge.toFixed(1)} วินาที` : 'ไม่ทราบอายุ';
  const sphStatus=environment.devices?.sph0645?.status||'offline';
  const soundInvalidReason=e.sound_invalid_reason||environment.devices?.sph0645?.invalid_values?.sound_dba_est;
  const soundMetric=soundDisplayMetric(environment);
  const adminView=currentPrincipal?.role==='admin';
  document.getElementById('sound').title = adminView
    ? environment.sound_dba_est==null
      ? `INVALID · ${soundInvalidReason||'ESP32 ยังไม่ส่ง sound_dba'}`
      : 'SPH0645LM4H-B · รับ sound_dba จาก ESP32 โดยตรง'
    : environment.sound_dba_est==null?'กำลังรวบรวมข้อมูลเสียง':'ข้อมูลเสียงพร้อม';
  const soundQuality=document.getElementById('soundQuality');
  soundQuality.textContent=adminView
    ? espFallback
      ? `⚠ SPH0645LM4H-B · ข้อมูลไม่สด (${espAgeText})`
      : environment.sound_dba_est==null
      ? espOk?`✕ SPH0645LM4H-B · INVALID · ${soundInvalidReason||'รอ sound_dba'}`:'SPH0645LM4H-B · ไม่เชื่อมต่อ'
      : sphStatus==='live'
        ? '✓ SPH0645LM4H-B · ESP32 direct'
        : `⚠ SPH0645LM4H-B · ${sphStatus}`
    : environment.sound_dba_est==null?'กำลังรวบรวมข้อมูลเสียง':'ข้อมูลเสียงพร้อม';
  soundQuality.className=`sensor-note ${espFallback||environment.sound_dba_est==null||sphStatus!=='live'?'status-warn':'status-good'}`;
  document.getElementById('environmentCard').title=adminView
    ?[espFallback?`Pi5 Sensor Set 1 fallback ${espAgeText}`:null,hub2Fallback?`ESP32 Air Sensor fallback ${hub2AgeText}`:null].filter(Boolean).join(' · ')
    :(espFallback||hub2Fallback?'กำลังอัปเดตข้อมูลสภาพแวดล้อม':'ข้อมูลสภาพแวดล้อมพร้อม');

  document.getElementById('bcgConn').textContent = b.connected ? 'Connected' : 'Disconnected';
  document.getElementById('bcgConn').className = b.connected ? 'status-good' : 'status-bad';
  document.getElementById('bcgConnChip').className=`status-chip ${b.connected?'success':'danger'}`;
  document.getElementById('bcgPackets').textContent = b.packets || 0;
  document.getElementById('bcgSensorPacket').textContent = b.sensor_packet_id ?? '--';
  const rawBedDiff=b.raw_status_code!=null&&b.raw_status_code!==b.status_code;
  document.getElementById('bcgCode').textContent = rawBedDiff
    ? `${b.status_code??'--'} · Raw ${b.raw_status_code}`
    : b.status_code ?? '--';
  document.getElementById('bcgHr').textContent = b.heart_rate_bpm ?? '--';
  document.getElementById('bcgRr').textContent = (b.respiration_rate==null) ? '--' : Number(b.respiration_rate).toFixed(1);
  const canonicalBedText=BCG_STATUS_TH[b.status_code] || b.status_text || '--';
  const rawBedText=BCG_STATUS_TH[b.raw_status_code] || b.raw_status_text || '--';
  document.getElementById('bcgBedStatus').textContent = rawBedDiff
    ? `${canonicalBedText} · Raw: ${rawBedText}`
    : canonicalBedText;
  if(rawBedDiff){
    const exit=b.bed_exit_evidence||{};
    document.getElementById('bcgBedStatus').title=exit.transient_rejected
      ? 'Raw Get out of bed ยังไม่ผ่านการยืนยัน จึงไม่บังคับเป็น Wake'
      : 'แสดง Raw และสถานะที่ระบบยืนยันแล้ว';
  }else{
    document.getElementById('bcgBedStatus').title='';
  }
  document.getElementById('bcgCard').title=bcgFallback?`Fallback: ค่า BCG ล่าสุด · อายุ ${bcgAgeText}`:'';
  renderSleepState(s.sleep || {},se,b);
  const bcgStats = drawBCG(updateBCGWave(b));
  renderBCGReading(b, bcgStats || {count:0,dynamicRange:0});

  updateOutputs(s.gpio || {});
  updateRedLights(s.gpio || {});
  renderAircon(a);
  renderBedControl(bedctl);
  renderControlCenter(environment,a,bedctl,s.safety||{},s.gpio||{},sys);
  renderSmartResponse(s.smart_response||{});
  renderSimpleDashboard(s,environment,b,se);
  renderUnifiedControl(s,environment,a,bedctl,m);
  renderControlDebug(s);

  const musicCard = document.getElementById('musicCard');
  musicCard.classList.toggle('playing', !!m.playing && !m.paused);
  musicCard.classList.toggle('paused', !!m.paused);
  document.getElementById('nowPlaying').textContent =
    m.track ? `${trackMeta(m.track).title}${m.loop ? ' · วนซ้ำ' : ''}${m.paused ? ' (พักอยู่)' : ''}` : 'ยังไม่ได้เล่นเพลง';
  Object.entries(trackEls).forEach(([t, e])=>
    e.row.classList.toggle('now', !!m.playing && m.track === t));
  const vol = document.getElementById('volume');
  if (document.activeElement !== vol){
    vol.value = m.volume ?? 60;
    document.getElementById('volText').textContent = m.volume ?? 60;
  }

  if(espFallback){
    const p=document.getElementById('esp32Pill');p.className='pill warn';p.innerHTML=`<span class="dot"></span>Pi5 Sensor Set 1 fallback · ${espAgeText}`;
  }else setPill('esp32Pill', espOk, 'Pi5 Sensor Set 1', 'Pi5 Sensor Set 1');
  if(hub2Fallback){
    const p=document.getElementById('hub2Pill');p.className='pill warn';p.innerHTML=`<span class="dot"></span>ESP32 Air Sensor fallback · ${hub2AgeText}`;
  }else setPill('hub2Pill', hub2Ok, 'ESP32 Air Sensor', 'ESP32 Air Sensor');
  if(a.stale){
    const p=document.getElementById('controlHubPill');p.className='pill warn';p.innerHTML='<span class="dot"></span>ESP32 Aircon stale';
  }else setPill('controlHubPill', !!a.connected, 'ESP32 Aircon', 'ESP32 Aircon');
  if(bedctl.stale){
    const p=document.getElementById('controlHub2Pill');p.className='pill warn';p.innerHTML='<span class="dot"></span>ESP32 Bed stale';
  }else setPill('controlHub2Pill', !!bedctl.connected, 'ESP32 Bed', 'ESP32 Bed');
  if(bcgFallback){
    const p=document.getElementById('bcgPill');p.className='pill warn';p.innerHTML=`<span class="dot"></span>BCG fallback · ${bcgAgeText}`;
  }else setPill('bcgPill', !!b.connected, 'BCG', 'BCG');
  document.getElementById('uptime').textContent = fmtUptime(sys.uptime_s);
  const gpioOk = !!sys.gpio_available;
  const g = document.getElementById('gpioAvail');
  g.textContent = gpioOk ? 'พร้อมใช้งาน' : 'เชื่อมต่อไม่ได้';
  g.className = 'v ' + (gpioOk ? 'status-good' : 'status-bad');
  // ประตูปิดปุ่มจริงเมื่อ GPIO เชื่อมต่อไม่ได้ (ช่วง pulse doorBusy เป็นคนคุม)
  const dO = document.getElementById('doorOpenBtn'), dC = document.getElementById('doorCloseBtn');
  if (!gpioOk){ dO.disabled = dC.disabled = true; }
  else if (!doorBusy){ dO.disabled = false; dC.disabled = !!s.safety?.latched; }
  document.getElementById('musicPlayBtn').disabled=!!s.safety?.latched;
  document.getElementById('musicPauseBtn').disabled=!!s.safety?.latched;
  // error จริงของ sensor/GPIO โชว์หน้างานเพื่อไล่สาเหตุได้ทันที
  const errs = [];
  if (!gpioOk && sys.gpio_error) errs.push(sys.gpio_error);
  if (!espOk && e.error) errs.push(`Pi5 Sensor Set 1: ${e.error}`);
  if (!hub2Ok && h2.error) errs.push(`ESP32 Air Sensor: ${h2.error}`);
  if (!a.connected && a.error) errs.push(`ESP32 Aircon: ${a.error}`);
  if (!bedctl.connected && bedctl.error) errs.push(`ESP32 Bed: ${bedctl.error}`);
  if (!b.connected && b.error) errs.push(`BCG: ${b.error}`);
  const errEl = document.getElementById('sensorErr');
  errEl.style.display = errs.length ? '' : 'none';
  errEl.textContent = errs.join(' · ');

  // ---- event log (จาก state.events_tail — ล่าสุดอยู่บน) ----
  const evRoot = document.getElementById('eventLog');
  const evs = (s.events_tail || []).slice().reverse();
  if (evs.length){
    evRoot.innerHTML = '';
    evs.forEach(ev=>{
      const row = document.createElement('div');
      const bad = /disconnect|fail|error/i.test(ev.event);
      const good = /connect|start|login|logout/i.test(ev.event) && !bad;
      row.className = `event-row ${bad ? 'err' : good ? 'ok' : ''}`;
      const ts = document.createElement('span');
      try { ts.textContent = new Date(ev.ts).toLocaleTimeString('th-TH', {hour:'2-digit', minute:'2-digit'}); }
      catch { ts.textContent = '--:--'; }
      const msg = document.createElement('span');
      const detail = Object.entries(ev)
        .filter(([k])=>!['ts','component','event'].includes(k))
        .map(([k,v])=>`${k}=${typeof v === 'object' ? JSON.stringify(v) : v}`).join(' ');
      msg.textContent = `${ev.component} · ${ev.event}${detail ? ' · ' + detail : ''}`;
      row.append(ts, msg);
      evRoot.appendChild(row);
    });
  }
  const et = document.getElementById('esp32Text');
  et.textContent = espOk ? 'เชื่อมต่อแล้ว' : espFallback ? `Fallback · ค่าล่าสุด ${espAgeText}` : 'ขาดการเชื่อมต่อ';
  et.className = 'v ' + (espOk ? 'status-good' : espFallback ? 'status-warn' : 'status-bad');
  const h2t = document.getElementById('hub2Text');
  h2t.textContent = hub2Ok ? 'เชื่อมต่อแล้ว' : hub2Fallback ? `Fallback · ค่าล่าสุด ${hub2AgeText}` : 'ขาดการเชื่อมต่อ';
  h2t.className = 'v ' + (hub2Ok ? 'status-good' : hub2Fallback ? 'status-warn' : 'status-bad');
  const bt = document.getElementById('bcgText');
  bt.textContent = b.connected ? 'เชื่อมต่อแล้ว' : bcgFallback ? `Fallback · ค่าล่าสุด ${bcgAgeText}` : 'ขาดการเชื่อมต่อ';
  bt.className = 'v ' + (b.connected ? 'status-good' : bcgFallback ? 'status-warn' : 'status-bad');
  const cpu=document.getElementById('cpuTemp'),cpuValue=Number(sys.health?.cpu_temp_c);
  cpu.textContent=Number.isFinite(cpuValue)?`${cpuValue.toFixed(1)}°C`:'--';cpu.className=`v ${Number.isFinite(cpuValue)&&cpuValue<75?'status-good':'status-warn'}`;
}

function setConnectionStatus(mode){
  const el=document.getElementById('wsStatus'); if(!el)return;
  const age=lastServerUpdateAt?Math.max(0,Math.round((Date.now()-lastServerUpdateAt)/1000)):null;
  const adminView=currentPrincipal?.role==='admin';
  if(mode==='ws'){
    el.className='pill good';
    el.innerHTML=`<span class="dot"></span>${adminView?'Realtime · WebSocket':'เชื่อมต่อแล้ว'}`;
  }else if(mode==='rest'){
    el.className='pill warn';
    el.innerHTML=`<span class="dot"></span>${adminView?'Fallback · REST polling':'กำลังซิงก์ข้อมูล'}`;
  }else{
    el.className='pill bad';
    el.innerHTML=adminView
      ?`<span class="dot"></span>Offline${age==null?'':` · ค่าล่าสุด ${age}s`}`
      :`<span class="dot"></span>กำลังเชื่อมต่อ${age==null?'':` · อัปเดตล่าสุด ${age} วินาที`}`;
  }
}
async function pollStateFallback(){
  const ctrl=new AbortController(),timeout=setTimeout(()=>ctrl.abort(),1800);
  try{
    const r=await fetch('/api/state',{cache:'no-store',signal:ctrl.signal});
    if(!r.ok)throw new Error(`HTTP ${r.status}`);
    render(await r.json(),'rest');setConnectionStatus('rest');
  }catch{serverReachable=false;setConnectionStatus('offline');}
  finally{clearTimeout(timeout);}
}
function startRestFallback(){
  if(restFallbackTimer||sessionEndShown)return;
  pollStateFallback();restFallbackTimer=setInterval(pollStateFallback,5000);
}
function stopRestFallback(){if(restFallbackTimer){clearInterval(restFallbackTimer);restFallbackTimer=null;}}
function connectWS(){
  let ws;
  try {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    ws = new WebSocket(`${proto}://${location.host}/ws`);
  } catch {
    setConnectionStatus('offline');startRestFallback();
    wsReconnectTimer=setTimeout(connectWS,3000);
    return;
  }
  activeWS=ws;
  ws.onopen = ()=>{
    stopRestFallback();setConnectionStatus('ws');
    if (wsWasDown){ toast('กลับมาเชื่อมต่อแล้ว', 'ok', 2200); loadTracks(); loadUsers(); }
    wsWasDown = false;
  };
  ws.onmessage = e=>{try{
    const message=JSON.parse(e.data);
    if(message?.type==='session_ended'){
      // Admin จบ/ไล่ Session: แท็บเล็ตไม่มีข้อมูลของตัวเอง จึงมากับ notice นี้
      showSessionEndScreen({...(message.report||{}),report_share:message.report_share});
      return;
    }
    render(message,'ws');setConnectionStatus('ws');
  }catch{}};
  ws.onclose = event=>{
    if(activeWS===ws)activeWS=null;
    if(event.code===4401){
      const target=currentPrincipal?.role==='admin'?ADMIN_LOGIN_PATH:USER_LOGIN_PATH;
      currentPrincipal=null;authenticatedAppStarted=false;
      history.replaceState({},'',target);setLoginAudience(target===ADMIN_LOGIN_PATH?'admin':'user');
      applyRoleUI(null);document.getElementById('login').classList.remove('hide');loadPublicStatus();return;
    }
    if(sessionEndShown||(event.code===4403&&sessionEndInProgress))return;
    if(event.code===4403&&currentPrincipal?.role==='user'){
      // An Admin ended or force-kicked this physical Session. The backend has
      // already persisted the report and revoked the occupant cookie; return
      // the shared touch screen to Login instead of leaving stale controls.
      currentPrincipal=null;authenticatedAppStarted=false;
      authPod={occupied:false,owns_active_session:false};
      sessionState={...sessionState,active:false,recording:false};
      applyRoleUI(null);setConnectionStatus('offline');
      history.replaceState({},'',USER_LOGIN_PATH);
      const overlay=document.getElementById('login');
      overlay.classList.remove('hide');overlay.setAttribute('aria-hidden','false');
      setLoginAudience('user');showLoginError('Admin จบ Session นี้แล้ว กรุณาเข้าสู่ระบบใหม่','warning');
      loadPublicStatus();return;
    }
    setConnectionStatus('offline');startRestFallback();
    if (!wsWasDown){ toast('หลุดการเชื่อมต่อ — กำลังพยายามใหม่…', 'error', 2600); dismissBoot(); }
    wsWasDown = true;
    clearTimeout(wsReconnectTimer);wsReconnectTimer=setTimeout(connectWS,1500);
  };
  ws.onerror = ()=>ws.close();
}
updateDashboardClock();
setInterval(updateDashboardClock,1000);
setInterval(()=>{
  if(sessionEndShown)return;
  if(lastServerUpdateAt&&Date.now()-lastServerUpdateAt>12000){
    serverReachable=false;setConnectionStatus('offline');startRestFallback();
    if(activeWS?.readyState===WebSocket.OPEN)activeWS.close();
  }else if(!serverReachable)setConnectionStatus('offline');
},1000);
buildOutputs();
setLoginAudience(loginAudience);
loadAgeBaselines();
bootstrapAuth();
setTimeout(dismissBoot, 4000); // fallback: never trap the UI behind the boot screen
