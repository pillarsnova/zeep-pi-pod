/* Shared result experience for Sessions and the end-of-session screen. */
function resultNumber(value, maximum=100){
  if(typeof value!=='number'&&typeof value!=='string')return null;
  if(String(value).trim()==='')return null;
  const number=Number(value);
  return Number.isFinite(number)&&number>=0&&number<=maximum?number:null;
}

function resultIcon(name){
  const paths={
    check:'<path d="m5 12 4 4L19 6"/>',
    adjust:'<path d="M4 7h16M4 17h16M9 4v6m6 4v6"/>',
    arrow:'<path d="M5 12h14m-5-5 5 5-5 5"/>',
    moon:'<path d="M20 15.5A8 8 0 0 1 9 4.5 8.5 8.5 0 1 0 20 15.5Z"/>',
    sun:'<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1 1m12 12 1 1M5 19l1-1M18 6l1-1"/>',
    chart:'<path d="M4 19h16M7 15v-3m5 3V8m5 7V5"/>',
  };
  return `<svg class="result-icon" viewBox="0 0 24 24" aria-hidden="true">${paths[name]||paths.chart}</svg>`;
}

function resultEmotion(tone, available, safety, limited=false){
  if(safety)return {symbol:'!', label:'ควรให้ทีมตรวจสอบ',tone:'attention'};
  if(!available)return {symbol:'—',label:'ยังไม่สรุประดับผลการพัก',tone:'neutral'};
  if(limited)return {symbol:'◌',label:'ข้อมูลประกอบมีจำกัด',tone:'neutral'};
  if(['very_good','good'].includes(tone))return {symbol:'☺',label:'ผลการพักอยู่ในระดับดี',tone:'positive'};
  return {symbol:'🌿',label:'ยังเติมช่วงพักที่สบายได้',tone:'gentle'};
}

const RESULT_COMPONENTS=Object.freeze({
  sleep_opportunity:{label:'เวลาและการเริ่มหลับ',icon:'moon',modes:['sleep']},
  sleep_stability:{label:'หลับต่อเนื่อง',icon:'check',modes:['sleep']},
  restorative_architecture:{label:'รูปแบบการนอน',icon:'chart',modes:['sleep']},
  cycle_expression:{label:'รอบการนอน',icon:'moon',modes:['sleep']},
  goal_duration:{label:'เวลาพักตามเป้าหมาย',icon:'sun',modes:['recovery']},
  physiological_response:{label:'ชีพจรและการหายใจ',icon:'chart',modes:['sleep','recovery']},
  rest_continuity:{label:'พักต่อเนื่อง',icon:'check',modes:['recovery']},
  environment_support:{label:'บรรยากาศที่ช่วยพัก',icon:'sun',modes:['sleep','recovery']},
});

function resultComponentRows(quality,presentation){
  const points=quality.component_points||{},maxima=quality.component_max_points||{};
  const imputed=quality.imputed_component_points||{};
  const order=Array.isArray(quality.component_order)?quality.component_order:Object.keys(points);
  return [...new Set(order)].flatMap(key=>{
    const meta=RESULT_COMPONENTS[key];
    if(!meta?.modes?.includes(presentation)||Object.prototype.hasOwnProperty.call(imputed,key))return [];
    const maximum=resultNumber(maxima[key]);
    const earned=resultNumber(points[key],maximum??0);
    if(maximum===null||maximum<=0||earned===null)return [];
    return [{...meta,key,earned,maximum,percent:100*earned/maximum}];
  });
}

function resultComponentsMarkup(quality,presentation,available){
  if(!available)return '';
  const rows=resultComponentRows(quality,presentation);
  if(!rows.length)return '';
  return `<section class="result-components" aria-label="องค์ประกอบคะแนนการพัก">
    <div class="result-section-title">${resultIcon('chart')}<div><h4>อะไรช่วยให้พักได้ดี</h4><p>คะแนนย่อยจากการพักครั้งนี้</p></div></div>
    <div class="result-bars">${rows.map(row=>`<div class="result-bar-row">
      <div><span>${row.label}</span><small>${row.earned} / ${row.maximum}</small></div>
      <meter min="0" max="${row.maximum}" value="${row.earned}" aria-label="${row.label}: ${row.earned} จาก ${row.maximum} คะแนน">${row.earned} / ${row.maximum}</meter>
    </div>`).join('')}</div>
    <small class="result-chart-note">ความยาวแถบเทียบคะแนนเต็มของแต่ละด้าน · ไม่ใช่เปอร์เซ็นต์การฟื้นตัวของร่างกาย</small>
  </section>`;
}

