const pulseOutputs = new Set(['aroma1','aroma2','aroma3','aroma4','steam']);
const editableLabels = new Set(['aroma1','aroma2','aroma3','aroma4']);
let airconRequestBusy = false;
// Control Hub 1 confirms that it transmitted each IR command, but the current
// air conditioner has no physical feedback channel for its louvre. Retain the
// latest acknowledged swing intent in this browser and prefer a future
// firmware-reported boolean when available. A fresh unknown state safely
// offers SWING ON as the first deterministic command.
let unifiedAirconSwingState = null;
// User controls expose the comfort target only. The Pi owns the -3°C hardware
// conversion, while Admin Debug shows both sides of the mapping.
const AIRCON_DESIRED_TEMPERATURE_MIN_C = 15;
const AIRCON_DESIRED_TEMPERATURE_MAX_C = 25;
const AIRCON_DEBUG_TEMPERATURE_MIN_C = 5;
const AIRCON_DEBUG_TEMPERATURE_MAX_C = 30;
// Preserve the user's unconfirmed selection while live WebSocket state keeps
// rendering. Without this draft, the selector jumps back once per second.
let unifiedAirconDraftTemp = null;
let unifiedAirconTempFeedbackTimer = null;
let bedRequestBusy = false;
// One acknowledged two-second movement equals one level. Keep this shared
// limit as the single source of truth for the controls, status text and SVG.
const BED_LEVEL_MAX = 5;
const BED_LEVEL_STORAGE_KEY = `zeep_bed_levels:${location.host}`;
function clampBedLevel(value){return Math.max(0,Math.min(BED_LEVEL_MAX,Math.round(Number(value)||0)));}
function loadBedVisualLevels(){
  try{
    const saved=JSON.parse(localStorage.getItem(BED_LEVEL_STORAGE_KEY)||'{}');
    return {head:clampBedLevel(saved.head),foot:clampBedLevel(saved.foot)};
  }catch(_error){return {head:0,foot:0};}
}
let bedVisualLevels=loadBedVisualLevels();
function saveBedVisualLevels(){
  try{localStorage.setItem(BED_LEVEL_STORAGE_KEY,JSON.stringify(bedVisualLevels));}catch(_error){}
}
let monitorAdvancedVisible = false;
const comfortCommandFeedback = {};
let comfortFeedbackTimer = null;
function currentLabel(k){ return (current.labels && current.labels[k]) || names[k]; }
function toggleAdvancedMonitor(){
  monitorAdvancedVisible=!monitorAdvancedVisible;
  document.body.classList.toggle('show-advanced-monitor',monitorAdvancedVisible);
  const btn=document.getElementById('monitorAdvancedBtn');
  if(btn){
    btn.classList.toggle('active',monitorAdvancedVisible);
    const label=btn.querySelector('.ui-button-label');
    if(label)label.textContent=monitorAdvancedVisible?'ซ่อน Advanced Diagnostics':'เปิด Advanced Diagnostics';
    btn.setAttribute('aria-expanded',monitorAdvancedVisible?'true':'false');
  }
  if(monitorAdvancedVisible){fetchRawPackets();fetchBcgTrend();requestAnimationFrame(()=>drawBCG(current.sensor?.bcg?.samples||[]));}
}
const DASHBOARD_TIME_ZONE=Intl.DateTimeFormat().resolvedOptions().timeZone||'Asia/Bangkok';
const dashboardTimeFormatter=new Intl.DateTimeFormat('th-TH-u-nu-latn',{
  timeZone:DASHBOARD_TIME_ZONE,hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false,
});
const dashboardDateFormatter=new Intl.DateTimeFormat('th-TH-u-nu-latn',{
  timeZone:DASHBOARD_TIME_ZONE,weekday:'short',day:'numeric',month:'short',year:'numeric',
});
function dashboardUtcOffset(now){
  try{
    const part=new Intl.DateTimeFormat('en-US',{
      timeZone:DASHBOARD_TIME_ZONE,timeZoneName:'longOffset',hour:'2-digit',
    }).formatToParts(now).find(item=>item.type==='timeZoneName')?.value||'GMT';
    return part.replace('GMT','UTC').replace(/:00$/,'');
  }catch(_error){
    const minutes=-now.getTimezoneOffset(),sign=minutes>=0?'+':'-';
    const absolute=Math.abs(minutes),hours=Math.floor(absolute/60),rest=absolute%60;
    return `UTC${sign}${hours}${rest?`:${String(rest).padStart(2,'0')}`:''}`;
  }
}
function updateDashboardClock(){
  const time=document.getElementById('dashClockTime'),date=document.getElementById('dashClockDate'),zone=document.getElementById('dashClockZone');
  if(!time||!date||!zone)return;
  const now=new Date();
  time.textContent=dashboardTimeFormatter.format(now);
  date.textContent=dashboardDateFormatter.format(now);
  zone.textContent=`${DASHBOARD_TIME_ZONE} · ${dashboardUtcOffset(now)}`;
  time.closest('.dash-clock')?.setAttribute('aria-label',`เวลาปัจจุบัน ${time.textContent} ${date.textContent} เขตเวลา ${zone.textContent}`);
}
function renderSafety(sf={}){
  const card=document.getElementById('safetyCard'),level=sf.level||'initializing';
  const visualLevel=level==='monitor'?'ready':level;
  const levelLabels={initializing:'กำลังเริ่มระบบ',monitor:'พร้อม',armed:'Auto เปิด',degraded:'เฝ้าระวัง',not_ready:'ยังไม่พร้อม',emergency:'ฉุกเฉิน'};
  card.classList.remove('emergency','not_ready','degraded','armed','monitor','ready','initializing');
  card.classList.add(visualLevel);
  document.getElementById('safetyLevel').textContent=levelLabels[level]||'กำลังตรวจระบบ';
  const ready=document.getElementById('safetyReadiness');
  ready.textContent=sf.latched?'ล็อกเหตุฉุกเฉิน':sf.armed?'Auto Response เปิด':sf.ready?'พร้อมใช้งาน':'ต้องตรวจสอบ';
  ready.className=`status-chip ${sf.latched?'danger':sf.ready?'success':'warning'}`;
  const faults=Array.isArray(sf.faults)?sf.faults:[],root=document.getElementById('safetyFaults');
  const hasCriticalFault=faults.some(f=>f.severity==='critical');
  setMonitorAlert(
    'safety_emergency',
    currentPrincipal?.role==='admin'&&(!!sf.latched||hasCriticalFault),
    sf.latched?'ระบบเข้าโหมดปลอดภัยแล้ว':'พบเหตุด้านความปลอดภัยที่ต้องตรวจทันที',
    'bad',
  );
  root.replaceChildren();
  const severityLabels={critical:'ฉุกเฉิน',blocking:'ต้องแก้ก่อนเปิด Auto',warning:'ควรตรวจ'};
  faults.forEach(f=>{const el=document.createElement('div');el.className=`safety-fault ${f.severity||''}`;el.title=f.code||'';const tag=document.createElement('b');tag.textContent=severityLabels[f.severity]||'แจ้งเตือน';const message=document.createElement('span');message.textContent=f.message||f.code;el.append(tag,message);root.appendChild(el);});
  if(!faults.length){const el=document.createElement('div');el.className='safety-fault clear';el.innerHTML='<b>พร้อม</b><span>ไม่พบเหตุที่ต้องแก้ไข</span>';root.appendChild(el);}
  const last=sf.last_action;
  const summary=document.getElementById('safetySummary');
  summary.textContent=sf.latched
    ? `โหมดปลอดภัยทำงานแล้ว · สาเหตุ ${last?.trigger||'สั่งจาก Admin'} · ตรวจสาเหตุก่อนปลดล็อก`
    : level==='not_ready'
      ? `ต้องแก้ ${faults.filter(f=>['critical','blocking'].includes(f.severity)).length} รายการก่อนเปิดการป้องกันอัตโนมัติ`
      : level==='degraded'
        ? `Pi ยังทำงาน Local ต่อ · มีคำเตือน ${faults.length} รายการ${sf.armed?' · Auto Response ยังเปิดอยู่':''}`
        : sf.armed
          ? 'พร้อมตอบสนองอัตโนมัติเมื่อพบเหตุ Critical'
          : 'ระบบพร้อม · การตอบสนองอัตโนมัติยังปิดอยู่';
  const basis=sf.threshold_basis||{};
  const basisText=basis.version
    ? `Basis ${basis.version} · ${basis.approved?'APPROVED':'NOT APPROVED'}`
    : 'ยังไม่มี Threshold Basis Version';
  summary.textContent=`${summary.textContent} · ${basisText}`;
  summary.title='ZEEP internal operating policy · ไม่ใช่เกณฑ์วินิจฉัยหรือเพดานสุขภาพสากล';
  const autoButton=document.getElementById('safetyAutoBtn'),autoLabel=document.getElementById('safetyAutoLabel');
  const autoAction=sf.armed?'disarm':'arm';
  autoButton.dataset.action=autoAction;
  autoLabel.textContent=sf.armed?'ปิดการป้องกันอัตโนมัติ':'เปิดการป้องกันอัตโนมัติ';
  const autoIcon=autoButton.querySelector('.ui-icon');if(autoIcon)setUiIconReference(autoIcon,sf.armed?'shield-off':'shield-check');
  autoButton.classList.toggle('active',!!sf.armed);
  autoButton.disabled=sf.armed?false:(!sf.ready||!!sf.latched);
  const ack=document.getElementById('safetyAckBtn');
  ack.hidden=!sf.latched;ack.disabled=!sf.latched;
  document.querySelectorAll('.safety-case-grid article').forEach(article=>article.classList.toggle('current',article.dataset.level===visualLevel));
  renderLoginSafety(sf);
}
function renderLoginSafety(sf={},occupied=authPod?.occupied){
  const el=document.getElementById('loginSafety');
  if(!el)return;
  const emergency=!!sf.latched||sf.level==='emergency';
  if(!emergency){el.className='login-safety login-off';el.textContent='';return;}
  // Login remains available so the User/Admin can reach the door controls.
  // The message is deliberately action-led and contains no engineering code.
  el.className='login-safety danger';
  el.textContent=occupied
    ?'ระบบอยู่ในโหมดปลอดภัย หากมีผู้ใช้อยู่ภายใน กรุณาเปิดประตู ออกจาก ZEEP และแจ้งทีมงาน'
    :'ระบบอยู่ในโหมดปลอดภัย กรุณาให้ทีมงานตรวจสอบก่อนเริ่มใช้งาน';
}
async function safetyAction(action,btn){
  if(action==='safe-mode'){
    const ok=await confirmAction('เข้า SAFE MODE ทันที?','Pi จะหยุดเพลง ปิด Aroma/Steam หยุด drive ประตู และเปิดไฟในตู้');
    if(!ok)return;
  }
  const result=await withBusy(btn,()=>post(`/api/safety/${action}`));
  if(result){
    const actionLabels={arm:'เปิดการป้องกันอัตโนมัติแล้ว',disarm:'ปิดการป้องกันอัตโนมัติแล้ว','safe-mode':'เข้าโหมดปลอดภัยแล้ว',ack:'ปลดเหตุฉุกเฉินแล้ว'};
    toast(actionLabels[action]||'อัปเดตระบบความปลอดภัยแล้ว','ok',2600);
    if(result.safety){current.safety=result.safety;renderSafety(result.safety);}
  }
}
function safetyAutoToggle(btn){
  return safetyAction(btn?.dataset.action==='disarm'?'disarm':'arm',btn);
}

