const REPORT_STAGE_META={
  wake:{label:'W · ตื่น',color:'#f6b94a'},
  n1:{label:'N1 · หลับตื้น',color:'#56d7eb'},
  n2:{label:'N2 · หลับสนิทขึ้น',color:'#5f8ff2'},
  n3:{label:'N3 · หลับลึก',color:'#9a82ef'},
  rem:{label:'REM · หลับฝัน',color:'#ea79b8'},
};
const RECOVERY_PROFILE_META={
  awake_rest:{label:'พักขณะตื่น',color:'#55dfa5'},
  drowsy:{label:'เคลิ้ม · N1',color:'#56d7eb'},
  short_sleep:{label:'ช่วงหลับที่ประเมินได้',color:'#8f82ef'},
};
const TERMINAL_OCCUPANCY_META={
  no_user_on_bed:{label:'ไม่มีผู้ใช้งานบนเตียง',code:'OFF',color:'#7cc7d8'},
  exited_zeep:{label:'ออกจาก ZEEP',code:'EXIT',color:'#f6b94a'},
};

function reportPresentationMode(source){
  const report=source?.session_report||source||{};
  const quality=report.quality||report.sleep_quality||report;
  const restMode=report.rest_mode||quality.rest_mode||{};
  const group=restMode.group||restMode.key||restMode.requested||restMode.resolved||'';
  const title=String(quality.score_title||restMode.score_title||'').toLowerCase();
  const validationStatus=quality.validation_status||restMode.validation_status;
  const unresolved=quality.rest_mode_unresolved
    ||['legacy_mode_unresolved','mode_unresolved','mode_metadata_conflict'].includes(
      validationStatus,
    )
    ||['auto','unknown_legacy'].includes(group)
    ||(!group&&!quality.quality_type&&!title);
  if(unresolved)return 'unknown';
  if(quality.quality_type==='rest_goal'||group==='nap_recovery'||title.includes('recovery'))return 'recovery';
  if(quality.quality_type==='sleep'||['sleep','overnight'].includes(group)||title.includes('sleep'))return 'sleep';
  return 'unknown';
}

function reportStageDurations(report){
  const values={wake:0,n1:0,n2:0,n3:0,rem:0};
  (report?.stages||[]).forEach(stage=>{
    const key=String(stage?.state||'').toLowerCase();
    if(Object.prototype.hasOwnProperty.call(values,key)){
      values[key]=Math.max(0,Number(stage.duration_s)||0);
    }
  });
  return values;
}

function reportProfileItems(report,presentation){
  const durations=reportStageDurations(report);
  const known=Object.values(durations).reduce((sum,value)=>sum+value,0);
  const denominator=Math.max(known,1);
  let items;
  if(presentation==='recovery'){
    items=[
      {key:'awake_rest',duration_s:durations.wake},
      {key:'drowsy',duration_s:durations.n1},
      {key:'short_sleep',duration_s:durations.n2+durations.n3+durations.rem},
    ].map(item=>({...RECOVERY_PROFILE_META[item.key],...item}));
    if(currentPrincipal?.role==='admin'){
      const sleepItem=items.find(item=>item.key==='short_sleep');
      if(sleepItem)sleepItem.label='ช่วงหลับที่ประเมินได้ · N2/N3/REM';
    }
  }else if(presentation==='sleep'){
    items=Object.keys(durations).map(key=>({...REPORT_STAGE_META[key],key,duration_s:durations[key]}));
  }else{
    items=[];
  }
  return {
    stateSeconds:known,
    items:items.map(item=>({...item,pct:100*item.duration_s/denominator})),
  };
}

function reportProfileMarkup(report,presentation){
  const sleep=report.sleep||{},quality=report.quality||{};
  const adminView=currentPrincipal?.role==='admin';
  if(presentation==='unknown'){
    return `<div class="report-context-note"><b>รูปแบบการพักยังไม่ยืนยัน</b> · แสดงเฉพาะข้อมูลที่ Sensor บันทึก โดยยังไม่ตีความเป็น Overnight หรือ Nap & Refresh</div>`;
  }
  const profile=reportProfileItems(report,presentation);
  const items=profile.items;
  let cursor=0;
  const segments=items.filter(item=>item.duration_s>0).map(item=>{
    const start=cursor,end=Math.min(100,cursor+item.pct);cursor=end;
    return `${item.color} ${start}% ${end}%`;
  });
  if(cursor<100)segments.push(`#1a2d3a ${cursor}% 100%`);
  const rows=items.map(item=>{
    const percentage=item.pct>=10?item.pct.toFixed(0):item.pct.toFixed(1);
    return `<div class="stage-legend-row" style="--stage-color:${item.color}"><i></i><span>${item.label}</span><strong>${percentage}%</strong><span>${fmtDur(item.duration_s)}</span></div>`;
  }).join('');
  const eligible=quality.duration_target?.eligible_rest_seconds;
  const centreValue=presentation==='recovery'
    ?fmtDur(eligible==null?sleep.recording_s:eligible)
    :fmtDur(sleep.estimated_sleep_s);
  const title=presentation==='recovery'?'รูปแบบการพักที่ตรวจพบ':adminView?'สัดส่วน Sleep Stage':'สัดส่วนการนอนที่ประเมินได้';
  const note=presentation==='recovery'
    ?'นับคุณค่าของการพักทั้งขณะตื่นและหลับ'
    :`${adminView?'State ที่เข้าคะแนน':'เวลาที่นำมาสรุปผล'} · ${fmtDur(profile.stateSeconds)}`;
  const centreLabel=presentation==='recovery'?'เวลาพักที่นับได้':'เวลานอนโดยประมาณ';
  const meaning=presentation==='recovery'
    ?'<div class="profile-meaning-note">การพักนิ่งและผ่อนคลายมีคุณค่า แม้ยังไม่หลับ · Recovery Score ดูทั้งเวลาพัก ความนิ่งของร่างกาย และสภาพแวดล้อม</div>'
    :'<div class="profile-meaning-note">แสดงเวลาที่ระบบประเมินได้ในแต่ละช่วงของการนอน · NREM คือ N1 + N2 + N3</div>';
  return `<div class="stage-summary ${presentation==='recovery'?'recovery-profile-summary':''}"><div class="report-subhead"><span>${title}</span><small>${note}</small></div><div class="stage-summary-content"><div class="stage-donut" style="--stage-ring:conic-gradient(${segments.join(',')})"><span><b>${centreValue}</b><small>${centreLabel}</small></span></div><div class="stage-legend">${rows}${meaning}</div></div></div>`;
}

