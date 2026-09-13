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

function sleepQualityTone(q){
  return ['very_good','good','fair','low'].includes(q?.level_key) ? q.level_key : 'unavailable';
}

function sleepQualityCompact(q, ended, presentationOverride){
  if (!ended) return `<span class="hist-quality quality-unavailable"><strong>LIVE</strong><span><b>กำลังบันทึก</b><small>${currentPrincipal?.role==='admin'?'คุณภาพหลังจบ Session':'ผลจะแสดงเมื่อจบการพัก'}</small></span></span>`;
  const presentation=presentationOverride||reportPresentationMode(q);
  const adminView=currentPrincipal?.role==='admin';
  const title=presentation==='recovery'
    ?'Recovery Score'
    :presentation==='sleep'?'Sleep Score':adminView?(q?.score_title||'คะแนน'):'ผลการพัก';
  if (!q?.available) return `<span class="hist-quality quality-unavailable"><strong>—</strong><span><b>${adminView?'รอข้อมูลสำหรับคะแนน':'กำลังเตรียมผล'}</b><small>${title}</small></span></span>`;
  return `<span class="hist-quality quality-${sleepQualityTone(q)}"><strong>${q.score}</strong><span><b>${historyEscape(userScoreLevelLabel(q))}</b><small>${title}</small></span></span>`;
}

