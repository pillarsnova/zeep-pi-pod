function fmtDateTh(iso){
  if (!iso) return '--';
  try { return new Date(iso).toLocaleString('th-TH', {day:'numeric', month:'short', hour:'2-digit', minute:'2-digit'}); }
  catch { return iso; }
}
function fmtDur(s){
  if (s == null) return '--';
  const m = Math.floor(s/60);
  if (m >= 60) return `${Math.floor(m/60)} ชม. ${m%60} นาที`;
  return m > 0 ? `${m} นาที ${Math.round(s%60)} วิ` : `${Math.round(s)} วินาที`;
}

// Build a prefix-sum index once, then calculate each Sleep State window in
// O(log n). Overnight reports contain thousands of Sensor rows, so scanning
// the whole Timeline again for every state would make the tablet feel slow.
function timelineMetricAverager(samples, key){
  const points=(samples||[]).flatMap(sample=>{
    const time=Number(sample?.t),raw=sample?.[key];
    if(!Number.isFinite(time)||raw===null||raw===undefined||raw==='') return [];
    const value=Number(raw);
    return Number.isFinite(value)?[{time,value}]:[];
  }).sort((a,b)=>a.time-b.time);
  const times=points.map(point=>point.time),prefix=[0];
  points.forEach(point=>prefix.push(prefix[prefix.length-1]+point.value));
  const lowerBound=value=>{let low=0,high=times.length;while(low<high){const mid=(low+high)>>1;if(times[mid]<value)low=mid+1;else high=mid;}return low;};
  const upperBound=value=>{let low=0,high=times.length;while(low<high){const mid=(low+high)>>1;if(times[mid]<=value)low=mid+1;else high=mid;}return low;};
  return (startTime,endTime)=>{
    const start=Date.parse(startTime)/1000,end=Date.parse(endTime)/1000;
    if(!Number.isFinite(start)||!Number.isFinite(end)||end<start) return null;
    const first=lowerBound(start),afterLast=upperBound(end),count=afterLast-first;
    return count ? (prefix[afterLast]-prefix[first])/count : null;
  };
}

// Sleep Timeline uses one compact visual language for every sensor.  Keep the
// units in the value and the source name in the badge so a tablet user can scan
// a state interval without parsing a long evidence sentence.
function sleepSensorTile(kind, badge, label, value){
  return `<span class="sleep-env ${kind}"><i>${badge}</i><span><small>${label}</small><b>${value}</b></span></span>`;
}

function sleepBedStatusLabel(value){
  return ({
    'On bed':'อยู่บนเตียง','Get out of bed':'ออกจากเตียง','Moving':'กำลังขยับ',
    'Weak breathing':'สัญญาณอ่อน','Heavy object on bed':'พบวัตถุ','Snoring':'คล้ายกรน',
  })[String(value||'').trim()] || value || '--';
}

function sleepReasonExplanation(reason){
  // Numeric evidence is already shown in tiles.  Retain only estimator logic,
  // gates and context to avoid repeating HR/RR/environment values below them.
  const duplicate=/^(HR เฉลี่ย|RR เฉลี่ย|movement\b|แสงเฉลี่ย|เสียงเฉลี่ย)/i;
  return String(reason||'').split(' · ').filter(part=>part&&!duplicate.test(part)).join(' · ') || 'ไม่มีเหตุผลเพิ่มเติม';
}

function reportSafetyReviewRequired(source={}){
  const payload=source?.data||source||{};
  const report=payload.session_report||payload.report||payload;
  const quality=payload.sleep_quality||report.quality||payload.quality||payload;
  const summary=payload.restore_summary||report.restore_summary||{};
  const attention=summary.drivers?.attention||summary.attention_drivers||[];
  return quality.safety_review_required===true
    ||quality.environment_support?.safety_review_required===true
    ||report.environment_assessment?.safety_review_required===true
    ||(report.findings||[]).some(item=>item?.decision==='safety_review')
    ||attention.some(item=>item?.priority==='safety_review');
}

function sleepQualityTone(q,safetyReviewOverride=false){
  if(safetyReviewOverride||reportSafetyReviewRequired(q))return 'safety_review';
  return ['very_good','good','fair','low'].includes(q?.level_key) ? q.level_key : 'unavailable';
}

function resultScoreTitle(q,presentation,adminView=false){
  if(presentation==='recovery')return 'Recovery Score';
  if(presentation==='sleep')return 'Sleep Score';
  return adminView?(q?.score_title||'คะแนน Session'):'ผลการพักครั้งนี้';
}

function userUnavailableScoreReason(q,presentation){
  const validation=String(
    q?.validation_status||q?.target_status||q?.rest_mode?.protocol_status?.status||'',
  ).toLowerCase();
  const reason=String(q?.reason||'').toLowerCase();
  if(presentation==='unknown'){
    return 'ยังยืนยันรูปแบบการพักครั้งนี้ไม่ได้ จึงไม่สรุปเป็นคะแนน';
  }
  if(validation.includes('short')||reason.includes('short')||reason.includes('10 นาที')){
    return 'ระยะเวลาครั้งนี้สั้นเกินกว่าจะสรุปเป็นคะแนนได้อย่างเหมาะสม';
  }
  if(validation.includes('unresolved')||reason.includes('mode')){
    return 'ยังยืนยันรูปแบบการพักครั้งนี้ไม่ได้ จึงไม่สรุปเป็นคะแนน';
  }
  return 'ผลเดิมของครั้งนี้ต้องตรวจความสอดคล้องก่อนแสดงคะแนน';
}