function classificationAccountingMarkup(report,adminView,presentation){
  const sleep=report?.sleep||{};
  const quality=report?.quality||{};
  const accounting=sleep.classification_accounting;
  if(!accounting||typeof accounting!=='object')return '';
  const recovery=presentation==='recovery';
  const recording=Number(accounting.recording_s??sleep.recording_s)||0;
  const displayed=Number(accounting.display_attributed_s??accounting.classified_s)||0;
  const restEligible=Number(quality.duration_target?.eligible_rest_seconds);
  const eligible=recovery
    ?Number.isFinite(restEligible)
      ?Math.max(0,Math.min(recording,restEligible))
      :null
    :Number(accounting.score_eligible_s??sleep.actual_scored_s)||0;
  const excluded=recovery
    ?eligible==null?null:Math.max(0,recording-eligible)
    :Number(accounting.excluded_from_score_s)||Math.max(0,recording-eligible);
  const invariant=accounting.arithmetic_invariant||{};
  const status=invariant.holds===true?'ครบถ้วน':invariant.holds===false?'ต้องตรวจสอบ':'รอข้อมูล';
  const statusClass=invariant.holds===true?'good':invariant.holds===false?'attention':'neutral';
  const title=recovery
    ?'บัญชีเวลาการพักและ State ประกอบ'
    :invariant.holds===true
    ?'เวลาของ Session ถูกจัดหมวดครบ'
    :invariant.holds===false
      ?'พบบัญชีเวลาที่ต้องตรวจสอบ'
      :'กำลังตรวจบัญชีเวลา';
  if(!adminView){
    const offBed=Number(accounting.off_bed_s)||0;
    if(invariant.holds!==false){
      return offBed>0
        ?`<div class="report-context-note user-off-bed-note"><b>ช่วงออกจากเตียง</b> · ${fmtDur(offBed)} · แยกจากเวลาพักที่ใช้สรุปผล</div>`
        :'';
    }
    return `<section class="classification-accounting-card user-time-summary">
      <div class="classification-accounting-head"><div><span>ช่วงเวลาการพัก</span><h3>กำลังตรวจสอบเวลาบางช่วง</h3></div><b class="accounting-status attention">กำลังตรวจสอบ</b></div>
      <div class="classification-accounting-metrics">
        <div><span>ระยะเวลาใช้งาน</span><b>${fmtDur(recording)}</b></div>
        <div><span>${recovery?'เวลาพักที่นับได้':'เวลาที่ใช้สรุปผล'}</span><b>${fmtDur(eligible)}</b></div>
        ${offBed>0?`<div><span>ช่วงออกจากเตียง</span><b>${fmtDur(offBed)}</b></div>`:''}
      </div>
      <p>${recovery?'ZEEP นับคุณค่าของการพักทั้งขณะตื่นและหลับ':'ทุกช่วงที่อยู่บนเตียงถูกนำมาประเมินอย่างต่อเนื่อง'}</p>
    </section>`;
  }
  const details=[
    ['ยืนยันโดยตรง',accounting.direct_confirmed_s],
    ['คง State ก่อนหน้า',accounting.continuity_carried_forward_s],
    ['provisional',accounting.provisional_hold_s],
    ['WAIT เริ่มต้น',accounting.initial_wait_s],
    ['NO DATA',accounting.no_data_s],
    ['OFF BED',accounting.off_bed_s],
    ['Restart hold',accounting.restart_display_hold_s],
    ['Sensor gap',accounting.sensor_gap_s],
  ].filter(([,value])=>value!=null&&Number(value)>0);
  const detailMarkup=adminView
    ?`<div class="classification-accounting-detail">${details.map(([label,value])=>`<span><small>${label}</small><b>${fmtDur(Number(value))}</b></span>`).join('')}</div>`
    :'';
  return `<section class="classification-accounting-card">
    <div class="classification-accounting-head"><div><span>TIME ACCOUNTING</span><h3>${title}</h3></div><b class="accounting-status ${statusClass}">${status}</b></div>
    <div class="classification-accounting-metrics">
      <div><span>Sensor บันทึก</span><b>${fmtDur(recording)}</b></div>
      <div><span>${recovery?'State (ข้อมูลประกอบ)':'แสดง State'}</span><b>${fmtDur(displayed)}</b></div>
      <div><span>${recovery?'เวลาพักที่นับได้':'ใช้คิดคะแนน'}</span><b>${fmtDur(eligible)}</b></div>
      <div><span>${recovery?'ไม่นับเป็นเวลาพัก':'ไม่นับคะแนน'}</span><b>${fmtDur(excluded)}</b></div>
    </div>
    ${detailMarkup}
    <p>${recovery
      ?'Recovery Score ไม่บังคับให้หลับ · Sleep State ใช้ประกอบการอธิบายเท่านั้น ส่วนคะแนนใช้เวลาพัก ความนิ่ง HR/RR ความนิ่งร่างกาย และสภาพแวดล้อมร่วมกัน'
      :'ทุกช่วง Recording ที่ยังไม่ยืนยัน OFF BED มี State และเข้าคะแนน · ถ้าหลักฐานยังไม่พอ จะคง State เดิมแบบ low-confidence และไม่ใช้เรียนรู้ Personal Baseline · OFF BED เท่านั้นที่ไม่เข้า Sleep Score'}</p>
  </section>`;
}

function reportOverviewMetrics(report,presentation){
  const sleep=report.sleep||{},quality=report.quality||{};
  const adminView=currentPrincipal?.role==='admin';
  let values;
  if(presentation==='recovery'){
    const target=quality.duration_target||{};
    const eligible=target.eligible_rest_seconds==null
      ?Number(sleep.recording_s)||0:Number(target.eligible_rest_seconds)||0;
    const completion=target.completion_pct==null?'--':`${Math.round(Number(target.completion_pct))}%`;
    const regularity=quality.physiology?.regularity_factor;
    const movement=quality.body_response?.movement_pct;
    values=[
      ['◷','เวลาพักที่นับได้',fmtDur(eligible)],
      ['◎',adminView?'เทียบเป้าหมาย':'เวลาพักที่ทำได้',completion],
      ['♥',adminView?'ความนิ่ง HR/RR':'ความนิ่งของสัญญาณชีพ',regularity==null?'--':`${Math.round(100*Number(regularity))}%`],
      ['◇','ความนิ่งร่างกาย',movement==null?'--':`${Math.max(0,Math.round(100-Number(movement)))}%`],
    ];
  }else if(presentation==='sleep'){
    values=[
      ['◷','เวลานอนโดยประมาณ',fmtDur(sleep.estimated_sleep_s)],
      ...(adminView?[['▣','ระยะเวลาใช้งาน',fmtDur(sleep.recording_s)]]:[]),
      ['◎',adminView?'ประสิทธิภาพ':'เวลาที่ประเมินว่าหลับ',sleep.sleep_efficiency_pct==null?'--':`${sleep.sleep_efficiency_pct}%`],
      ['☀','W · ตื่น',fmtDur(sleep.wake_s)],
    ];
  }else{
    values=adminView?[['▣','ระยะเวลาที่บันทึก',fmtDur(sleep.recording_s)]]:[];
  }
  return values.map(([icon,label,value])=>`<div class="session-key-metric"><i>${icon}</i><span><small>${label}</small><b>${value}</b></span></div>`).join('');
}