function renderSleepQuality(q, ended, presentationOverride){
  const adminView=currentPrincipal?.role==='admin';
  const presentation=presentationOverride||reportPresentationMode(q);
  const scoreTitle=presentation==='recovery'
    ?'Recovery Score'
    :presentation==='sleep'?'Sleep Score':adminView?(q?.score_title||'คะแนน Session'):'ผลการพักครั้งนี้';
  if (!ended || !q?.available){
    const reason = !ended
      ?'คะแนนจะแสดงเมื่อจบการพัก'
      :'ZEEP กำลังรวบรวมข้อมูลต่อเนื่องเพื่อสรุปคะแนนครั้งนี้';
    const adminReason=currentPrincipal?.role==='admin'&&q?.reason
      ?`<small>สำหรับผู้ดูแล · ${historyEscape(q.reason)}</small>`:'';
    return `<section class="sleep-quality-card quality-unavailable mode-${presentation}"><div class="sleep-quality-ring"><strong>—</strong><small>/100</small></div><div class="sleep-quality-copy"><span class="sleep-quality-eyebrow">${scoreTitle}</span><h3>กำลังเตรียมผลสรุป</h3><p>${reason}</p><small>เมื่อข้อมูลต่อเนื่องเพียงพอ ZEEP จะสรุปให้โดยอัตโนมัติ</small>${adminReason}</div></section>`;
  }
  const components=q.component_points||{},componentMax=q.component_max_points||{};
  const arousal=q.continuity?.arousal_proxy||{};
  const pointText=key=>components[key]==null?'--':`${Number(components[key]).toFixed(1)} / ${Number(componentMax[key]||0).toFixed(0)}`;
  const legacyLabels={duration:'เวลาพัก',architecture:'รูปแบบการนอน',continuity:'ความต่อเนื่อง'};
  const userComponentLabels={
    ...legacyLabels,
    sleep_opportunity:'เวลาและการเข้าสู่การนอน',
    sleep_stability:'ความต่อเนื่องของการนอน',
    restorative_architecture:'รูปแบบการนอน',
    cycle_expression:'รอบการนอน',
    goal_duration:'เวลาพักตามเป้าหมาย',
    physiological_response:'การตอบสนองระหว่างพัก',
    rest_continuity:'ความต่อเนื่องในการพัก',
    environment_support:'บรรยากาศระหว่างพัก',
  };
  const componentRows=(q.component_order||Object.keys(components)).map(key=>[
    adminView
      ?q.component_labels?.[key]||legacyLabels[key]||key
      :userComponentLabels[key]||'รายละเอียดคะแนน',
    pointText(key),
  ]);
  const targetText=q.duration_target?.target_minutes!=null
    ? `${q.duration_target.target_minutes} นาที`
    : q.duration_target?.range_minutes
    ? `${q.duration_target.range_minutes[0]}–${q.duration_target.range_minutes[1]} นาที`
    : q.duration_target?.hours==null?null:`${q.duration_target.hours} ชม.`;
  const restMetrics = [
    ['รูปแบบการพัก', adminView
      ?q.rest_mode?.label||'ประเมินตามเวลาที่บันทึกจริง'
      :presentation==='sleep'?'Overnight Recovery':presentation==='recovery'?'Nap & Refresh':'การพักครั้งนี้'],
    ...componentRows,
    targetText?[adminView?'เป้าหมายเวลา':'ช่วงเวลาที่เลือก',targetText]:null,
    q.duration_target?.eligible_rest_minutes==null?null:
      ['เวลาพักที่นับได้',`${q.duration_target.eligible_rest_minutes} นาที`],
    q.duration_target?.completion_pct==null?null:
      [adminView?'ความสำเร็จตามเป้าหมาย':'เวลาพักที่ทำได้',`${q.duration_target.completion_pct}%`],
    !adminView||q.physiology?.heart_rate_average==null?null:['ชีพจรเฉลี่ย',`${q.physiology.heart_rate_average} bpm`],
    !adminView||q.physiology?.respiration_average==null?null:['หายใจเฉลี่ย',`${q.physiology.respiration_average} ครั้ง/นาที`],
    q.body_response?.movement_pct==null?null:['การเคลื่อนไหว',`${q.body_response.movement_pct}%`],
    ['ผลที่ตรวจพบ',q.session_character==='hybrid'?'พักและมีช่วงหลับ':'พักขณะตื่น · ไม่จำเป็นต้องหลับ'],
  ];
  const sleepMetrics = [
    ['รูปแบบการพัก', q.rest_mode?.label || 'ประเมินตามเวลาที่บันทึกจริง'],
    ...componentRows,
    ['เวลานอนโดยประมาณ', fmtDur(q.estimated_sleep_s)],
    targetText?[adminView?'เป้าหมายเวลา':'ช่วงเวลาที่แนะนำ',targetText]:null,
    ['เวลาที่แสดงสถานะการนอน', fmtDur(q.actual_scored_s)],
    [adminView?'สัดส่วนเวลานอน':'เวลาที่ระบบประเมินว่าหลับ', `${q.sleep_efficiency_pct}%`],
    ['เข้าสู่ W · ตื่น', `${q.wake_entries ?? q.awakenings ?? 0} ครั้ง`],
    q.deep_pct == null ? null : ['N3 / หลับลึก', `${q.deep_pct}%`],
    q.rem_pct == null ? null : ['REM / หลับฝัน', `${q.rem_pct}%`],
    arousal.available?[adminView?'BCG disturbance proxy':'ช่วงที่มีการรบกวน',`${arousal.episodes} ครั้ง · ${arousal.index_per_hour}/ชม.`]:null,
  ];
  const metrics=(q.quality_type==='rest_goal'?restMetrics:sleepMetrics)
    .filter(Boolean).map(([label,value])=>`<div><span>${label}</span><b>${value}</b></div>`).join('');
  const technicalNote=currentPrincipal?.role==='admin'
    ?`${q.outcome_interpretation?`${q.outcome_interpretation} · `:''}${q.score_basis || ''} · ${q.disclaimer || 'ประเมินจาก BCG/Sensor ไม่ใช่ผลวินิจฉัยจาก PSG'}`
    :'ผลประเมินเพื่อ Wellness · ไม่ใช่การวินิจฉัยหรือทดแทนผลตรวจทางการแพทย์';
  const levelLabel=adminView?(q.level||userScoreLevelLabel(q)):userScoreLevelLabel(q);
  const insight=adminView
    ?q.insight||''
    :userScoreMeaning(q);
  return `<section class="sleep-quality-card quality-${sleepQualityTone(q)} mode-${presentation}" style="--quality-score:${q.score}">
    <div class="sleep-quality-ring"><strong>${q.score}</strong><small>/100</small></div>
    <div class="sleep-quality-copy"><span class="sleep-quality-eyebrow">${scoreTitle} · ZEEP WELLNESS</span><h3>${historyEscape(levelLabel)}</h3><p>${adminView?(q.score_scope||'ค่าประเมินจาก Sensor'):'ภาพรวมจากการพักครั้งนี้'}${insight?` · ${historyEscape(insight)}`:''}</p><div class="sleep-quality-metrics">${metrics}</div><small>${technicalNote}</small></div>
  </section>`;
}

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
    const adminView=currentPrincipal?.role==='admin';
    list.innerHTML=`<div class="flat-message loading"><span class="flat-icon"></span><div><b>กำลังโหลดประวัติการใช้งาน</b><span>${adminView?'กำลังอ่าน Session จากเครื่อง Pi':'กำลังเตรียมรายการย้อนหลังของคุณ'}</span></div></div>`;
    document.getElementById('historySummary').innerHTML='<div class="mini">กำลังสรุปช่วงเวลาที่เลือก…</div>';
    document.getElementById('historyParticipants').innerHTML='';
    document.getElementById('sessionDetail').innerHTML='';
    const params=historyFilterParams();
    const path=currentPrincipal?.role==='admin'
      ? `/api/admin/history?${params}`
      : `/api/history/${encodeURIComponent(user)}?${params}`;
    let r;
    try { r=await fetch(path,{cache:'no-store'}); }
    catch { toast(adminView?'เชื่อมต่อ server ไม่ได้':'ยังเชื่อมต่อระบบไม่ได้ กรุณาลองอีกครั้ง', 'error'); return; }
    if (!r.ok){
      let detail='';try{detail=(await r.json()).detail||'';}catch{}
      toast(adminView?(detail||`โหลดประวัติไม่ได้ · HTTP ${r.status}`):'ยังโหลดประวัติไม่ได้ กรุณาลองอีกครั้ง','error');return;
    }
    renderSessionList(await r.json());
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
  if(unavailable)return 'ZEEP กำลังรวบรวมข้อมูลเพื่ออธิบายผลการพักครั้งนี้';
  const meanings={
    sleep_restore_very_good:'ภาพรวมการนอนคืนนี้เป็นไปได้ดีมาก',sleep_restore_good:'ภาพรวมการนอนคืนนี้เป็นไปได้ดี',
    pace_morning:'คืนนี้ได้พักในระดับหนึ่ง',prioritise_rest:'ครั้งนี้ยังมีบางจุดที่ช่วยให้การพักสบายขึ้นได้',
    rest_goal_full:'ช่วงพักนี้เป็นไปได้ดีมากตามเวลาที่เลือก',rest_good:'ช่วงพักนี้เป็นไปได้ดี',
    rest_partial:'ช่วงพักนี้ช่วยให้ร่างกายได้หยุดนิ่งและผ่อนคลาย',rest_more:'ครั้งนี้ยังมีบางจุดที่ลองปรับให้สบายขึ้นได้',
  };
  return meanings[statusKey]||(presentation==='recovery'?'ดูผลช่วงพักนี้ร่วมกับความรู้สึกหลังพัก':'ดูภาพรวมคืนนี้ร่วมกับความรู้สึกหลังตื่น');
}