function sessionStartGateText(session={},system={}){
  const gate=session.vital_gate||{};
  const bedNeed=Math.round(system.bed_start_s??20);
  const bedNow=Math.min(bedNeed,Math.floor(session.bed_wait_s||0));
  const items=[];
  if(bedNow<bedNeed)items.push(`อยู่บนเตียง ${bedNow}/${bedNeed} วินาที`);
  if(gate.reason==='waiting_for_bcg')items.push('รอสัญญาณ BCG');
  else{
    if(!gate.heart_rate_valid)items.push('รอ HR');
    if(!gate.respiration_rate_valid)items.push('รอ RR');
    if(gate.heart_rate_valid&&gate.respiration_rate_valid&&!gate.ready){
      items.push(`ยืนยัน HR/RR ${gate.confirmed_packets||0}/${gate.required_packets||3} รอบ`);
    }
  }
  return items.length?items.join(' · '):'กำลังเริ่มบันทึก';
}

function renderAdminOccupantActions(session={}){
  const title=document.getElementById('adminOccupantTitle');
  const meta=document.getElementById('adminOccupantMeta');
  const endButton=document.getElementById('adminEndSessionBtn');
  const kickButton=document.getElementById('adminKickOccupantBtn');
  if(!title||!meta||!endButton||!kickButton)return;
  const active=!!session.active;
  const account=identityLabel(session);
  title.textContent=active?account:'การใช้งาน ZEEP ปัจจุบัน';
  meta.textContent=active
    ? `${session.recording?'กำลังบันทึก':sessionStartGateText(session,current.system||{})} · ${Number(session.samples||0).toLocaleString('th-TH')} รอบ · ${session.session_id||'ไม่พบ Session ID'}`
    : 'ยังไม่มีผู้ใช้งานในตู้';
  endButton.disabled=!active;
  kickButton.disabled=!active;
}