function recoveryProtocolBadge(report,adminView=false){
  const quality=report.quality||{},sleep=report.sleep||{};
  const minutes=(Number(sleep.recording_s)||0)/60;
  const status=quality.rest_mode?.protocol_status?.status;
  if(minutes<10)return {tone:'review',label:adminView?'สั้นกว่า 10 นาที':'ช่วงพักสั้น'};
  if(status==='implausible_outlier'||status==='out_of_protocol'){
    return {
      tone:'review',
      label:adminView?'ตรวจ Mode/ระยะเวลา':'ระยะเวลาต่างจากรูปแบบที่เลือก',
    };
  }
  const target=quality.duration_target||quality.rest_mode?.protocol_status?.target||{};
  const targetUnknown=quality.legacy_score_preserved===true
    ||quality.target_status==='TARGET_UNKNOWN'
    ||status==='target_unknown'
    ||target.source==='legacy_missing';
  if(targetUnknown){
    return adminView
      ?{tone:'legacy',label:minutes>45?'Legacy target ไม่ถูกบันทึก':'Target เดิมไม่ถูกบันทึก'}
      :null;
  }
  const targetMinutes=Number(target.target_minutes??target.minutes);
  if(Number.isFinite(targetMinutes)){
    return {
      tone:status==='recommended'?'good':'',
      label:adminView?`เป้าหมาย ${Math.round(targetMinutes)} นาที`:`เลือกพัก ${Math.round(targetMinutes)} นาที`,
    };
  }
  if(minutes>120)return {
    tone:'review',
    label:adminView?'ตรวจ Mode/ระยะเวลา':'ระยะเวลาต่างจากรูปแบบที่เลือก',
  };
  if(status==='recommended')return {tone:'good',label:'เป้าหมาย 25–35 นาที'};
  return adminView?{tone:'legacy',label:'Target ยังไม่ยืนยัน'}:null;
}

function respiratoryWellnessTone(status){
  return ({supportive:'good',observe:'fair',needs_recheck:'attention'})[
    String(status||'').toLowerCase()
  ]||'neutral';
}