function restoreSummaryTone(status){
  const key=String(status?.key||status||'').toLowerCase();
  if([
    'excellent','very_good','good','restored','strong',
    'sleep_restore_very_good','sleep_restore_good','rest_goal_full','rest_good',
  ].includes(key))return 'good';
  if(['fair','moderate','partial','pace_morning','rest_partial'].includes(key))return 'fair';
  if([
    'low','poor','attention','needs_attention','prioritise_rest','rest_more',
  ].includes(key))return 'attention';
  return 'neutral';
}

function renderRestoreSummary(source,presentation){
  const payload=source?.data||source||{};
  const report=payload.session_report||payload;
  const summary=restoreSummarySource(source);
  if(!summary)return '';
  const adminView=currentPrincipal?.role==='admin';
  const unavailable=summary.available===false;
  const status=summary.status||{};
  const statusKey=String(status?.key||status||'').toLowerCase();
  const statusLabels={
    excellent:'ยอดเยี่ยม',very_good:'ดีมาก',good:'ดี',fair:'พอใช้',
    low:'ให้เวลากับการพักเพิ่ม',sleep_restore_very_good:'ดีมาก',
    sleep_restore_good:'ดี',pace_morning:'ได้พักในระดับหนึ่ง',
    prioritise_rest:'ให้เวลากับการพักเพิ่ม',rest_goal_full:'พักได้ตามเป้าหมาย',
    rest_good:'ช่วงพักเป็นไปได้ดี',rest_partial:'ได้พักในระดับหนึ่ง',
    rest_more:'ลองปรับให้สบายขึ้น',
  };
  const statusLabel=(adminView
    ?restorePlainText(status?.label||status?.title):statusLabels[statusKey])
    ||statusLabels[statusKey]
    ||(unavailable?'กำลังเตรียมผลสรุป':'สรุปผลแล้ว');
  const statusMeaning=adminView
    ?restorePlainText(status?.meaning||status?.description)
    :userRestoreMeaning(statusKey,presentation,unavailable);
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
  const driverMarkup=unavailable
    ?'<div class="restore-summary-empty">ZEEP กำลังรวบรวมข้อมูลเพื่ออธิบายผลการพักครั้งนี้</div>'
    :[
      driverGroup('สิ่งที่ทำได้ดี',positives,'positive'),
      driverGroup('สิ่งที่ลองปรับได้',attentions,'attention'),
    ].join('')||'<div class="restore-summary-empty">ยังไม่มีปัจจัยที่ต้องดูแลเป็นพิเศษ</div>';
  const recommendation=adminView
    ?restorePlainText(summary.recommendation,['primary'])||restorePlainText(report.post_session_guidance,['primary'])
    :presentation==='recovery'
      ?'ครั้งถัดไปเลือกเวลาที่สบาย แล้วปล่อยให้ร่างกายพักโดยไม่ต้องบังคับให้หลับ'
      :'รักษาเวลาเข้านอนให้สม่ำเสมอ และค่อย ๆ ปรับสิ่งรบกวนทีละอย่าง';
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
  const confidenceDisplay=adminView
    ?confidenceLabel:userConfidenceLevelLabel(confidence.level);
  const scope=summary.session_scope||summary.scope||{};
  const scopeLabel=adminView
    ?restorePlainText(scope)||(presentation==='recovery'?'Nap & Refresh':'Overnight Recovery')
    :presentation==='recovery'?'Nap & Refresh':presentation==='sleep'?'Overnight Recovery':'การพักครั้งนี้';
  return `<section class="restore-summary-card mode-${presentation}">
    <div class="restore-summary-head"><div><span>RESTORE SUMMARY</span><h3>สรุปผลหลังใช้งาน</h3><small>${historyEscape(scopeLabel)} · ${adminView?'ประเมินเฉพาะ Session นี้':'สรุปเฉพาะการพักครั้งนี้'}</small></div><strong class="restore-status ${restoreSummaryTone(status)}">${historyEscape(statusLabel)}</strong></div>
    ${statusMeaning?`<p class="restore-status-meaning">${historyEscape(statusMeaning)}</p>`:''}
    <div class="restore-summary-grid"><div class="restore-drivers">${driverMarkup}</div><div class="restore-recommendation"><b>ลองทำครั้งถัดไป</b><p>${recommendation?historyEscape(recommendation):'ใช้งานตามปกติและสังเกตความรู้สึกหลังพัก'}</p></div></div>
    <div class="restore-summary-meta"><span><b>รูปแบบของคุณ</b>${historyEscape(baselineText)}</span><span><b>${adminView?'ความมั่นใจ':'ความชัดเจนของข้อมูล'}</b>${historyEscape(confidenceDisplay)}</span></div>
    <div class="restore-claim-note">${adminView?'ปัจจัยเป็นความสัมพันธ์ใกล้เวลา ไม่ยืนยันเหตุ–ผล และไม่ใช่ความพร้อมตลอดทั้งวัน':'ผลนี้สะท้อนเฉพาะการพักครั้งนี้ และควรดูร่วมกับความรู้สึกของคุณ'}</div>
  </section>`;
}