async function adminOccupantAction(action,btn){
  if(currentPrincipal?.role!=='admin'){
    toast('คำสั่งนี้สำหรับ Admin เท่านั้น','error');
    return;
  }
  if(!sessionState.active){
    toast('ยังไม่มีผู้ใช้งานหรือ Session ที่ต้องจบ','warning');
    renderAdminOccupantActions(sessionState);
    return;
  }
  const kick=action==='kick';
  const shownName=identityLabel(sessionState,'ผู้ใช้งานปัจจุบัน');
  const confirmed=await confirmAction({
    title:kick?'จบการใช้งานและออกจากระบบ':'จบและบันทึก Session',
    message:kick
      ? `ระบบจะบันทึก W · ตื่นเป็นจุดจบของลำดับ จากนั้นจบ Session ของ “${shownName}” และยกเลิก Login ฝั่งผู้ใช้ทั้งหมด ต้องการดำเนินการหรือไม่?`
      : `ระบบจะบันทึก W · ตื่นเป็นจุดจบของลำดับ จากนั้นจบ Session ของ “${shownName}” และนำหน้าจอผู้ใช้กลับไปหน้า Login ต้องการดำเนินการหรือไม่?`,
    confirmText:kick?'จบและออกจากระบบ':'จบ Session',
    tone:kick?'danger':'warning',
    icon:kick?'↪':'■',
  });
  if(!confirmed)return;
  const result=await withBusy(btn,()=>post(
    `/api/admin/session/${kick?'kick':'end'}`,
    {reason:kick?'admin_kick_occupant':'admin_end_session'},
  ));
  if(!result){
    renderAdminOccupantActions(sessionState);
    return;
  }
  authPod={...authPod,occupied:false,owns_active_session:false,session_id:null,occupant_username:null};
  sessionState={...sessionState,active:false,recording:false,username:null,display_name:null,session_id:null,samples:0};
  renderAdminOccupantActions(sessionState);
  toast(
    kick
      ? `จบ Session ของ ${identityLabel(result)} และออกจากระบบแล้ว`
      : `จบและบันทึก Session ของ ${identityLabel(result)} แล้ว`,
    'ok',3600,
  );
}
applyPageView();
let current = {};
let currentPrincipal = null;
let authPod = {occupied:false,owns_active_session:false};
let authenticatedAppStarted = false;
let activeWS = null;
let restFallbackTimer = null;
let wsReconnectTimer = null;
let lastServerUpdateAt = 0;
let serverReachable = false;
let wsWasDown = false;
let sessionState = {active:false, username:null, gender:null, age:null, session_id:null};
let selectedGender = null;
let loginBaselines = {};
let genderAdjustments = {};
const bcgWave = {samples:[], lastPacketCount:null, maxSamples:300};
const BCG_STATUS_TH = {
  0:'อยู่บนเตียง · On bed', 1:'ลุกออกจากเตียง · Off bed', 2:'กำลังขยับ · Moving',
  3:'สัญญาณหายใจอ่อน · Weak breathing signal', 4:'พบวัตถุน้ำหนัก · Heavy object',
  5:'รูปแบบคล้ายเสียงกรน · Snoring flag'
};
// Control uses concise bedside language; Dashboard and Admin retain the
// complete bilingual BCG status above for analysis and troubleshooting.
const BCG_STATUS_CONTROL_TH = {
  0:'มีผู้ใช้งาน', 1:'เตียงว่าง', 2:'กำลังขยับ',
  3:'สัญญาณอ่อน', 4:'พบวัตถุ', 5:'มีเสียงกรน'
};
const USER_BED_STATUS_TH = {
  0:'ตรวจพบผู้ใช้งานบนเตียง', 1:'ไม่พบผู้ใช้งานบนเตียง',
  2:'พบการขยับบนเตียง', 3:'กำลังอ่านข้อมูลจากเตียง',
  4:'ตรวจพบแรงกดบนเตียง', 5:'ตรวจพบผู้ใช้งานบนเตียง'
};