function renderRespiratoryWellness(report,adminView=false){
  const summary=report?.respiratory_wellness;
  if(!summary||typeof summary!=='object')return '';
  const status=summary.status||{};
  const observations=summary.observations||{};
  const vital=summary.vital_summary||{};
  const age=summary.age_context||{};
  const baseline=summary.personal_baseline||{};
  const confidence=summary.confidence||{};
  const recommendation=summary.recommendation||{};
  const finite=value=>value!==null&&value!==undefined&&value!==''&&Number.isFinite(Number(value));
  const median=finite(observations.median_rr_brpm)
    ?`${Number(observations.median_rr_brpm).toFixed(1)} ครั้ง/นาที`:'—';
  if(!adminView){
    const heartRate=finite(vital.heart_rate_bpm)
      ?`${Number(vital.heart_rate_bpm).toFixed(1)} ครั้ง/นาที`:'ไม่มีข้อมูลสำหรับครั้งนี้';
    const breathingRate=finite(vital.respiration_rate_brpm)
      ?`${Number(vital.respiration_rate_brpm).toFixed(1)} ครั้ง/นาที`:'ไม่มีข้อมูลสำหรับครั้งนี้';
    const summaryText=typeof vital.summary==='string'&&vital.summary.trim()
      ?vital.summary:'ข้อมูลชีพจรและการหายใจยังไม่พอสรุป';
    return `<section class="user-vitals-compact" aria-label="ชีพจรและการหายใจระหว่างพัก">
      <div class="user-vitals-values">
        <span><small>ชีพจร</small><b>${historyEscape(heartRate)}</b></span>
        <span><small>การหายใจ</small><b>${historyEscape(breathingRate)}</b></span>
      </div>
      <p><b>แนวโน้มระหว่างพัก</b>${historyEscape(summaryText)}</p>
    </section>`;
  }
  const range=finite(observations.p10_rr_brpm)&&finite(observations.p90_rr_brpm)
    ?`${Number(observations.p10_rr_brpm).toFixed(1)}–${Number(observations.p90_rr_brpm).toFixed(1)} ครั้ง/นาที`:'ข้อมูลไม่พอสรุป';
  const regularity=({stable:'จังหวะค่อนข้างสม่ำเสมอ',mixed:'จังหวะเปลี่ยนแปลงบางช่วง',variable:'จังหวะเปลี่ยนแปลงระหว่างพัก',insufficient:'กำลังเรียนรู้รูปแบบของคุณ'})[
    observations.regularity_key
  ]||'กำลังเรียนรู้รูปแบบของคุณ';
  const baselineText=baseline.available
    ?`${adminView?(baseline.label||'เทียบกับรูปแบบของคุณแล้ว'):'เทียบกับรูปแบบการพักของคุณแล้ว'} · จากการพัก ${baseline.sessions_used||0} ครั้ง`
    :adminView
      ?`กำลังเรียนรู้ ${baseline.sessions_used||0}/${baseline.minimum_sessions||7} ครั้ง`
      :'กำลังเรียนรู้รูปแบบของคุณจากการพักหลายครั้ง';
  const ageText=age.available
    ?adminView?`${age.label||age.age_band}`:'เทียบกับช่วงวัยของคุณ'
    :'เพิ่มข้อมูลอายุเพื่อรับคำแนะนำที่เหมาะกับช่วงวัย';
  const ageGuidance=adminView&&age.guidance
    ?age.guidance:'ดูแนวโน้มหลายครั้งร่วมกับความรู้สึกหลังพักและกิจกรรมประจำวัน';
  const userStatusLabels={supportive:'จังหวะการหายใจสม่ำเสมอ',observe:'มีการเปลี่ยนแปลงบางช่วง',needs_recheck:'ลองติดตามเพิ่มอีกครั้ง'};
  const statusLabel=adminView
    ?status.label||(summary.available?'สรุปผลแล้ว':'กำลังเรียนรู้รูปแบบของคุณ')
    :userStatusLabels[status.key]||(summary.available?'สรุปแนวโน้มแล้ว':'กำลังเรียนรู้รูปแบบของคุณ');
  const interpretation=adminView
    ?summary.interpretation||'ข้อมูลครั้งนี้ยังไม่พอสรุปแนวโน้ม'
    :summary.available?'แสดงแนวโน้มการหายใจที่พบระหว่างการพักครั้งนี้':'ข้อมูลครั้งนี้ยังไม่พอสรุปแนวโน้ม';
  const confidenceLabel=adminView
    ?confidence.label||'หลักฐานจำกัด'
    :({high:'ชัดเจน',medium:'เพียงพอ',low:'กำลังสะสม'})[confidence.level]||'กำลังสะสม';
  const observationList=adminView
    ?`<li>ค่ากลาง ${historyEscape(median)}</li><li>ช่วง P10–P90 ${historyEscape(range)}</li><li>${historyEscape(regularity)}</li>`
    :`<li>อัตราการหายใจ ${historyEscape(median)}</li><li>ช่วงที่พบเป็นส่วนใหญ่ ${historyEscape(range)}</li><li>${historyEscape(regularity)}</li>`;
  const adminDetails=adminView?`<details class="report-details respiratory-technical"><summary>รายละเอียดคุณภาพสัญญาณสำหรับผู้ดูแล</summary><div class="classification-accounting-detail">
      <span><small>ช่วงใช้ได้</small><b>${finite(observations.valid_minutes)?Number(observations.valid_minutes).toFixed(1):'—'} นาที</b></span>
      <span><small>Coverage</small><b>${finite(observations.coverage_pct)?Number(observations.coverage_pct).toFixed(1):'—'}%</b></span>
      <span><small>ตัวอย่างที่ใช้</small><b>${finite(observations.valid_samples)?Math.round(Number(observations.valid_samples)):'—'}</b></span>
      <span><small>ต่อเนื่องสูงสุด</small><b>${finite(observations.longest_valid_run_seconds)?fmtDur(Number(observations.longest_valid_run_seconds)):'—'}</b></span>
      <span><small>Regularity</small><b>${finite(observations.regularity_factor)?Number(observations.regularity_factor).toFixed(3):'—'}</b></span>
      <span><small>ตัด Movement/สัญญาณอ่อน</small><b>${finite(observations.excluded_motion_or_weak_signal_minutes)?Number(observations.excluded_motion_or_weak_signal_minutes).toFixed(1):'—'} นาที</b></span>
      <span><small>ตัด Invalid/Held</small><b>${finite(observations.excluded_invalid_or_held_minutes)?Number(observations.excluded_invalid_or_held_minutes).toFixed(1):'—'} นาที</b></span>
      <span><small>Version</small><b>${historyEscape(summary.version||'—')}</b></span>
    </div></details>`:'';
  return `<section class="restore-summary-card respiratory-wellness-card">
    <div class="restore-summary-head"><div><span>RESTING BREATHING</span><h3>การหายใจระหว่างพัก</h3><small>${adminView?'วิเคราะห์จาก RR ที่ผ่านคุณภาพสัญญาณ BCG':'ดูจากจังหวะและความสม่ำเสมอตลอดช่วงพัก'}</small></div><strong class="restore-status ${respiratoryWellnessTone(status.key)}">${historyEscape(statusLabel)}</strong></div>
    <p class="restore-status-meaning">${historyEscape(interpretation)}</p>
    <div class="restore-summary-grid"><div class="restore-driver-group respiratory-observation"><b>สิ่งที่สังเกตได้</b><ul>${observationList}</ul></div><div class="restore-recommendation"><b>ลองทำครั้งถัดไป</b><p>${historyEscape(adminView&&recommendation.primary?recommendation.primary:'พักตามปกติและให้ ZEEP เรียนรู้รูปแบบของคุณเพิ่มอีกครั้ง')}</p></div></div>
    <div class="restore-summary-meta"><span><b>ช่วงวัย</b>${historyEscape(ageText)}</span><span><b>รูปแบบประจำของคุณ</b>${historyEscape(baselineText)}</span><span><b>${adminView?'ความมั่นใจ':'ความชัดเจนของข้อมูล'}</b>${historyEscape(confidenceLabel)}</span></div>
    <p class="respiratory-age-guidance"><b>คำแนะนำตามช่วงอายุ</b> · ${historyEscape(ageGuidance)}</p>
    ${adminDetails}
    <div class="restore-claim-note">${adminView?'ประเมินจาก BCG · ไม่วัด PFT, SpO₂ หรือ sleep apnea และไม่เปลี่ยน Sleep/Recovery Score':'ข้อมูลนี้ช่วยดูแนวโน้มระหว่างพัก ไม่ใช่การตรวจสมรรถภาพปอด ออกซิเจนในเลือด หรือการวินิจฉัยโรค'}</div>
  </section>`;
}