function historyScoreMarkup(score){
  const available=score?.available&&score?.score!=null;
  const title=historyEscape(score?.score_title||'คะแนน');
  return `<span class="history-score ${available?'available':'unavailable'}"><b>${available?historyEscape(score.score):'—'}</b><small>${title}</small></span>`;
}

function renderHistorySummary(d){
  const summary=d.summary||{};
  const root=document.getElementById('historySummary');
  const adminView=currentPrincipal?.role==='admin';
  const selected=document.getElementById('historyDateFrom').value===historyLocalToday()
    &&document.getElementById('historyDateTo').value===historyLocalToday();
  const scope=adminView
    ? `${summary.people_count||0} คน`
    : `${summary.session_count||0} ครั้ง`;
  const scopeNote=adminView
    ?'นับการใช้งานที่จบแล้วและมีข้อมูล Sensor · Asia/Bangkok'
    :'สรุปการพักที่บันทึกไว้ในช่วงนี้';
  root.innerHTML=`<div class="history-summary-heading"><span>${selected?'วันนี้':'ช่วงที่เลือก'}</span><b>${scope}</b><small>${scopeNote}</small></div>
    <div class="history-summary-metrics">
      <div><span>${adminView?'Session':'การพัก'}</span><b>${summary.session_count||0}</b></div>
      <div><span>Sleep Score</span><b>${summary.sleep_score_count||0}</b><small>${summary.average_sleep_score==null?'—':`เฉลี่ย ${historyEscape(summary.average_sleep_score)}`}</small></div>
      <div><span>Recovery Score</span><b>${summary.recovery_score_count||0}</b><small>${summary.average_recovery_score==null?'—':`เฉลี่ย ${historyEscape(summary.average_recovery_score)}`}</small></div>
      <div><span>${adminView?'รอคะแนน':'กำลังเตรียมผล'}</span><b>${summary.awaiting_score_count||0}</b></div>
    </div>`;
}