function genderTh(g){ return ({male:'ชาย', female:'หญิง', other:'อื่น ๆ', unspecified:'ไม่ระบุ'})[g] || g || '-'; }
function ageToGroup(age){ return age>=60?'60+':age>=45?'45-59':age>=30?'30-44':'18-29'; }
function displayAge(se={}){
  const ref=se.health_reference||{},exact=Number(ref.age_years);
  if(Number.isFinite(exact)&&exact>0)return `อายุ ${Math.round(exact)} ปี`;
  const group=ref.age_group||se.age_group;
  return group?`ช่วงอายุ ${group} ปี`:'ยังไม่มีข้อมูลอายุ';
}
function healthReferenceValue(value,unit=''){
  if(value===null||value===undefined||value===''||!Number.isFinite(Number(value)))return '—';
  return `${Number(value).toLocaleString('th-TH-u-nu-latn',{maximumFractionDigits:1})}${unit}`;
}
function setHealthReferenceFact(id,value){
  const card=document.getElementById(id);if(!card)return;
  card.querySelector('strong').textContent=value||'—';card.classList.toggle('missing',!value||value==='—');
}
function renderHealthReference(session={}){
  const root=document.getElementById('dashProfileReference');if(!root)return;
  const ref=session.health_reference||{},active=!!session.active;
  const adminView=currentPrincipal?.role==='admin';
  root.classList.toggle('idle',!active);
  setHealthReferenceFact('dashProfileGender',active?genderTh(ref.gender||session.gender):'—');
  setHealthReferenceFact('dashProfileAge',active?displayAge(session):'—');
  setHealthReferenceFact('dashProfileHeight',active?healthReferenceValue(ref.height_cm,' ซม.'):'—');
  setHealthReferenceFact('dashProfileWeight',active?healthReferenceValue(ref.weight_kg,' กก.'):'—');
  setHealthReferenceFact('dashProfileBlood',active?(ref.blood_group||'—'):'—');
  const source=document.getElementById('dashProfileSource');
  if(!active){
    source.textContent=adminView
      ?'แสดงเฉพาะข้อมูลจริงจาก Profile · ไม่ใช่การวินิจฉัย'
      :'ข้อมูลจากบัญชีช่วยให้คำแนะนำเหมาะกับคุณมากขึ้น';
    return;
  }
  const updated=ref.updated_at_utc?fmtDateTh(ref.updated_at_utc):'';
  const refresh=ref.refresh_status==='live_login'
    ? `อัปเดตจากบัญชี ZEEP เมื่อ Login${updated?` · ${updated}`:''}`
    : ref.refresh_status==='cached'
      ? `ใช้ข้อมูลบัญชีล่าสุดในเครื่อง · จะอัปเดตอีกครั้งเมื่อเชื่อมต่อบัญชี ZEEP${updated?` · อัปเดตล่าสุด ${updated}`:''}`
      : `ข้อมูล Profile ในเครื่อง${updated?` · ${updated}`:''}`;
  source.textContent=adminView
    ?`${refresh} · ช่องว่างหมายถึงบัญชียังไม่มีข้อมูล · ไม่ใช่การวินิจฉัย`
    :'ใช้ข้อมูลจากบัญชี ZEEP เพื่อปรับคำแนะนำให้เหมาะกับคุณ · เติมข้อมูลที่ยังว่างได้ในแอป';
}
function healthReferenceInline(rec={}){
  const ref=rec.health_reference||{};
  return `${genderTh(ref.gender||rec.gender)} · ${displayAge({...rec,health_reference:ref})} · ส่วนสูง ${healthReferenceValue(ref.height_cm,' ซม.')} · น้ำหนัก ${healthReferenceValue(ref.weight_kg,' กก.')} · กรุ๊ปเลือด ${ref.blood_group||'—'}`;
}
function renderSystemHealth(sys={}){
  const h=sys.health||{},wifi=document.getElementById('wifiPill'),ip=document.getElementById('ipPill');
  const dbm=Number(h.wifi_dbm),connected=!!h.wifi_connected&&Number.isFinite(dbm);
  const quality=!connected?'bad':dbm>=-60?'good':dbm>=-74?'warn':'bad';
  const level=!connected?0:dbm>=-55?4:dbm>=-65?3:dbm>=-75?2:1;
  const qualityTh=quality==='good'?'แรง':quality==='warn'?'ปานกลาง':connected?'อ่อน':'ไม่เชื่อมต่อ';
  wifi.className=`pill health ${quality}`;
  wifi.innerHTML=`<span class="wifi-signal level-${level}" aria-label="สัญญาณ ${qualityTh}"><i></i><i></i><i></i><i></i></span><span>${connected?`${h.wifi_ssid||'Wi‑Fi'} · ${qualityTh} · ${dbm} dBm`:'Wi‑Fi ไม่เชื่อมต่อ'}</span>`;
  ip.textContent=`⇄ ${h.ip_address||'IP N/A'} · uptime ${fmtUptime(h.host_uptime_s)}`;
}
async function loadAgeBaselines(){
  try {
    const r=await fetch('/api/sleep/baselines'); const d=await r.json();
    loginBaselines=d.age_groups||{}; genderAdjustments=d.gender_adjustments||{}; renderLoginBaseline();
  } catch {}
}
function renderLoginBaseline(){
  const group=document.getElementById('loginAgeGroup').value;
  const root=document.getElementById('loginBaselinePreview');
  const base=loginBaselines[group];
  if(!base){
    root.innerHTML='<div class="mini">เลือกช่วงอายุเพื่อให้ ZEEP เตรียมค่าเริ่มต้นที่เหมาะกับคุณ</div>';
    return;
  }
  root.innerHTML='<div class="mini"><b>พร้อมสำหรับการพักครั้งนี้</b><br>ZEEP จะใช้ข้อมูลโปรไฟล์เป็นจุดเริ่มต้น และเรียนรู้รูปแบบของคุณจากการพักแต่ละครั้ง</div>';
}