function renderSessionOverview(report,hasRestoreSummary=false){
  if(!report?.available)return '';
  const adminView=currentPrincipal?.role==='admin';
  const sleep=report.sleep||{},quality=report.quality||{};
  const data=report.data_quality||{};
  const presentation=reportPresentationMode(report);
  const findingIcon={critical:'!',poor:'↓',fair:'–',good:'✓',excellent:'★',unavailable:'?'};
  const allFindings=Array.isArray(report.findings)?report.findings:[];
  const findingRow=item=>{
    if(adminView)return `<div class="disturbance-item ${item.severity||'unavailable'}"><i>${findingIcon[item.severity]||'·'}</i><div><b>${historyEscape(item.title||'ข้อมูลประกอบ')}</b><small>${historyEscape(item.detail||'')}</small></div><span>${historyEscape(item.action||'')}</span></div>`;
    const finding=userReportFinding(item);
    return `<div class="disturbance-item ${finding.severity}"><i>${findingIcon[finding.severity]||'·'}</i><div><b>${historyEscape(finding.metric)} · ${historyEscape(finding.label)}</b><small>${historyEscape(finding.detail)}</small></div><span>${historyEscape(finding.action)}</span></div>`;
  };
  const requiredFindings=allFindings.filter(item=>
    ['required','sensor_check','safety_review'].includes(item.decision)
    ||['critical','poor'].includes(item.severity)
    ||(item.severity==='unavailable'&&item.blocks_overall!==false));
  const optimiseFindings=allFindings.filter(item=>
    ['optimise','investigate','advisory'].includes(item.decision)
    ||item.severity==='fair'
    ||(item.severity==='unavailable'&&item.blocks_overall===false));
  const maintainFindings=allFindings.filter(item=>item.decision==='maintain'||['good','excellent'].includes(item.severity));
  const findingTier=(title,items)=>items.length?`<div class="disturbance-tier"><h5>${title}</h5>${items.map(findingRow).join('')}</div>`:'';
  const tierTitles=adminView?[
    'ต้องตรวจสอบ · Safety / ต่ำกว่าเกณฑ์ / Sensor ไม่พร้อม',
    'ผ่านขั้นต่ำ · ปรับเพิ่มได้',
    'ดี / ยอดเยี่ยม · รักษาค่า',
  ]:[
    'ควรดูแลก่อน',
    'ปรับเพิ่มได้',
    'ทำได้ดี',
  ];
  const findings=[
    findingTier(tierTitles[0],requiredFindings),
    findingTier(tierTitles[1],optimiseFindings),
    findingTier(tierTitles[2],maintainFindings),
  ].join('');
  const environmentAssessment=report.environment_assessment||{};
  const restMode=report.rest_mode||{};
  const profile=reportProfileMarkup(report,presentation);
  const disturbanceTitle=adminView
    ?presentation==='sleep'?'สิ่งที่อาจรบกวนการนอน':'สิ่งที่อาจรบกวนการพัก'
    :'ปัจจัยระหว่างการพัก';
  const environmentStatus=adminView
    ?`คาดหวังพอใช้ขึ้นไป · ${environmentAssessment.mode_label||restMode.label||'ตาม Mode'} · ${environmentAssessment.context_only===false?'':'ไม่กำหนด Sleep State'}`
    :`เทียบกับเกณฑ์ของ ${environmentAssessment.mode_label||restMode.label||'รูปแบบการพักครั้งนี้'}`;
  const metrics=reportOverviewMetrics(report,presentation);
  const scoreConfidence=quality.score_confidence||{};
  const badgeLevel=presentation==='recovery'&&scoreConfidence.level?scoreConfidence.level:(data.level||'low');
  const badgeLabel=adminView
    ?presentation==='recovery'&&scoreConfidence.label?scoreConfidence.label:(data.label||'ข้อมูลจำกัด')
    :userConfidenceLevelLabel(
      presentation==='recovery'&&scoreConfidence.level?scoreConfidence.level:data.level,
    );
  const dataBadge=adminView
    ?`<span class="report-data-badge ${badgeLevel}">${badgeLabel}</span>`:'';
  const protocolBadge=presentation==='recovery'
    ?recoveryProtocolBadge(report,adminView):null;
  const guidance=report.post_session_guidance||{};
  const guidanceHtml=!hasRestoreSummary&&guidance.primary
    ?adminView
      ?`<div class="report-context-note"><b>คำแนะนำหลังออกจาก ZEEP</b> · ${historyEscape(guidance.primary)}${guidance.next_session?` · ${historyEscape(guidance.next_session)}`:''}${guidance.self_check?`<br><b>เช็กความพร้อม</b> · ${historyEscape(guidance.self_check)}`:''}</div>`
      :`<div class="report-context-note"><b>คำแนะนำหลังพัก</b> · ${presentation==='recovery'?'ค่อย ๆ กลับไปทำกิจกรรม และสังเกตว่ารู้สึกสดชื่นขึ้นเพียงใด':'เริ่มวันตามจังหวะที่สบาย และดูความรู้สึกของคุณร่วมกับผลคืนนี้'}</div>`
    :'';
  const headline=presentation==='recovery'
    ?'ภาพรวมการพักตามเป้าหมายที่เลือก'
    :presentation==='sleep'
      ?'ภาพรวมการนอนที่ ZEEP ประเมินได้'
      :'รายละเอียดที่ Sensor บันทึก';
  const footer=adminView
    ?(presentation==='recovery'
      ?'Nap & Refresh ประเมินคุณค่าของการพักและการตอบสนอง ไม่ใช้การหลับเป็นเงื่อนไข'
      :presentation==='sleep'
        ?`ใช้เวลาก่อนเริ่มหลับ ${sleep.sleep_onset_proxy_s==null?'--':fmtDur(sleep.sleep_onset_proxy_s)} · เข้าสู่ W · ตื่น ${sleep.wake_entries ?? sleep.awakenings ?? 0} ครั้ง`
        :'ยังไม่ตีความเป็น Sleep Score หรือ Recovery Score จนกว่าจะยืนยันรูปแบบการพัก')
    :(presentation==='recovery'
      ?'Nap & Refresh นับคุณค่าของการพักทั้งขณะตื่นและหลับ'
      :presentation==='sleep'
        ?`ประเมินเฉพาะการพัก Overnight ครั้งนี้ · ตื่น ${sleep.wake_entries ?? sleep.awakenings ?? 0} ครั้ง`
        :'ยังไม่สรุปเป็น Overnight หรือ Nap & Refresh');
  const version=adminView&&report.version?` · ${historyEscape(report.version)}`:'';
  const respiratoryHtml=renderRespiratoryWellness(report,adminView);
  const overview=`<section class="session-report-overview mode-${presentation}">
    <div class="session-report-head"><div><div class="sleep-quality-eyebrow">${presentation==='recovery'?'NAP & REFRESH SUMMARY':presentation==='sleep'?'OVERNIGHT SLEEP SUMMARY':'SESSION DETAIL'}${version}</div><h3>${headline}</h3></div><div class="report-badge-group">${dataBadge}${protocolBadge?`<span class="report-protocol-badge ${protocolBadge.tone}">${protocolBadge.label}</span>`:''}</div></div>
    <div class="session-key-metrics">${metrics}</div>
    <div class="session-report-body">
      ${profile}
      <div class="disturbance-summary"><div class="report-subhead"><span>${disturbanceTitle}</span><small>${environmentStatus}</small></div><div class="disturbance-list">${findings||'<div class="mini">ยังไม่มีปัจจัยที่ต้องดูแลเป็นพิเศษ</div>'}</div></div>
    </div>
    ${respiratoryHtml}
    ${guidanceHtml}
    <div class="report-context-note">${footer}</div>
  </section>`;
  return adminView
    ?overview
    :`<details class="report-details user-result-details"><summary>ดูรายละเอียดการพัก</summary>${overview}</details>`;
}