function sleepQualityCompact(q, ended, presentationOverride,safetyReviewOverride=false){
  if (!ended) return `<span class="hist-quality quality-unavailable"><strong>LIVE</strong><span><b>กำลังบันทึก</b><small>${currentPrincipal?.role==='admin'?'คุณภาพหลังจบ Session':'ผลจะแสดงเมื่อจบการพัก'}</small></span></span>`;
  const presentation=presentationOverride||reportPresentationMode(q);
  const adminView=currentPrincipal?.role==='admin';
  const title=resultScoreTitle(q,presentation,adminView);
  if (!q?.available||presentation==='unknown') return `<span class="hist-quality quality-unavailable"><strong>—</strong><span><b>${adminView?'ไม่มีคะแนน':'ยังไม่มีคะแนน'}</b><small>${title}</small></span></span>`;
  const safetyReview=safetyReviewOverride||reportSafetyReviewRequired(q);
  const level=safetyReview
    ?USER_PRODUCT_COPY.scoreLevels.safety_review:userScoreLevelLabel(q);
  return `<span class="hist-quality quality-${sleepQualityTone(q,safetyReview)}"><strong>${q.score}</strong><span><b>${historyEscape(level)}</b><small>${title}</small></span></span>`;
}

let historyRequestSeq=0;
let historyJourneyRequestSeq=0;
let historyDetailRequestSeq=0;
const HISTORY_JOURNEY_CACHE_MS=60000;
const historyJourneyCache=new Map();

async function refreshHistory(btn){
  ensureHistoryFilterDefaults();
  const user=currentPrincipal
    ? (currentPrincipal.account_key||currentPrincipal.email||currentPrincipal.username||'')
    : '';
  const list = document.getElementById('sessionList');
  if(currentPrincipal?.role==='user'&&!user){
    list.innerHTML='<div class="mini">กรุณาเข้าสู่ระบบอีกครั้งเพื่อดูประวัติของคุณ</div>';return;
  }
  const run = async ()=>{
    const requestSeq=++historyRequestSeq;
    const adminView=currentPrincipal?.role==='admin';
    list.innerHTML=`<div class="flat-message loading"><span class="flat-icon"></span><div><b>กำลังโหลดประวัติการใช้งาน</b><span>${adminView?'กำลังอ่าน Session จากเครื่อง Pi':'กำลังเตรียมรายการย้อนหลังของคุณ'}</span></div></div>`;
    document.getElementById('historySummary').innerHTML='<div class="mini">กำลังสรุปช่วงเวลาที่เลือก…</div>';
    historyDetailRequestSeq+=1;
    document.getElementById('sessionDetail').innerHTML='<div class="history-empty"><b>เลือกรายการการพัก</b><span>ผลสรุปจะแสดงในส่วนนี้</span></div>';
    refreshUserJourney();
    const params=historyFilterParams();
    const path=currentPrincipal?.role==='admin'
      ? `/api/admin/history?${params}`
      : `/api/history/${encodeURIComponent(user)}?${params}`;
    let r;
    try { r=await fetch(path,{cache:'no-store'}); }
    catch {
      if(requestSeq===historyRequestSeq){
        toast(adminView?'เชื่อมต่อ server ไม่ได้':'ยังเชื่อมต่อระบบไม่ได้ กรุณาลองอีกครั้ง', 'error');
      }
      return;
    }
    if(requestSeq!==historyRequestSeq)return;
    if (!r.ok){
      let detail='';try{detail=(await r.json()).detail||'';}catch{}
      toast(adminView?(detail||`โหลดประวัติไม่ได้ · HTTP ${r.status}`):'ยังโหลดประวัติไม่ได้ กรุณาลองอีกครั้ง','error');return;
    }
    const data=await r.json();
    if(requestSeq!==historyRequestSeq)return;
    renderSessionList(data);
  };
  return btn ? withBusy(btn, run) : run();
}

function historyLocalToday(){
  const parts=new Intl.DateTimeFormat('en-CA',{
    timeZone:'Asia/Bangkok',year:'numeric',month:'2-digit',day:'2-digit',
  }).formatToParts(new Date());
  const part=type=>parts.find(item=>item.type===type)?.value;
  return `${part('year')}-${part('month')}-${part('day')}`;
}

function ensureHistoryFilterDefaults(){
  const from=document.getElementById('historyDateFrom');
  const to=document.getElementById('historyDateTo');
  if(!from||!to)return;
  if(!from.value)from.value=historyLocalToday();
  if(!to.value)to.value=from.value;
}