/* Canonical five-state presentation. Keep title/meaning in sync with
   sleep_system_policy.py; label stays compact for the live Dashboard tile. */
const SLEEP_TH = {
  wake:       {code:'W',   title:'ตื่น',meaning:'ช่วงที่ระบบประเมินว่ายังตื่นหรือกลับเข้าสู่สถานะตื่น',label:'ตื่น',cls:'wake'},
  n1:         {code:'N1',  title:'หลับตื้น / เคลิ้มหลับ',meaning:'เริ่มเข้าสู่การนอน ร่างกายผ่อนคลาย และปลุกให้ตื่นได้ง่าย',label:'หลับตื้น',cls:'nrem'},
  n2:         {code:'N2',  title:'หลับสนิทขึ้น / หลับตื้นต่อเนื่อง',meaning:'หัวใจและการหายใจช้าลง ร่างกายเข้าสู่การนอนที่ต่อเนื่องขึ้น',label:'หลับสนิทขึ้น',cls:'nrem'},
  n3:         {code:'N3',  title:'หลับลึก',meaning:'ช่วงหลับลึกที่ร่างกายได้พักอย่างต่อเนื่อง',label:'หลับลึก',cls:'deep'},
  rem:        {code:'REM', title:'ระยะ REM / หลับฝัน',meaning:'ช่วงหลับที่สมองยังทำงานมากขึ้นและมักมีความฝัน',label:'หลับฝัน',cls:'rem'},
  // ``nrem`` is kept only for rendering old history. The live estimator never
  // emits a generic NREM because ZEEP's current ontology is W/N1/N2/N3/REM.
  nrem:       {code:'NREM', label:'หลับ · ข้อมูลเดิม',cls:'nrem'},
  off_bed:    {code:'OFF',  label:'ไม่มีผู้ใช้งานบนเตียง',cls:'off'},
  wait_initial:{code:'WAIT', title:'WAIT · กำลังยืนยันสถานะ',label:'กำลังยืนยันสถานะ',cls:'na'},
  no_data:    {code:'NO DATA', label:'หลักฐานไม่ครบ', cls:'na'},
};
const USER_SLEEP_STAGE_LABELS=Object.freeze({
  wake:'ตื่น',n1:'หลับตื้น',n2:'หลับสนิทขึ้น',n3:'หลับลึก',rem:'หลับฝัน',
  nrem:'ช่วงหลับ',off_bed:'ออกจากเตียง',
});
function userSleepStageLabel(state){
  return USER_SLEEP_STAGE_LABELS[String(state||'').toLowerCase()]||'ช่วงการพัก';
}
function renderSleepState(sl={},session={},bcg={}){
  const box = document.getElementById('sleepState');
  const classificationActive=sl.classification_active===true;
  const restartHold=sl.display_only_after_restart===true&&sl.held_previous_state===true;
  const sessionActive=!!session.active,recording=!!session.recording;
  const offBed=sl.data_status==='empty_bed'||sl.data_status==='no_session'
    ||(!sessionActive)||(Number(bcg.status_code)===1&&bcg.bed_exit_evidence?.confirmed);
  // UI defence-in-depth: even if an old/cached server frame contains N1–REM,
  // never present it as current without an active classification contract.
  const initialWait=['confirming_initial_state','collecting_evidence_epoch']
    .includes(sl.data_status);
  const stateKey=offBed?'off_bed':classificationActive
    ? sl.state
    : recording&&initialWait?'wait_initial':'no_data';
  const meta = SLEEP_TH[stateKey] || SLEEP_TH.no_data;
  box.className = `sleep-state ${meta.cls}`;
  document.getElementById('sleepStateText').textContent = `${meta.code} · ${meta.label}`;
  const confidenceTh = {low:'ต่ำ',medium:'ปานกลาง',high:'สูง'};
  const clock=sl.sensor_frame_clock||{},confirmation=sl.confirmation||{},evidence=sl.evidence||{};
  const evidenceCandidate=evidence.candidate||sl.probability_winner||sl.raw_candidate;
  const progress = `Sensor ${clock.frame_in_epoch||0}/${clock.sensor_frames_per_epoch||3} · Evidence ${sl.evidence_epoch_s||30} วิ`;
  const next = ` · สรุปรอบถัดไปใน ${sl.next_evidence_s ?? sl.evidence_epoch_s ?? 30} วิ`;
  const source = sl.classification_source === 'personal' ? 'Personal Baseline' : 'Age + Gender Baseline';
  const provisional = classificationActive&&sl.provisional
    ? ` · provisional · คง State ก่อนหน้า · ${sl.score_eligible?'นับตาม State เดิม':'ยังไม่นับคะแนน'}`
    : '';
  const confirmProgress=`${confirmation.candidate_epochs||0}/${confirmation.required_epochs||2} epoch`;
  const confirmationSeconds=(confirmation.required_epochs||2)*30;
  const classificationNote=classificationActive
    ? restartHold
      ? `สถานะยืนยันก่อน Restart · รอหลักฐานสดรอบใหม่ · ไม่บันทึกซ้ำ`
      : `${source}${provisional} · แสดง ${meta.code} · หลักฐานล่าสุด ${(evidenceCandidate||'--').toUpperCase()} · มั่นใจ ${confidenceTh[sl.confidence] || 'ต่ำ'}`
    : sl.evidence_active
      ? `หลักฐาน ${(evidenceCandidate||'--').toUpperCase()} · กำลังยืนยัน ${confirmProgress}`
      : 'ยังไม่จัดประเภทการนอน';
  document.getElementById('sleepStateMeta').textContent = `${sl.reason || 'กำลังรอข้อมูล'} · ${progress}${next} · ${classificationNote} · ${sl.version || 'v1'}`;
  const probs = sl.evidence_probabilities || sl.probabilities || {}, order=['wake','n1','n2','n3','rem'];
  document.getElementById('sleepProbabilities').innerHTML = order.map(k=>{
    const pct = Math.round((probs[k]||0)*100);
    return `<div class="sleep-prob"><div class="prob-head"><span>${k==='wake'?'W · ตื่น':k.toUpperCase()}</span><span>${pct}%</span></div><div class="prob-bar"><div class="prob-fill" style="width:${pct}%"></div></div></div>`;
  }).join('');
  const base=sl.baseline||{}, names={wake:'W · ตื่น',n1:'N1',n2:'N2',n3:'N3',rem:'REM'};
  const baselineRows=order.filter(k=>base[k]).map(k=>`<tr class="${classificationActive&&sl.state===k?'current':''}"><td>${names[k]}</td><td>${base[k].hr[0]}–${base[k].hr[1]} BPM</td><td>${base[k].rr[0]}–${base[k].rr[1]} ครั้ง/นาที</td></tr>`).join('');
  const genderAdj=sl.gender_adjustment||{};
  const baselineTable=baselineRows?`<div class="baseline-block"><div class="baseline-title"><strong>Wellness Baseline · อายุ ${sl.age_group || '18-29'} ปี · ${genderTh(sl.gender)}</strong><span>Age + Gender directional starting range</span></div><table class="baseline-table"><thead><tr><th>Sleep State</th><th>HR · Heart Rate</th><th>RR · Respiratory Rate</th></tr></thead><tbody>${baselineRows}</tbody></table></div>`:'';
  const env=sl.environment||{}, q=sl.signal_quality||{};
  const envParts=[
    env.temperature_c!=null?`🌡 ${env.temperature_c}°C`:null,
    env.humidity_rh!=null?`💧 ${env.humidity_rh}%RH`:null,
    env.co2_ppm!=null?`☁ CO₂ ${env.co2_ppm} ppm`:null,
    env.lux!=null?`☀ ${env.lux} lux`:null,
    env.sound_dba!=null?`🔊 ${env.sound_dba} dBA`:null,
    env.pm2_5_ug_m3!=null?`🌫 PM2.5 ${env.pm2_5_ug_m3} µg/m³`:null,
  ].filter(Boolean);
  const quality=q.total_buckets?`คุณภาพข้อมูล BCG ${q.valid_buckets}/${q.total_buckets} ช่วง (${q.valid_percent}%) · clipping เฉลี่ย ${q.average_clip_percent ?? 0}%`:'';
  const progression=(sl.stage_progression||[]).map(x=>x.toUpperCase());
  const previous=sl.previous_state?sl.previous_state.toUpperCase():'ยังไม่มี';
  const supportLines = [
    `Confirmed State ล่าสุด ${previous} · Evidence ${(evidenceCandidate||'--').toUpperCase()} ${confirmProgress} · ต้องต่อเนื่อง ${confirmationSeconds} วินาทีก่อนเปลี่ยน State`,
    `Evidence: ${sl.evidence_version || 'zeep-wellness-evidence'} · ใช้แนวโน้มและ variability ร่วมกัน ไม่ใช้ค่า HR/RR จุดเดียว`,
    `Gender Baseline · HR offset ${genderAdj.hr_offset>=0?'+':''}${genderAdj.hr_offset ?? 0} BPM · RR offset ${genderAdj.rr_offset>=0?'+':''}${genderAdj.rr_offset ?? 0} · REM variability ×${genderAdj.rem_variability_weight ?? 1} · ${genderAdj.note || 'neutral'}`,
    progression.length?`Timeline ล่าสุด: ${progression.join(' → ')}`:'',
    sl.transition_guard || '',
    envParts.length ? `Environment: ${envParts.join(' · ')} · coverage ${env.coverage_percent ?? 0}%` : '',
    (env.comfort_flags||[]).length ? `ข้อสังเกต: ${env.comfort_flags.join(' · ')}` : 'สภาพแวดล้อม: ไม่มีเงื่อนไขเด่นจากเซ็นเซอร์ที่พร้อมใช้งาน',
    (env.unavailable_sensors||[]).length ? `เซ็นเซอร์ที่ยังไม่มีข้อมูล: ${env.unavailable_sensors.join(', ')}` : '',
    quality,
  ].filter(Boolean).map(x=>`<div>${x}</div>`).join('');
  document.getElementById('sleepBaseline').innerHTML = `${baselineTable}<div class="baseline-support">${supportLines}</div>`;
}