function renderReport(rec){
  const root = document.getElementById('sessionDetail');
  const adminView=currentPrincipal?.role==='admin';
  const presentation=reportPresentationMode(rec.session_report||rec);
  const reportTitle=presentation==='recovery'
    ?'ผล Nap & Refresh'
    :presentation==='sleep'?'ผล Overnight Recovery':adminView?'ผล Session · รอยืนยันรูปแบบ':'ผลการพักครั้งนี้';
  const timelineTitle=presentation==='recovery'
    ?adminView?'ลำดับการพัก · Sleep State เป็นข้อมูลประกอบ':'ลำดับการพัก'
    :presentation==='sleep'?'ลำดับสถานะการนอน':adminView?'ลำดับข้อมูลที่ Sensor บันทึก':'ลำดับการพัก';
  const timelineEmpty=adminView
    ?presentation==='recovery'
      ?'ยังไม่มีข้อมูลยืนยันรูปแบบการพัก'
      :presentation==='sleep'?'ยังไม่มีข้อมูลสถานะการนอน':'ยังไม่พบข้อมูลที่ยืนยันได้'
    :rec.ended_at_utc
      ?presentation==='sleep'?'ไม่มีลำดับการนอนสำหรับครั้งนี้':'ไม่มีลำดับการพักสำหรับครั้งนี้'
      :presentation==='sleep'?'กำลังเตรียมลำดับการนอน':'กำลังเตรียมลำดับการพัก';
  const su = rec.summary || {};
  const bed = su.bed_status_counts || {};
  const bedTotal = Object.values(bed).reduce((a,b)=>a+b, 0);
  const bedTxt = bedTotal
    ? Object.entries(bed).map(([k,v])=>`${sleepBedStatusLabel(k)} ${Math.round(v*100/bedTotal)}%`).join(' · ')
    : 'ไม่มีข้อมูลจาก BCG';
  const cnt = rec.counters || {};
  const cntTxt = [['door','ประตู'],['pulse','Aroma/ไอน้ำ'],['music','เปิดเพลง'],['output','สวิตช์']]
    .filter(([k])=>cnt[k]).map(([k,l])=>`${l} ${cnt[k]} ครั้ง`).join(' · ') || 'ไม่มีการสั่งงาน';
  const hasChart = (rec.samples || []).length > 1;
  const confidenceTh={low:'ต่ำ',medium:'ปานกลาง',high:'สูง'};
  const averageTemperature=timelineMetricAverager(rec.samples,'temp');
  const averageHumidity=timelineMetricAverager(rec.samples,'hum');
  const averageCo2=timelineMetricAverager(rec.samples,'co2');
  const averageSound=timelineMetricAverager(rec.samples,'dba');
  const averageLight=timelineMetricAverager(rec.samples,'lux');
  const averageHeartRate=timelineMetricAverager(rec.samples,'hr');
  const averageRespiration=timelineMetricAverager(rec.samples,'rr');
  const sleepTimeline=(rec.sleep_timeline||[]).map(period=>{
    const start=new Date(period.start_time),end=new Date(period.end_time),m=period.metrics||{},prob=period.probabilities||{};
    if(period.decision_kind==='terminal_wake_boundary'){
      const time=start.toLocaleTimeString('th-TH',{hour:'2-digit',minute:'2-digit',second:'2-digit'});
      const source=period.confirmed_by==='confirmed_terminal_bed_exit'?'ก่อนออกจาก ZEEP':'ก่อนจบ Session';
      if(!adminView){
        return '';
      }
      return `<div class="sleep-period terminal-wake-period"><div>${time}<div class="mini">เหตุการณ์เปลี่ยนสถานะ</div></div><div class="stage">W · ตื่น</div><div>${source}<div class="mini">ไม่นับเวลา/สัดส่วน Sleep Stage</div></div><div class="reason"><div class="sleep-period-note">${period.reason||'สิ้นสุดลำดับการนอนก่อนจบ Session'} · เป็น Operational marker ไม่ใช่ผล AASM/PSG</div></div></div>`;
    }
    const temperatureAvg=averageTemperature(period.start_time,period.end_time);
    const humidityAvg=averageHumidity(period.start_time,period.end_time);
    const co2Avg=averageCo2(period.start_time,period.end_time);
    const soundAvg=averageSound(period.start_time,period.end_time);
    const lightAvg=averageLight(period.start_time,period.end_time);
    const heartAvg=m.mean_hr==null?averageHeartRate(period.start_time,period.end_time):Number(m.mean_hr);
    const respirationAvg=m.mean_rr==null?averageRespiration(period.start_time,period.end_time):Number(m.mean_rr);
    const time=`${start.toLocaleTimeString('th-TH',{hour:'2-digit',minute:'2-digit',second:'2-digit'})}–${end.toLocaleTimeString('th-TH',{hour:'2-digit',minute:'2-digit',second:'2-digit'})}`;
    const interval=Number(period.sample_interval_s||rec.sample_interval_s||5);
    const epoch=period.round_count?`${period.round_count} รอบ × ${interval} วินาที`:period.analysis_window_samples?`วิเคราะห์จาก ${period.analysis_window_samples} ชุด`:'ข้อมูลรูปแบบเดิม';
    const sensorTiles=[
      sleepSensorTile('temp','°C','อุณหภูมิเฉลี่ย',temperatureAvg==null?'--':`${temperatureAvg.toFixed(1)} °C`),
      sleepSensorTile('humidity','%RH','ความชื้นเฉลี่ย',humidityAvg==null?'--':`${humidityAvg.toFixed(1)} %RH`),
      sleepSensorTile('co2','CO₂','CO₂ เฉลี่ย',co2Avg==null?'--':`${Math.round(co2Avg)} ppm`),
      sleepSensorTile('sound','dB','เสียงเฉลี่ย',soundAvg==null?'--':`${soundAvg.toFixed(1)} dBA`),
      sleepSensorTile('light','lx','แสงเฉลี่ย',lightAvg==null?'--':`${lightAvg.toFixed(1)} lux`),
      sleepSensorTile('heart','HR','ชีพจรเฉลี่ย',heartAvg==null||!Number.isFinite(heartAvg)?'--':`${heartAvg.toFixed(1)} bpm`),
      sleepSensorTile('respiration','RR','หายใจเฉลี่ย',respirationAvg==null||!Number.isFinite(respirationAvg)?'--':`${respirationAvg.toFixed(1)} ครั้ง/นาที`),
      sleepSensorTile('movement','MOV','เคลื่อนไหว',m.movement_ratio==null?'--':`${Math.round(Number(m.movement_ratio)*100)}%`),
      sleepSensorTile('bed','BED','สถานะเตียง',period.state==='off_bed'?'ไม่มีผู้ใช้งานบนเตียง':sleepBedStatusLabel(m.bed_status)),
    ].join('');
    if(period.decision_kind==='operational_status'){
      const coverage=period.coverage||{};
      const coverageText=coverage.sensor_rows
        ? `HR/RR ใช้ได้ ${coverage.valid_hr_rr_pairs||0}/${coverage.sensor_rows} รอบ`
        : 'ใช้ผล Operational ที่บันทึกไว้กับ Session';
      const operationLabel='ยืนยัน OFF BED';
      const scoreLabel='แยกออกจาก Sleep State และคะแนน';
      if(!adminView){
        return `<div class="sleep-period user-sleep-period"><div>${time}<div class="mini">${fmtDur(period.duration_s)}</div></div><div class="stage">ออกจากเตียง</div><div class="user-period-summary">ช่วงนี้แยกจากเวลาพัก</div></div>`;
      }
      return `<div class="sleep-period terminal-occupancy-period"><div>${time}<div class="mini">${fmtDur(period.duration_s)} · ${operationLabel}</div></div><div class="stage">${period.label||'OFF BED · ไม่มีผู้ใช้งานบนเตียง'}</div><div>${coverageText}<div class="mini">${scoreLabel}</div></div><div class="reason"><div class="sleep-period-env">${sensorTiles}</div><div class="sleep-period-note">${period.reason||'แยกสถานะการใชงานออกจากผล Sleep State'}</div></div></div>`;
    }
    if(!adminView){
      const heldCopy=period.held_previous_state
        ?'แสดงต่อเนื่องจากช่วงก่อนหน้า'
        :'ประเมินจากแนวโน้มระหว่างการพัก';
      return `<div class="sleep-period user-sleep-period"><div>${time}<div class="mini">${fmtDur(period.duration_s)}</div></div><div class="stage">${userSleepStageLabel(period.state)}</div><div class="user-period-summary">${heldCopy}</div></div>`;
    }
    const holdMeta=period.held_previous_state
      ? `<div class="mini">คง State ก่อนหน้า ${period.continuity_hold_rounds||0} รอบ${period.provisional_rounds?` · provisional ${period.provisional_rounds} รอบ`:''} · ผู้ท้าชิงยังไม่ถูกนับเป็น State ใหม่</div>`
      : '';
    return `<div class="sleep-period"><div>${time}<div class="mini">${fmtDur(period.duration_s)} · ${epoch}</div></div><div class="stage">${SLEEP_TH[period.state]?.label||period.state.toUpperCase()}${period.provisional?' · provisional':''}</div><div>มั่นใจ ${confidenceTh[period.confidence]||'ไม่ระบุ'}<div class="mini">P ${Math.round((prob[period.state]||0)*100)}%</div>${holdMeta}</div><div class="reason"><div class="sleep-period-env">${sensorTiles}</div><div class="sleep-period-note">${sleepReasonExplanation(period.reason)}</div></div></div>`;
  }).join('');
  const terminalOccupancy=(rec.terminal_occupancy_timeline||[]).map(period=>{
    const registeredMeta=TERMINAL_OCCUPANCY_META[period.state];
    const meta=registeredMeta||{label:period.label||period.state,code:'—'};
    const start=new Date(period.start_time),end=new Date(period.end_time);
    const time=`${start.toLocaleTimeString('th-TH',{hour:'2-digit',minute:'2-digit',second:'2-digit'})}–${end.toLocaleTimeString('th-TH',{hour:'2-digit',minute:'2-digit',second:'2-digit'})}`;
    if(!adminView)return '';
    return `<div class="sleep-period terminal-occupancy-period"><div>${time}<div class="mini">${fmtDur(period.duration_s)} · Occupancy</div></div><div class="stage">${meta.code} · ${meta.label}</div><div>HR — · RR —<div class="mini">ไม่นับเป็น Sleep Stage</div></div><div class="reason"><div class="sleep-period-note">${period.reason||'แยกสถานะผู้ใช้งานออกจากผลการนอน'}</div></div></div>`;
  }).join('');
  const sessionEnded=rec.ended_at_utc
    ?(adminView
      ? `<div class="sleep-period terminal-occupancy-period"><div>${new Date(rec.ended_at_utc).toLocaleTimeString('th-TH',{hour:'2-digit',minute:'2-digit',second:'2-digit'})}<div class="mini">เหตุการณ์สุดท้าย</div></div><div class="stage">END · จบ Session</div><div>${rec.end_reason==='logout'?'ผู้ใช้กดจบ':'ผู้ดูแล/ระบบบันทึกการจบ'}</div><div class="reason"><div class="sleep-period-note">${terminalOccupancy?'Session จบหลังลำดับ Wake → ออกจาก ZEEP':'Session จบหลังบันทึก Terminal Wake boundary'}</div></div></div>`
      :`<div class="sleep-period user-sleep-period"><div>${new Date(rec.ended_at_utc).toLocaleTimeString('th-TH',{hour:'2-digit',minute:'2-digit',second:'2-digit'})}<div class="mini">สิ้นสุดการใช้งาน</div></div><div class="stage">สิ้นสุดการพัก</div><div class="user-period-summary">บันทึกผลเรียบร้อย</div></div>`):'';
  const resultSummaryHtml=renderRestoreSummary(
    rec,presentation,Boolean(rec.ended_at_utc),
  );
  const timelineCount=`${rec.sleep_timeline?.length||0} ช่วง`;
  const decisionRounds=Number(rec.sleep_timeline_rounds||0)+Number(rec.sleep_status_timeline_rounds||0);
  const timelineMeta=adminView
    ?`${timelineCount} · จาก ${decisionRounds||rec.sleep_timeline?.length||0} รอบข้อมูล${rec.sleep_status_timeline_rounds?` · OFF BED ${rec.sleep_status_timeline_rounds} รอบ`:''}`
    :timelineCount;
  const primaryTimeline=adminView?sleepTimeline:`${sleepTimeline}${sessionEnded}`;
  const timelineDetails=adminView||primaryTimeline
    ?`<details class="report-details"><summary>${timelineTitle} · ${timelineMeta}</summary>${primaryTimeline?`<div class="sleep-timeline">${primaryTimeline}</div>`:`<div class="mini" style="padding:0 12px 12px">${timelineEmpty}</div>`}</details>`
    :'';
  const operationalNotes=adminView
    ?`<div class="mini">สถานะเตียง: ${bedTxt}</div><div class="mini">การสั่งงานระหว่าง Session: ${cntTxt}</div>`
    :'';
  const timeAccounting=classificationAccountingMarkup(
    rec.session_report,adminView,presentation,
  );
  const adminDiagnostics=adminView?`<details class="report-details admin-report-details">
    <summary>ข้อมูล Sensor, Timeline และรายการสำหรับพัฒนา</summary>
    <div class="admin-report-details-body">
      <div class="mini">${healthReferenceInline(rec)}</div>
      ${timeAccounting}
      <div class="report-grid">
        ${statBlock('อุณหภูมิเฉลี่ย', su.temperature_c, ' °C')}
        ${statBlock('ความชื้นเฉลี่ย', su.humidity_rh, ' %RH')}
        ${statBlock('เสียงเฉลี่ย', su.sound_dba_est, ' dBA')}
        ${statBlock('แสงเฉลี่ย', su.lux, ' lx')}
        ${statBlock('HR (Heart Rate) เฉลี่ย', su.heart_rate_bpm, ' ครั้ง/นาที (BPM)')}
        ${statBlock('RR (Respiratory Rate) เฉลี่ย', su.respiration_rate, ' ครั้ง/นาที')}
      </div>
      ${operationalNotes}
      ${timelineDetails}
      ${terminalOccupancy||sessionEnded?`<details class="report-details"><summary>ลำดับจบ Session · Occupancy แยกจาก Sleep State</summary><div class="sleep-timeline">${terminalOccupancy}${sessionEnded}</div></details>`:''}
      ${hasChart?'<canvas id="histCanvas"></canvas><div class="legend-row"><span><i class="legend-dot" style="background:#19e3ff"></i>อุณหภูมิ</span><span><i class="legend-dot" style="background:#ffb02e"></i>ชีพจร</span></div>':''}
      <div class="mini">ค่าชีพจรและการหายใจเป็นค่าประเมินจาก BCG · ใช้ตรวจสอบระบบ ไม่ใช่การวินิจฉัย</div>
    </div>
  </details>`:'';
  root.innerHTML = `
    <div class="report-result-head">
      <div class="section-title report-mode-title mode-${presentation}">${reportTitle}</div>
      <div class="report-result-meta">${adminView?`${historyEscape(identityLabel(rec,''))} · `:''}${fmtDateTh(rec.started_at_utc)} → ${fmtDateTh(rec.ended_at_utc)} · ${fmtDur(rec.duration_s)}</div>
    </div>
    ${resultSummaryHtml}
    ${renderSessionOverview(rec.session_report,Boolean(resultSummaryHtml))}
    ${!adminView?timeAccounting:''}
    ${!adminView?timelineDetails:''}
    ${adminDiagnostics}
  `;
  const diagnostics=root.querySelector('.admin-report-details');
  if(hasChart&&diagnostics){
    diagnostics.addEventListener('toggle',()=>{
      if(diagnostics.open)requestAnimationFrame(()=>drawHistory(rec.samples));
    });
  }
}