function historyShiftDate(value,days){
  const date=new Date(`${value}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate()+days);
  return date.toISOString().slice(0,10);
}

function shiftHistoryRange(days){
  ensureHistoryFilterDefaults();
  const from=document.getElementById('historyDateFrom');
  const to=document.getElementById('historyDateTo');
  from.value=historyShiftDate(from.value,days);
  to.value=historyShiftDate(to.value,days);
  refreshHistory();
}

function setHistoryToday(){
  const today=historyLocalToday();
  document.getElementById('historyDateFrom').value=today;
  document.getElementById('historyDateTo').value=today;
  document.getElementById('historyTimeFrom').value='00:00';
  document.getElementById('historyTimeTo').value='23:59';
  refreshHistory();
}

function historyFilterParams(){
  const params=new URLSearchParams({
    date_from:document.getElementById('historyDateFrom').value,
    date_to:document.getElementById('historyDateTo').value,
    time_from:document.getElementById('historyTimeFrom').value||'00:00',
    time_to:document.getElementById('historyTimeTo').value||'23:59',
    limit:'500',
  });
  if(currentPrincipal?.role==='admin'){
    const account=document.getElementById('historyUser')?.value||'';
    const query=document.getElementById('historyNameFilter')?.value.trim()||'';
    if(account)params.set('account_key',account);
    if(query)params.set('query',query);
  }
  return params.toString();
}

function historyEscape(value){
  return String(value??'').replace(/[&<>"']/g,character=>({
    '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;',
  })[character]);
}

function restoreSummarySource(source){
  const payload=source?.data||source||{};
  const report=payload.session_report||payload;
  const summary=payload.restore_summary||report.restore_summary;
  if(!summary||typeof summary!=='object')return null;
  return summary;
}

function restorePlainText(value,keys=[]){
  if(value===null||value===undefined)return '';
  if(['string','number'].includes(typeof value))return String(value).trim();
  if(typeof value!=='object')return '';
  for(const key of [...keys,'label','title','summary','text','meaning','observation']){
    const candidate=value[key];
    if(['string','number'].includes(typeof candidate)&&String(candidate).trim()){
      return String(candidate).trim();
    }
  }
  return '';
}

function restoreDriverText(value){
  // Driver copy describes an observation in the same Session. It must never
  // turn a time-aligned Sensor association into a medical causal claim.
  const copy=restorePlainText(value,['message','observation','name'])
    .replace(/(?:เป็น)?สาเหตุ(?:ของ|ที่ทำให้)?/g,'พบสัมพันธ์ใกล้เวลากับ')
    .replace(/ส่งผลให้|ทำให้/g,'พบร่วมกับ');
  return historyEscape(copy.length>140?`${copy.slice(0,137)}…`:copy);
}

const USER_RESTORE_DRIVER_COPY=Object.freeze({
  sleep_opportunity:'เวลาและช่วงเตรียมตัวก่อนนอนมีส่วนต่อผลครั้งนี้',
  sleep_stability:'ความต่อเนื่องของการนอนมีส่วนต่อผลครั้งนี้',
  restorative_architecture:'รูปแบบการนอนที่ประเมินได้มีส่วนต่อผลครั้งนี้',
  cycle_expression:'ความต่อเนื่องของช่วงการนอนมีส่วนต่อผลครั้งนี้',
  goal_duration:'เวลาพักตามที่เลือกมีส่วนต่อผลครั้งนี้',
  physiological_response:'ความนิ่งของชีพจรและการหายใจมีส่วนต่อผลครั้งนี้',
  rest_continuity:'ความต่อเนื่องและการขยับระหว่างพักมีส่วนต่อผลครั้งนี้',
  environment_support:'สภาพแวดล้อมภายใน ZEEP มีส่วนต่อผลครั้งนี้',
});
function userRestoreDriverText(value,tone){
  const key=String(value?.key||'').toLowerCase();
  if(key.startsWith('environment_')){
    const metric=USER_PRODUCT_COPY.environmentMetrics[key.slice(12)]||'สภาพแวดล้อม';
    return tone==='positive'?`${metric}เหมาะกับการพักครั้งนี้`:`${metric}ยังปรับให้สบายขึ้นได้`;
  }
  return USER_RESTORE_DRIVER_COPY[key]
    ||(tone==='positive'?'มีปัจจัยที่ช่วยให้การพักครั้งนี้เป็นไปได้ดี':'มีบางจุดที่ลองปรับให้การพักครั้งถัดไปสบายขึ้นได้');
}

function userRestoreMeaning(statusKey,presentation,unavailable){
  if(unavailable)return 'ครั้งนี้ยังไม่มีคะแนน แต่ยังดูรายละเอียดการพักที่บันทึกไว้ได้';
  const meanings={
    safety_review:'พบค่าสภาพแวดล้อมบางช่วงที่ควรให้ทีมตรวจสอบก่อนใช้งานครั้งถัดไป',
    limited_evidence:'เวลาบันทึกครบขั้นต่ำ แต่ข้อมูล Sensor ครั้งนี้มีจำกัด',
    sleep_restore_very_good:'ภาพรวมการนอนคืนนี้เป็นไปได้ดีมาก',sleep_restore_good:'ภาพรวมการนอนคืนนี้เป็นไปได้ดี',
    pace_morning:'คืนนี้ได้พักในระดับหนึ่ง',prioritise_rest:'ครั้งนี้ยังมีบางจุดที่ช่วยให้การพักสบายขึ้นได้',
    rest_goal_full:'ช่วงพักนี้เป็นไปได้ดีมาก',rest_good:'ช่วงพักนี้เป็นไปได้ดี',
    rest_partial:'ภาพรวมช่วงพักนี้พอใช้',rest_more:'ครั้งนี้ยังมีบางจุดที่ลองปรับให้สบายขึ้นได้',
  };
  return meanings[statusKey]||(presentation==='recovery'?'ดูผลช่วงพักนี้ร่วมกับความรู้สึกหลังพัก':'ดูภาพรวมคืนนี้ร่วมกับความรู้สึกหลังตื่น');
}

function adminResultEvidence(report,quality,summary,presentation){
  const coverage=report.data_quality?.coverage||{};
  const confidence=report.data_quality?.confidence_pct||{};
  const componentPoints=quality.component_points||{};
  const componentMax=quality.component_max_points||{};
  const componentLabels=quality.component_labels||{};
  const componentRows=(quality.component_order||Object.keys(componentPoints)).map(key=>{
    const value=Number(componentPoints[key]);
    const maximum=Number(componentMax[key]);
    if(!Number.isFinite(value))return '';
    const points=Number.isFinite(maximum)
      ?`${value.toFixed(1)} / ${maximum.toFixed(0)}`:value.toFixed(1);
    return `<span><small>${historyEscape(componentLabels[key]||key)}</small><b>${points}</b></span>`;
  }).join('');
  const coverageValue=value=>Number.isFinite(Number(value))?`${Number(value).toFixed(0)}%`:'—';
  const baseline=summary.personal_baseline||{};
  const maturity=baseline.maturity||baseline;
  const sessions=Number(maturity.sessions_used??baseline.sessions_used);
  const baselineLabel=Number.isFinite(sessions)&&sessions>0
    ?`${Math.round(sessions)} Sessions`:'กำลังสะสมข้อมูล';
  const version=report.version||quality.formula_version||summary.version||'—';
  return `<details class="report-details result-evidence-details">
    <summary>หลักฐานและคุณภาพข้อมูลสำหรับผู้ดูแล</summary>
    <div class="result-evidence-section">
      <div class="result-evidence-grid">
        <span><small>Recording</small><b>${coverageValue(coverage.recording_pct)}</b></span>
        <span><small>BCG</small><b>${coverageValue(coverage.bcg_pct)}</b></span>
        <span><small>Sleep State</small><b>${coverageValue(coverage.sleep_stage_pct)}</b></span>
        <span><small>Environment</small><b>${coverageValue(coverage.environment_pct)}</b></span>
        <span><small>Confidence H / M / L</small><b>${Number(confidence.high)||0} / ${Number(confidence.medium)||0} / ${Number(confidence.low)||0}%</b></span>
        <span><small>Personal Baseline</small><b>${historyEscape(baselineLabel)}</b></span>
        <span><small>Mode</small><b>${presentation==='recovery'?'Nap & Refresh':presentation==='sleep'?'Overnight Recovery':'รอยืนยัน'}</b></span>
        <span><small>Version</small><b>${historyEscape(version)}</b></span>
      </div>
      ${componentRows?`<div class="result-component-grid">${componentRows}</div>`:''}
      <div class="result-development-note"><b>ใช้พัฒนาระบบต่ออย่างไร</b><p>ใช้ตรวจความครบของ Sensor, ความสอดคล้องของ State, ปัจจัยที่สัมพันธ์ใกล้เวลากับการพัก และผลของ Personal Baseline โดยไม่แก้ข้อมูล Raw</p></div>
      <div class="restore-claim-note">ปัจจัยเป็นความสัมพันธ์ใกล้เวลา ไม่ยืนยันเหตุ–ผล · ผลนี้เป็น ZEEP Wellness ไม่ใช่การวินิจฉัยและไม่ใช่ความพร้อมตลอดทั้งวัน</div>
    </div>
  </details>`;
}

function renderRestoreSummary(source,presentation,ended=true){
  const payload=source?.data||source||{};
  const report=payload.session_report||payload;
  const summary=restoreSummarySource(source)||{};
  const quality=payload.sleep_quality||report.quality||{};
  const adminView=currentPrincipal?.role==='admin';
  const safetyReviewRequired=reportSafetyReviewRequired(source);
  const scoreAvailable=Boolean(
    ended&&presentation!=='unknown'&&quality.available&&quality.score!=null,
  );
  const scoreTitle=resultScoreTitle(quality,presentation,adminView);
  const status=summary.status||{};
  const statusKey=String(status?.key||status||'').toLowerCase();
  const statusLabels={
    excellent:'ยอดเยี่ยม',very_good:'ดีมาก',good:'ดี',fair:'พอใช้',
    safety_review:'ควรให้ทีมตรวจสอบ',
    limited_evidence:'สรุปการพักครั้งนี้แล้ว',
    low:'ให้เวลากับการพักเพิ่ม',sleep_restore_very_good:'ดีมาก',
    sleep_restore_good:'ดี',pace_morning:'ได้พักในระดับหนึ่ง',
    prioritise_rest:'ให้เวลากับการพักเพิ่ม',rest_goal_full:'พักได้ดีมาก',
    rest_good:'ช่วงพักเป็นไปได้ดี',rest_partial:'ได้พักในระดับหนึ่ง',
    rest_more:'ลองปรับให้สบายขึ้น',
  };
  const statusLabel=scoreAvailable&&safetyReviewRequired
    ?USER_PRODUCT_COPY.scoreLevels.safety_review
    :scoreAvailable
    ?(
      (adminView
        ?restorePlainText(status?.label||status?.title):statusLabels[statusKey])
      ||statusLabels[statusKey]
      ||(adminView?(quality.level||userScoreLevelLabel(quality)):userScoreLevelLabel(quality))
    )
    :!ended?'กำลังบันทึกการพัก':'ครั้งนี้ยังไม่มีคะแนน';
  const statusMeaning=scoreAvailable&&safetyReviewRequired
    ?'พบค่าสภาพแวดล้อมบางช่วงที่ควรให้ทีมตรวจสอบก่อนใช้งานครั้งถัดไป'
    :scoreAvailable
    ?(adminView
      ?restorePlainText(status?.meaning||status?.description)
      :userRestoreMeaning(statusKey,presentation,false))
    :!ended
      ?'ZEEP กำลังบันทึกข้อมูลระหว่างการพัก'
      :userUnavailableScoreReason(quality,presentation);
  const drivers=summary.drivers||{};
  const positives=Array.isArray(drivers.positive)
    ?drivers.positive:Array.isArray(summary.positive_drivers)?summary.positive_drivers:[];
  const attentions=Array.isArray(drivers.attention)
    ?drivers.attention:Array.isArray(summary.attention_drivers)?summary.attention_drivers:[];
  const driverGroup=(title,items,tone)=>{
    const rows=items.map(item=>adminView?restoreDriverText(item):historyEscape(userRestoreDriverText(item,tone))).filter(Boolean).slice(0,2);
    if(!rows.length)return '';
    return `<div class="restore-driver-group ${tone}"><b>${title}</b><ul>${rows.map(row=>`<li>${row}</li>`).join('')}</ul></div>`;
  };
  const driverMarkup=presentation==='unknown'
    ?'<div class="restore-summary-empty">แสดงเฉพาะข้อมูลที่บันทึก โดยยังไม่ตีความเป็น Overnight หรือ Nap & Refresh</div>'
    :summary.available===false||!Object.keys(summary).length
    ?`<div class="restore-summary-empty">${!ended?'รายละเอียดจะพร้อมหลังจบการพัก':'ยังดูข้อมูลการพักและ Sensor ที่บันทึกไว้ได้ตามปกติ'}</div>`
    :[
      driverGroup('สิ่งที่ทำได้ดี',positives,'positive'),
      driverGroup('สิ่งที่ลองปรับได้',attentions,'attention'),
    ].join('')||'<div class="restore-summary-empty">ยังไม่มีปัจจัยที่ต้องดูแลเป็นพิเศษ</div>';
  const canonicalRecommendation=restorePlainText(summary.recommendation,['primary'])
    ||restorePlainText(report.post_session_guidance,['primary']);
  const recommendation=presentation==='unknown'
    ?'ตรวจสอบรูปแบบการพักก่อนนำผลครั้งนี้ไปเปรียบเทียบ'
    :canonicalRecommendation||(presentation==='recovery'
      ?'ครั้งถัดไปเลือกเวลาที่สบาย แล้วปล่อยให้ร่างกายพักโดยไม่ต้องบังคับให้หลับ'
      :'รักษาเวลาเข้านอนให้สม่ำเสมอ และค่อย ๆ ปรับสิ่งรบกวนทีละอย่าง');
  const subjective=summary.subjective_outcome||{};
  const subjectiveRows=[];
  if(subjective.status==='measured'){
    const freshnessRaw=subjective.freshness_delta;
    const freshness=freshnessRaw==null||freshnessRaw===''?null:Number(freshnessRaw);
    if(freshness!==null&&Number.isFinite(freshness)){
      const amount=Number.isInteger(Math.abs(freshness))
        ?String(Math.abs(freshness)):Math.abs(freshness).toFixed(1);
      subjectiveRows.push(freshness>0
        ?`สดชื่นขึ้น ${amount} ระดับ`
        :freshness<0?`ความสดชื่นลดลง ${amount} ระดับ`:'ความสดชื่นใกล้เคียงก่อนพัก');
    }
    const readinessRaw=subjective.activity_readiness;
    const readiness=readinessRaw==null||readinessRaw===''?null:Number(readinessRaw);
    if(readiness!==null&&Number.isFinite(readiness)){
      subjectiveRows.push(`ความพร้อมทำกิจกรรม ${readiness.toFixed(1).replace(/\.0$/,'')}/10`);
    }
  }
  const subjectiveMarkup=subjectiveRows.length
    ?`<div class="restore-subjective-outcome"><b>ความรู้สึกก่อน–หลังพัก</b><span>${subjectiveRows.map(row=>historyEscape(row)).join(' · ')}</span><small>จากแบบประเมินของผู้ใช้ · ไม่ได้อนุมานจาก Sensor</small></div>`
    :'';
  const personalBaseline=summary.personal_baseline||{};
  const maturity=personalBaseline.maturity||personalBaseline;
  const maturityKey=String(maturity.key||personalBaseline.status||'learning');
  const userMaturityLabel={
    learning:'กำลังเรียนรู้รูปแบบของคุณ',early:'เริ่มเห็นรูปแบบของคุณ',
    active:'พร้อมเทียบกับรูปแบบของคุณ',stable:'รูปแบบของคุณชัดเจนขึ้น',
  }[maturityKey]||'กำลังเรียนรู้รูปแบบของคุณ';
  const maturityLabel=adminView
    ?restorePlainText(maturity)||userMaturityLabel:userMaturityLabel;
  const sessionsUsed=Number(maturity.sessions_used??personalBaseline.sessions_used);
  const baselineText=Number.isFinite(sessionsUsed)&&sessionsUsed>0
    ?`${maturityLabel} · จากการพัก ${Math.round(sessionsUsed)} ครั้ง`:maturityLabel;
  const confidence=summary.confidence||payload.data_quality?.confidence
    ||report.data_quality?.confidence||{};
  const confidenceLabel=restorePlainText(confidence)||'ยังไม่ระบุ';
  const confidenceDisplay=scoreAvailable
    ?(adminView?confidenceLabel:userConfidenceLevelLabel(confidence.level))
    :!ended?'กำลังบันทึกข้อมูล':'ข้อมูลยังไม่พอสรุปคะแนน';
  const scope=summary.session_scope||summary.scope||{};
  const scopeLabel=adminView
    ?restorePlainText(scope)||(presentation==='recovery'?'Nap & Refresh':'Overnight Recovery')
    :presentation==='recovery'?'Nap & Refresh':presentation==='sleep'?'Overnight Recovery':'การพักครั้งนี้';
  const scoreTone=scoreAvailable
    ?sleepQualityTone(quality,safetyReviewRequired):'unavailable';
  const safetyBanner=safetyReviewRequired
    ?'<div class="result-safety-review"><b>ควรให้ทีมตรวจสอบ</b><span>มีค่าสภาพแวดล้อมบางช่วงแตะเกณฑ์ความปลอดภัย คะแนนยังแสดงได้ แต่ควรตรวจรายละเอียดก่อนใช้งานครั้งถัดไป</span></div>'
    :'';
  return `<section class="restore-summary-card result-summary-card mode-${presentation} quality-${scoreTone}" style="--quality-score:${scoreAvailable?Number(quality.score)||0:0}">
    <div class="result-summary-primary">
      <div class="sleep-quality-ring"><strong>${scoreAvailable?historyEscape(quality.score):'—'}</strong><small>/100</small></div>
      <div class="result-summary-copy">
        <span class="sleep-quality-eyebrow">${historyEscape(scoreTitle)} · ZEEP WELLNESS</span>
        <h3>${historyEscape(statusLabel)}</h3>
        ${statusMeaning?`<p>${historyEscape(statusMeaning)}</p>`:''}
        <small>${historyEscape(scopeLabel)} · ${adminView?'ประเมินเฉพาะ Session นี้':'สรุปเฉพาะการพักครั้งนี้'}</small>
      </div>
    </div>
    ${safetyBanner}
    <div class="result-summary-actions"><div class="restore-drivers">${driverMarkup}</div><div class="restore-recommendation"><b>คำแนะนำครั้งถัดไป</b><p>${recommendation?historyEscape(recommendation):'ใช้งานตามปกติและสังเกตความรู้สึกหลังพัก'}</p></div></div>
    ${subjectiveMarkup}
    <div class="restore-summary-meta"><span><b>รูปแบบของคุณ</b>${historyEscape(baselineText)}</span><span><b>${adminView?'ความมั่นใจ':'ความชัดเจนของข้อมูล'}</b>${historyEscape(confidenceDisplay)}</span></div>
    ${adminView?adminResultEvidence(report,quality,summary,presentation):''}
    <div class="restore-claim-note">${adminView?'ผลสรุปสำหรับตรวจสอบระบบและพัฒนาต่อ':'ผล Wellness เฉพาะการพักครั้งนี้ · ดูร่วมกับความรู้สึกของคุณ · ไม่ใช่การวินิจฉัย'}</div>
  </section>`;
}

function renderHistorySummary(d){
  const summary=d.summary||{};
  const root=document.getElementById('historySummary');
  const adminView=currentPrincipal?.role==='admin';
  const selected=document.getElementById('historyDateFrom').value===historyLocalToday()
    &&document.getElementById('historyDateTo').value===historyLocalToday();
  const scope=adminView?`${summary.people_count||0} คน`:'ผลการพัก';
  const scopeNote=adminView
    ?'Session ที่จบแล้วในช่วงที่เลือก · Asia/Bangkok'
    :'สรุปการพักที่บันทึกไว้ในช่วงนี้';
  root.innerHTML=`<div class="history-summary-heading"><span>${selected?'วันนี้':'ช่วงที่เลือก'}</span><b>${scope}</b><small>${scopeNote}</small></div>
    <div class="history-summary-metrics">
      <div><span>${adminView?'Session':'การพัก'}</span><b>${summary.session_count||0}</b></div>
      <div><span>Overnight Recovery</span><b>${summary.sleep_score_count||0}</b><small>ครั้งที่มี Sleep Score</small></div>
      <div><span>Nap & Refresh</span><b>${summary.recovery_score_count||0}</b><small>ครั้งที่มี Recovery Score</small></div>
      <div><span>ยังสรุปคะแนนไม่ได้</span><b>${summary.without_score_count??summary.awaiting_score_count??0}</b></div>
    </div>`;
}

function historyJourneyMode(mode){
  const score=mode.latest_score==null?'—':historyEscape(mode.latest_score);
  const scoreCaption=mode.latest_score==null
    ?'Session ล่าสุดยังไม่มีคะแนน'
    :`${historyEscape(mode.score_title)} ล่าสุด`;
  const targetText=(mode.targets||[]).map(item=>{
    const latest=item.latest_score==null?'ยังไม่มีคะแนนล่าสุด':`ล่าสุด ${historyEscape(item.latest_score)}`;
    return `${historyEscape(item.minutes)} นาที ${item.session_count} ครั้ง · ${latest}`;
  }).join(' / ');
  const trend=mode.trend?.label||'กำลังสะสมข้อมูลในรูปแบบนี้';
  return `<article class="history-journey-mode mode-${historyEscape(mode.key)}">
    <div class="history-journey-mode-head"><span>${historyEscape(mode.label)}</span><b>${mode.session_count} ครั้ง</b></div>
    <div class="history-journey-score"><strong>${score}</strong><span>${scoreCaption}</span></div>
    <p>${historyEscape(trend)}</p>
    <small>มีคะแนน ${mode.scored_count} ครั้ง${mode.without_score_count?` · ยังสรุปคะแนนไม่ได้ ${mode.without_score_count} ครั้ง`:''}${targetText?` · เป้าหมาย ${targetText}`:''}</small>
  </article>`;
}

function renderUserJourney(payload){
  const root=document.getElementById('historyUserJourney');
  const history=payload.observed_history||{};
  const adminView=currentPrincipal?.role==='admin';
  if(!history.session_count){
    root.innerHTML='<div class="history-journey-empty"><b>ยังไม่มีภาพรวมสะสม</b><span>ระบบจะเริ่มรวมข้อมูลเมื่อมี Session ที่จบ</span></div>';
    return;
  }
  const identity=adminView
    ?historyEscape(payload.user?.email||payload.user?.canonical_identifier||'ผู้ใช้งาน')
    :'รูปแบบการพักของคุณ';
  const duration=fmtDur(Number(history.usage_minutes||0)*60);
  const noSensor=history.without_sensor_data_count
    ?` · ไม่มีข้อมูล Sensor ${history.without_sensor_data_count} ครั้ง`:'';
  const noScore=history.without_score_count
    ?` · ${history.without_score_count} ครั้งยังสรุปคะแนนไม่ได้`:'';
  root.innerHTML=`<div class="history-journey-head">
      <div><span>ภาพรวมสะสมตั้งแต่เริ่ม Pilot</span><b>${identity}</b><small>ใช้ ZEEP ${history.session_count} ครั้ง · เวลารวม ${duration}${noScore}${noSensor}</small></div>
      <div class="history-learning-state"><span>PERSONAL CONTEXT</span><b>${historyEscape(payload.learning_readiness?.label||'กำลังเรียนรู้รูปแบบของคุณ')}</b><small>ข้อมูลประกอบคำแนะนำ · คุณเป็นผู้ยืนยันก่อนปรับอุปกรณ์</small></div>
    </div>
    <div class="history-journey-modes">${historyJourneyMode(payload.modes.sleep)}${historyJourneyMode(payload.modes.nap_recovery)}</div>
    <div class="history-journey-note">Overnight และ Nap เรียนรู้แยกกัน · จำนวนครั้งที่ใช้ไม่ถูกตีความว่าเป็นความชอบ</div>`;
}

async function refreshUserJourney(force=false){
  const root=document.getElementById('historyUserJourney');
  if(!root||!currentPrincipal)return;
  const requestSeq=++historyJourneyRequestSeq;
  const adminView=currentPrincipal.role==='admin';
  const account=document.getElementById('historyUser')?.value||'';
  if(adminView&&!account){
    root.innerHTML='<div class="history-journey-empty compact"><b>เลือกผู้ใช้งานเพื่อดูภาพรวมสะสม</b><span>การ์ดนี้รวม Overnight Recovery และ Nap & Refresh ของคนเดียวกัน</span></div>';
    return;
  }
  const principalKey=currentPrincipal.account_key||currentPrincipal.email
    ||currentPrincipal.username||'';
  const cacheKey=`${currentPrincipal.role}:${adminView?account:principalKey}`;
  const cached=historyJourneyCache.get(cacheKey);
  if(!force&&cached&&Date.now()-cached.savedAt<HISTORY_JOURNEY_CACHE_MS){
    renderUserJourney(cached.payload);
    return;
  }
  root.innerHTML='<div class="mini">กำลังรวมรูปแบบการพักที่ผ่านมา…</div>';
  const path='/api/v1/usage-sessions/longitudinal';
  const headers=adminView?{'X-Zeep-Account-Key':account}:{};
  try{
    const response=await fetch(path,{cache:'no-store',headers});
    if(!response.ok)throw new Error(`HTTP ${response.status}`);
    const data=(await response.json()).data||{};
    const selected=document.getElementById('historyUser')?.value||'';
    if(requestSeq!==historyJourneyRequestSeq||(adminView&&selected!==account))return;
    historyJourneyCache.set(cacheKey,{payload:data,savedAt:Date.now()});
    renderUserJourney(data);
  }catch{
    if(requestSeq!==historyJourneyRequestSeq)return;
    root.innerHTML='<div class="history-journey-empty compact"><b>ยังรวมภาพรวมสะสมไม่ได้</b><span>รายการ Session ด้านล่างยังใช้งานได้ตามปกติ</span></div>';
  }
}

function renderSessionList(d){
  const root = document.getElementById('sessionList'); root.innerHTML = '';
  renderHistorySummary(d);
  if (!d.sessions.length){
    root.innerHTML=currentPrincipal?.role==='admin'
      ?`<div class="history-empty"><b>${currentPrincipal?.role==='admin'?'ไม่พบ Session ในช่วงเวลานี้':'ยังไม่มีประวัติในช่วงเวลานี้'}</b><span>ลองเลือกวัน${currentPrincipal?.role==='admin'?' เวลา หรือชื่อผู้ใช้งาน':'หรือช่วงเวลา'}ใหม่</span></div>`
      :'<div class="history-empty"><b>ยังไม่มีประวัติในช่วงนี้</b><span>ลองเลือกวันหรือช่วงเวลาอื่น</span></div>';
    return;
  }
  d.sessions.forEach(sx=>{
    const presentation=reportPresentationMode(sx);
    const modeLabel=presentation==='recovery'
      ?'Nap & Refresh'
      :presentation==='sleep'?'Overnight Recovery':currentPrincipal?.role==='admin'?'รูปแบบยังไม่ยืนยัน':'ผลการพักครั้งนี้';
    const row = document.createElement('button'); row.className = `hist-row mode-${presentation}`;
    const identity=currentPrincipal?.role==='admin'
      ? `<span class="hist-person-label"><b>${historyEscape(identityLabel(sx))}</b><small>${historyEscape(sx.display_name||'')}</small></span>`:'';
    row.innerHTML =
      `${identity}<b>${fmtDateTh(sx.ended_at_utc||sx.started_at_utc)}</b>`+
      `<span class="hist-mode-label mode-${presentation}"><b>${modeLabel}</b><small>${currentPrincipal?.role==='admin'?'Sensor บันทึก':'ระยะเวลาใช้งาน'} ${fmtDur(sx.duration_s)}</small></span>` +
      `${sleepQualityCompact(
        sx.sleep_quality,sx.ended_at_utc,presentation,
        reportSafetyReviewRequired(sx),
      )}`;
    row.onclick = ()=>loadDetail(sx.account_key||d.account_key||d.username, sx.session_id, row);
    root.appendChild(row);
  });
}

async function loadDetail(user, sid, row){
  const requestSeq=++historyDetailRequestSeq;
  document.querySelectorAll('.hist-row').forEach(x=>x.classList.remove('sel'));
  row?.classList.add('sel');
  const adminView=currentPrincipal?.role==='admin';
  document.getElementById('sessionDetail').innerHTML=`<div class="flat-message loading"><span class="flat-icon"></span><div><b>กำลังเตรียมผลการพัก</b><span>${adminView?'กำลังอ่านผลและ Timeline ของ Session':'กำลังเรียบเรียงรายละเอียดการพักของคุณ'}</span></div></div>`;
  const legacyPath=`/api/history/${encodeURIComponent(user)}/${encodeURIComponent(sid)}`;
  let r;
  // The local Pi report retains the confirmed Sleep State sequence. The new
  // raw-free v1 API remains the contract for ZEEP Backend/Mobile integration.
  try { r=await fetch(legacyPath,{cache:'no-store'}); }
  catch { toast(adminView?'เชื่อมต่อ server ไม่ได้':'ยังเชื่อมต่อระบบไม่ได้ กรุณาลองอีกครั้ง', 'error'); return; }
  if (!r.ok){ toast(adminView?`โหลดรายละเอียดไม่ได้ · HTTP ${r.status}`:'ยังโหลดรายละเอียดไม่ได้ กรุณาลองอีกครั้ง', 'error'); return; }
  const data=await r.json();
  if(requestSeq!==historyDetailRequestSeq)return;
  renderReport(data);
  // On a tablet the history list can fill most of the viewport. Bring the
  // completed report into view so the newly requested quality result is not
  // hidden below the fixed navigation bar.
  requestAnimationFrame(()=>document.getElementById('sessionDetail').scrollIntoView({behavior:'smooth',block:'start'}));
}

function statBlock(label, st, unit){
  if (!st) return '';
  return `<div class="report-stat"><div class="muted">${label}</div><div class="v">${st.avg}${unit}</div>` +
         `<div class="mini" style="margin-top:4px">ต่ำสุด ${st.min} · สูงสุด ${st.max}</div></div>`;
}