function renderRestoreSummary(source,presentation,ended=true){
  const payload=source?.data||source||{};
  const report=payload.session_report||payload;
  const summary=restoreSummarySource(source)||{};
  const quality=payload.sleep_quality||report.quality||{};
  const adminView=currentPrincipal?.role==='admin';
  const safetyReviewRequired=reportSafetyReviewRequired(source);
  const scoreAvailable=Boolean(
    ended&&presentation!=='unknown'&&quality.available===true&&resultNumber(quality.score)!==null,
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
    return `<div class="restore-driver-group ${tone}"><b>${resultIcon(tone==='positive'?'check':'adjust')}${title}</b><ul>${rows.map(row=>`<li>${row}</li>`).join('')}</ul></div>`;
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
  const tip=ended&&presentation!=='unknown'?(summary.recommendation||{}):{};
  const tipTitle=restorePlainText(tip,['title']);
  const tipWhen=restorePlainText(tip,['when_label']);
  const tipReason=restorePlainText(tip,['reason']);
  const subjective=summary.subjective_outcome||{};
  const subjectiveRows=[];
  if(subjective.status==='measured'){
    const freshnessRaw=subjective.freshness_delta;
    const freshnessValid=['number','string'].includes(typeof freshnessRaw)
      &&String(freshnessRaw).trim()!==''&&Number.isFinite(Number(freshnessRaw))&&Math.abs(Number(freshnessRaw))<=10;
    const freshness=freshnessValid?Number(freshnessRaw):null;
    if(freshness!==null){
      const amount=Number.isInteger(Math.abs(freshness))
        ?String(Math.abs(freshness)):Math.abs(freshness).toFixed(1);
      subjectiveRows.push(freshness>0
        ?`สดชื่นขึ้น ${amount} ระดับ`
        :freshness<0?`ความสดชื่นลดลง ${amount} ระดับ`:'ความสดชื่นใกล้เคียงก่อนพัก');
    }
    const readiness=resultNumber(subjective.activity_readiness,10);
    if(readiness!==null){
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
  const scoreValue=scoreAvailable?wellnessScoreValue(quality.score):null;
  const scoreTone=scoreAvailable
    ?sleepQualityTone(quality,safetyReviewRequired):'unavailable';
  const emotion=resultEmotion(scoreTone,scoreAvailable,safetyReviewRequired,
    statusKey==='limited_evidence'||quality.limited_evidence_neutral_score===true);
  const components=resultComponentsMarkup(quality,presentation,scoreAvailable);
  const safetyBanner=safetyReviewRequired
    ?`<div class="result-safety-review"><b>ควรให้ทีมตรวจสอบ</b><span>มีค่าสภาพแวดล้อมบางช่วงแตะเกณฑ์ความปลอดภัย ${scoreAvailable?'คะแนนยังแสดงได้ แต่ควรตรวจรายละเอียด':'ควรตรวจรายละเอียด'}ก่อนใช้งานครั้งถัดไป</span></div>`
    :'';
  return `<section class="restore-summary-card result-summary-card result-app mode-${presentation} quality-${scoreTone}" style="--quality-score:${scoreValue??0}">
    <div class="result-app-header"><span>${resultIcon(presentation==='sleep'?'moon':'sun')}${historyEscape(scopeLabel)}</span><small>YOUR REST · สรุปการพัก</small></div>
    ${safetyBanner}
    <div class="result-app-overview">
    <div class="result-summary-primary">
      <div class="sleep-quality-ring" aria-label="${historyEscape(scoreTitle)} ${scoreAvailable?wellnessScoreDisplay(quality.score):'ยังไม่มีคะแนน'}"><span class="sleep-quality-value"><strong>${scoreAvailable?wellnessScoreDisplay(quality.score):'—'}</strong><small>/100</small></span></div>
      <div class="result-summary-copy">
        <span class="sleep-quality-eyebrow">${historyEscape(scoreTitle)}</span>
        <h3><span class="result-emotion ${emotion.tone}" role="img" aria-label="สัญลักษณ์ระดับผลการพัก: ${emotion.label}">${emotion.symbol}</span>${historyEscape(statusLabel)}</h3>
        ${statusMeaning?`<p>${historyEscape(statusMeaning)}</p>`:''}
        <small>${presentation==='recovery'?'การพักมีคุณค่า แม้ไม่หลับ':presentation==='sleep'?'ภาพรวมจากการนอนครั้งนี้':'ข้อมูลที่บันทึกได้ในครั้งนี้'}</small>
      </div>
    </div>
    ${components}
    </div>
    <div class="result-summary-actions"><div class="restore-drivers">${driverMarkup}</div><div class="restore-recommendation"><span class="result-next-icon">${resultIcon('arrow')}</span><div><b>คำแนะนำสำหรับคุณ</b>${tipWhen?`<small class="result-tip-when">${historyEscape(tipWhen)} · อ้างอิงการพักครั้งนี้</small>`:''}${tipTitle?`<h4>${historyEscape(tipTitle)}</h4>`:''}<p>${recommendation?historyEscape(recommendation):'ใช้งานตามปกติและสังเกตความรู้สึกหลังพัก'}</p>${tipReason?`<details class="result-tip-reason"><summary>เหตุผลที่แนะนำ</summary><p>${historyEscape(tipReason)}</p></details>`:''}</div></div></div>
    ${subjectiveMarkup}
    <div class="restore-summary-meta"><span><b>รูปแบบของคุณ</b>${historyEscape(baselineText)}</span><span><b>${adminView?'ความมั่นใจ':'ความชัดเจนของข้อมูล'}</b>${historyEscape(confidenceDisplay)}</span></div>
    ${adminView?adminResultEvidence(report,quality,summary,presentation):''}
    <div class="restore-claim-note">${adminView?'ผลสรุปสำหรับตรวจสอบระบบและพัฒนาต่อ':'ผล Wellness เฉพาะการพักครั้งนี้ · ดูร่วมกับความรู้สึกของคุณ · ไม่ใช่การวินิจฉัย'}</div>
  </section>`;
}