function drawHistory(samples){
  const c = document.getElementById('histCanvas');
  if (!c) return;
  const dpr = window.devicePixelRatio || 1;
  const w = c.clientWidth || c.parentElement.clientWidth, h = 170;
  c.width = Math.round(w*dpr); c.height = Math.round(h*dpr);
  const x = c.getContext('2d');
  x.setTransform(dpr,0,0,dpr,0,0); x.clearRect(0,0,w,h);
  x.strokeStyle = '#0a2c40'; x.lineWidth = 1;
  for (let gy = h/4; gy < h; gy += h/4){ x.beginPath(); x.moveTo(0,gy); x.lineTo(w,gy); x.stroke(); }
  const plot = (key, color)=>{
    const vals = samples.map(s=>s[key]);
    const nums = vals.filter(v=>typeof v === 'number');
    if (nums.length < 2) return;
    let mn = Math.min(...nums), mx = Math.max(...nums);
    if (mx === mn) mx = mn + 1;
    x.strokeStyle = color; x.lineWidth = 2; x.lineJoin = 'round';
    x.beginPath(); let started = false;
    vals.forEach((v,i)=>{
      if (typeof v !== 'number'){ started = false; return; }
      const px = i * (w/(vals.length-1));
      const py = (h-10) - ((v-mn)/(mx-mn)) * (h-20);
      if (!started){ x.moveTo(px,py); started = true; } else x.lineTo(px,py);
    });
    x.stroke();
  };
  plot('temp', '#19e3ff');
  plot('hr', '#ffb02e');
}