function renderHistoryParticipants(d){
  const root=document.getElementById('historyParticipants');
  if(currentPrincipal?.role!=='admin'||!(d.participants||[]).length){
    root.innerHTML='';return;
  }
  root.innerHTML=`<div class="history-people-heading"><b>ผู้ใช้งานและคะแนน</b><span>${d.participants.length} คนในช่วงที่เลือก</span></div><div class="history-people-grid">${d.participants.map(person=>{
    const scores=(person.scores||[]).map(historyScoreMarkup).join('');
    return `<button type="button" class="history-person" data-history-account="${historyEscape(person.account_key)}"><span class="history-person-avatar">${historyEscape(identityLabel(person,'?').slice(0,1).toUpperCase())}</span><span class="history-person-copy"><b>${historyEscape(identityLabel(person))}</b><small>${person.session_count} Session</small></span><span class="history-person-scores">${scores}</span></button>`;
  }).join('')}</div>`;
  root.querySelectorAll('[data-history-account]').forEach(button=>{
    button.onclick=()=>selectHistoryPerson(button.dataset.historyAccount);
  });
}

function selectHistoryPerson(accountKey){
  const select=document.getElementById('historyUser');
  if(select&&[...select.options].some(option=>option.value===accountKey)){
    select.value=accountKey;
    document.getElementById('historyNameFilter').value='';
    refreshHistory();
  }
}

function renderSessionList(d){
  const root = document.getElementById('sessionList'); root.innerHTML = '';
  renderHistorySummary(d);
  renderHistoryParticipants(d);
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
    const hr = sx.summary?.heart_rate_bpm;
    const identity=currentPrincipal?.role==='admin'
      ? `<span class="hist-person-label"><b>${historyEscape(identityLabel(sx))}</b><small>${historyEscape(sx.display_name||'')}</small></span>`:'';
    row.innerHTML =
      `${identity}<b>${fmtDateTh(sx.ended_at_utc||sx.started_at_utc)}</b>`+
      `<span class="hist-mode-label mode-${presentation}"><b>${modeLabel}</b><small>${currentPrincipal?.role==='admin'?'Sensor บันทึก':'ระยะเวลาใช้งาน'} ${fmtDur(sx.duration_s)}</small></span>` +
      `${sleepQualityCompact(sx.sleep_quality, sx.ended_at_utc, presentation)}` +
      `<span>♥ ${currentPrincipal?.role==='admin'?'HR':'ชีพจร'} ${hr ? hr.avg + ' ครั้ง/นาที' : '--'}</span>`;
    row.onclick = ()=>loadDetail(sx.account_key||d.account_key||d.username, sx.session_id, row);
    root.appendChild(row);
  });
}

async function loadDetail(user, sid, row){
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
  renderReport(await r.json());
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