async function deleteUser(btn){
  const user = document.getElementById('historyUser').value;
  if (!user){ toast('ยังไม่ได้เลือกผู้ใช้', 'error'); return; }
  if (sessionState.active && sessionState.username === user){
    toast('ผู้ใช้นี้กำลังอยู่ใน session — ออกจากระบบก่อนลบ', 'error'); return;
  }
  if (!await confirmAction({title:'ลบข้อมูลผู้ใช้',message:`Profile และประวัติการใช้งานทั้งหมดของ “${user}” จะถูกลบถาวรและไม่สามารถย้อนกลับได้`,confirmText:'ลบถาวร',tone:'danger',icon:'×'})) return;
  await withBusy(btn, async ()=>{
    const opt = {method:'DELETE', headers:authenticatedHeaders({})};
    let r;
    try { r = await fetch(`/api/users/${encodeURIComponent(user)}`, opt); }
    catch { toast('เชื่อมต่อ server ไม่ได้', 'error'); return; }
    if (!r.ok){
      let msg = ''; try { msg = (await r.json()).detail || ''; } catch {}
      toast(msg || `HTTP ${r.status}`, 'error'); return;
    }
    const d = await r.json();
    toast(`ลบข้อมูลของ ${d.username} แล้ว (${d.sessions_removed} sessions)`, 'ok', 3600);
    document.getElementById('sessionList').innerHTML = '<div class="mini">เลือกผู้ใช้แล้วกด "โหลดประวัติ"</div>';
    document.getElementById('sessionDetail').innerHTML = '';
    loadUsers();
  });
}
