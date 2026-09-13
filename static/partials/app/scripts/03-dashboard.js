function compactMetric(value,unit='',digits=0){
  const number=Number(value);
  return value!==null&&value!==undefined&&value!==''&&Number.isFinite(number)?`${number.toFixed(digits)}${unit?` ${unit}`:''}`:`--${unit?` ${unit}`:''}`;
}
function setDashboardSensor(cardId,valueId,value,unit,device,digits=0){
  const card=document.getElementById(cardId),valueEl=document.getElementById(valueId);
  if(!card||!valueEl)return;
  valueEl.textContent=compactMetric(value,unit,digits);
  const live=device?.status==='live';
  card.classList.toggle('live',live);card.classList.toggle('offline',!live);
  const fieldNames={dashSensorTemp:'อุณหภูมิ',dashSensorHumidity:'ความชื้น',dashSensorLight:'แสง',dashSensorSound:'เสียง',dashSensorCo2:'CO₂',dashSensorPm:'PM2.5',dashSensorVoc:'VOC'};
  card.title=currentPrincipal?.role==='admin'
    ?`${device?.model||'Sensor'} · ${fieldNames[cardId]||'Reading'} · ${device?.status||'no data'}${Number.isFinite(Number(device?.data_age_s))?` · ${Number(device.data_age_s).toFixed(1)}s`:''}`
    :`${fieldNames[cardId]||'ข้อมูล'} · ${live?'ข้อมูลพร้อม':'กำลังรวบรวมข้อมูล'}`;
}

const dashboardAtmosphereLevels=Object.freeze([
  {key:'critical',label:'แนะนำให้ปรับตอนนี้',english:'Needs attention',symbol:'!',description:'มีอย่างน้อยหนึ่งค่าหลุดจากช่วง Wellness ที่กำหนด และปรับให้เหมาะขึ้นได้',principle:'มีอย่างน้อย 1 ใน 7 ค่าอยู่นอกช่วง Wellness ชั้นนอก'},
  {key:'poor',label:'ควรปรับ',english:'Adjust',symbol:'↓',description:'มีบางปัจจัยที่ควรปรับเพื่อให้พักได้สบายขึ้น',principle:'ไม่มีค่าหลุดช่วงชั้นนอก แต่มีอย่างน้อย 1 ค่าที่ควรปรับ'},
  {key:'fair',label:'พอใช้',english:'Fair',symbol:'–',description:'ใช้งานได้ และยังมีบางปัจจัยที่ปรับให้สบายขึ้นได้',principle:'ไม่มีค่าระดับควรปรับ/ต้องดูแล แต่มีอย่างน้อย 1 ค่าอยู่ระดับพอใช้'},
  {key:'good',label:'ดี',english:'Good',symbol:'✓',description:'สภาพแวดล้อมเหมาะสมโดยรวม แต่ยังมีเกณฑ์ที่ปรับได้อีกเล็กน้อย',principle:'เกณฑ์หลักที่พร้อมใช้งานอยู่ระดับดีขึ้นไป; เสียงเป็นข้อมูลเสริม'},
  {key:'excellent',label:'ยอดเยี่ยม',english:'Excellent',symbol:'★',description:'เกณฑ์หลักที่พร้อมใช้งานอยู่ในช่วงเป้าหมายสำหรับการพักผ่อน',principle:'ทุกเกณฑ์หลักอยู่ระดับยอดเยี่ยม; Sensor เสริมที่ขาดจะแสดงแยกโดยไม่บล็อกภาพรวม'},
]);
function dashboardUpperScore(value,thresholds){
  const index=thresholds.findIndex(limit=>value<=limit);
  return index<0?0:4-index;
}
function dashboardRangeScore(value,ranges){
  const index=ranges.findIndex(([minimum,maximum])=>value>=minimum&&value<=maximum);
  return index<0?0:4-index;
}
// The overall atmosphere covers comfort, ambience and air. The worst live
// criterion wins so a healthy reading cannot hide a genuinely bad one.
const dashboardAtmosphereCriteria=Object.freeze([
  {id:'temperature',name:'อุณหภูมิ',deviceKey:'sht3x_dis',source:'SHT3x-DIS',unit:'°C',digits:1,target:'18–27°C',principle:'ประเมิน Thermal comfort จากอุณหภูมิจริงใน ZEEP',bands:'ยอดเยี่ยม 18–27 · ดี 17–28 · พอใช้ 16–29 · ควรปรับ 13–32 · ต้องดูแลเมื่ออยู่นอกช่วง',read:e=>e.temperature_c,score:v=>dashboardRangeScore(v,[[18,27],[17,28],[16,29],[13,32]]),control:'เครื่องปรับอากาศ',action:v=>v>27?'ลดอุณหภูมิที่เลือกหรือเปิดแอร์':v<18?'เพิ่มอุณหภูมิที่เลือกหรือลดความเย็น':'รักษาอุณหภูมิปัจจุบัน'},
  {id:'humidity',name:'ความชื้น',deviceKey:'sht3x_dis',source:'SHT3x-DIS',unit:'%RH',digits:1,target:'40–60%RH',principle:'ป้องกันอากาศแห้งเกินไปหรือความชื้นสะสมและการควบแน่น',bands:'ยอดเยี่ยม 40–60 · ดี 35–65 · พอใช้ 30–70 · ควรปรับ 20–80 · ต้องดูแลเมื่ออยู่นอกช่วง',read:e=>e.humidity_rh,score:v=>dashboardRangeScore(v,[[40,60],[35,65],[30,70],[20,80]]),control:'ไอน้ำ · ระบบระบายอากาศ',action:v=>v>60?'ปิดไอน้ำและเร่งระบายอากาศ':v<40?'เปิดไอน้ำเป็นช่วงและติดตามค่า':'รักษาความชื้นปัจจุบัน'},
  {id:'light',name:'ความสว่าง',deviceKey:'opt3001',source:'OPT3001',unit:'lux',digits:1,target:'≤5 lux',principle:'ประเมินแสงรบกวนในโหมดเตรียมนอนและขณะนอน',bands:'ยอดเยี่ยม ≤5 · ดี ≤10 · พอใช้ ≤30 · ควรปรับ ≤100 · ต้องดูแล >100 lux',read:e=>e.lux,score:v=>dashboardUpperScore(v,[5,10,30,100]),control:'ไฟเพดาน · แสงแดง · ประตู',action:v=>v>5?'ลดหรือปิดไฟ ตรวจแสงรั่วและตำแหน่งประตู':'รักษาระดับแสงปัจจุบัน'},
  {id:'sound',name:'เสียง',deviceKey:'sph0645',source:'SPH0645LM4H-B',unit:'dBA',digits:1,target:'<40 dBA',requiredForOverall:false,principle:'รับค่า sound_dba ที่ Sensor Hub 1 ส่งจาก ESP32 โดยตรง',bands:'ยอดเยี่ยม <40 · ดี 40–45 · พอใช้ >45–50 · ควรปรับ >50–60 · ต้องดูแล >60 dBA',read:e=>e.sound_dba_est,score:v=>v<40?4:v<=45?3:v<=50?2:v<=60?1:0,control:'เสียงบรรยากาศ · พัดลม · คอมเพรสเซอร์',action:v=>v>=40?'ลดเสียงเพลงและตรวจพัดลม คอมเพรสเซอร์ หรือการสั่น':'รักษาระดับเสียงปัจจุบัน'},
  {id:'co2',name:'CO₂',deviceKey:'mhz19c',source:'MH-Z19C',unit:'ppm',digits:0,target:'≤800 ppm',principle:'ใช้ CO₂ เป็นตัวชี้การระบายอากาศ ไม่ใช่ค่าปริมาณออกซิเจน',bands:'ยอดเยี่ยม ≤800 · ดี ≤1,000 · พอใช้ ≤1,150 · ควรปรับ <1,300 · เกณฑ์หยุด ≥1,300 ppm',read:e=>e.co2_ppm,score:v=>v<=800?4:v<=1000?3:v<=1150?2:v<1300?1:0,control:'พัดลมลมเข้า · พัดลมลมออก',action:v=>v>800?'เพิ่มการเติมและระบายอากาศ พร้อมตรวจ Filter อุดตัน':'รักษาการหมุนเวียนอากาศปัจจุบัน'},
  {id:'pm25',name:'PM2.5',deviceKey:'pms7003',source:'PMS7003',unit:'µg/m³',digits:1,target:'≤15 µg/m³',principle:'ตรวจประสิทธิภาพการกรองฝุ่นละเอียดและการรั่วของอากาศ',bands:'ยอดเยี่ยม ≤15 · ดี ≤25 · พอใช้ ≤37.5 · ควรปรับ ≤50 · ต้องดูแล >50 µg/m³',read:e=>e.pm2_5_ug_m3,score:v=>dashboardUpperScore(v,[15,25,37.5,50]),control:'Pre-Filter · HEPA · ซีลประตู',action:v=>v>15?'ตรวจหรือเปลี่ยน Pre/HEPA Filter และตรวจรอยรั่ว':'รักษาระบบกรองอากาศปัจจุบัน'},
  {id:'voc',name:'VOC Index',deviceKey:'sgp40',source:'SGP40',unit:'',digits:0,target:'≤120',principle:'เทียบสารระเหยกับ Adaptive baseline ของ SGP40 ซึ่งปรับตัวใกล้ 100',bands:'ยอดเยี่ยม ≤120 · ดี ≤150 · พอใช้ ≤200 · ควรปรับ ≤300 · ต้องดูแล >300',read:e=>e.voc_index,score:v=>dashboardUpperScore(v,[120,150,200,300]),control:'กลิ่น · พัดลมระบาย · Carbon Filter',action:v=>v>120?'หยุดแหล่งกลิ่นหรือสารระเหย เร่งระบาย และตรวจ Carbon Filter':'รักษาการระบายอากาศปัจจุบัน'},
]);
function assessDashboardAtmosphere(environment={},devices={}){
  const evaluations=dashboardAtmosphereCriteria.map(criterion=>{
    const device=devices[criterion.deviceKey]||{};
    const raw=criterion.read(environment),value=Number(raw);
    const live=device.status==='live'&&raw!==null&&raw!==undefined&&raw!==''&&Number.isFinite(value);
    const requiredForOverall=criterion.requiredForOverall!==false;
    if(!live)return {...criterion,required_for_overall:requiredForOverall,status:'unavailable',deviceStatus:device.status||'no_data',display:'--'};
    const score=criterion.score(value),level=dashboardAtmosphereLevels[score];
    const decision=score<2?'required':score===2?'optimise':'maintain';
    return {...criterion,required_for_overall:requiredForOverall,status:'live',deviceStatus:'live',value,score,level,decision,meets_expected:score>=2,display:`${value.toFixed(criterion.digits)}${criterion.unit?` ${criterion.unit}`:''}`,recommendation:decision==='maintain'?'รักษาการตั้งค่าปัจจุบัน':criterion.action(value)};
  });
  const metrics=evaluations.filter(metric=>metric.status==='live');
  const unavailable=evaluations.filter(metric=>metric.status!=='live');
  const blockingUnavailable=unavailable.filter(metric=>metric.required_for_overall!==false);
  const advisoryUnavailable=unavailable.filter(metric=>metric.required_for_overall===false);
  const blockingMissingActions=blockingUnavailable.map(metric=>({type:'sensor',priority:'required',name:metric.name,current:'ไม่มีข้อมูล Live',target:metric.target,control:metric.source,action:`ตรวจการเชื่อมต่อ ${metric.source} และ freshness ก่อนประเมิน`,blocks_overall:true}));
  const advisoryActions=advisoryUnavailable.map(metric=>({type:'sensor',priority:'advisory',name:metric.name,current:'ไม่มีข้อมูล Live',target:metric.target,control:metric.source,action:`ตรวจการเชื่อมต่อ ${metric.source} โดยภาพรวมยังทำงานต่อ`,blocks_overall:false}));
  if(!metrics.length){
    return {key:'unknown',label:'รอข้อมูล',english:'Waiting',symbol:'?',description:'Sensor ยังไม่พร้อมสำหรับประเมินภาพรวม',reason:'รอข้อมูล Sensor 7 เกณฑ์',metrics,evaluations,actions:[...blockingMissingActions,...advisoryActions],required_actions:blockingMissingActions,advisory_actions:advisoryActions,assessment_quality:'insufficient'};
  }
  const score=Math.min(...metrics.map(metric=>metric.score));
  const level=dashboardAtmosphereLevels[score];
  const requiredActions=metrics.filter(metric=>metric.score<2).sort((a,b)=>a.score-b.score).map(metric=>({type:'condition',priority:'required',name:metric.name,current:metric.display,target:metric.target,control:metric.control,action:metric.recommendation,score:metric.score}));
  const optimisationActions=metrics.filter(metric=>metric.score===2).map(metric=>({type:'condition',priority:'optimise',name:metric.name,current:metric.display,target:metric.target,control:metric.control,action:metric.recommendation,score:metric.score}));
  const actions=[...requiredActions,...blockingMissingActions,...advisoryActions,...optimisationActions];
  // Required Sensor loss blocks a positive claim. SPH0645 is optional for
  // overall atmosphere, so it lowers coverage without hiding valid results.
  if(blockingUnavailable.length&&score>=2){
    return {key:'unknown',label:'รอข้อมูล',english:'Waiting',symbol:'?',description:'ข้อมูลหลักยังไม่ครบ จึงยังยืนยันภาพรวมไม่ได้',reason:`Sensor หลักพร้อม ${metrics.length}/${evaluations.length} เกณฑ์ · ตรวจ ${blockingUnavailable[0].source}`,metrics,evaluations,actions,required_actions:[...requiredActions,...blockingMissingActions],advisory_actions:advisoryActions,optimisation_actions:optimisationActions,meets_expected:false,assessment_quality:'incomplete_required'};
  }
  const limiting=metrics.filter(metric=>metric.score===score);
  const firstRequired=requiredActions[0],firstOptimise=optimisationActions[0];
  return {
    ...level,score,metrics,evaluations,actions,limiting,
    required_actions:[...requiredActions,...blockingMissingActions],advisory_actions:advisoryActions,optimisation_actions:optimisationActions,
    meets_expected:!blockingUnavailable.length&&!requiredActions.length,
    assessment_quality:blockingUnavailable.length?'incomplete_required':advisoryUnavailable.length?'degraded_optional':'complete',
    reason:firstRequired?`แนะนำให้ปรับ ${firstRequired.name} · ${firstRequired.action}`:firstOptimise?`ผ่านขั้นต่ำพอใช้ · ปรับเพิ่มได้ ${firstOptimise.name}`:advisoryUnavailable.length?`ประเมินจาก ${metrics.length}/${evaluations.length} เกณฑ์ · ${advisoryUnavailable[0].name}ไม่มีข้อมูล แต่ไม่บล็อกภาพรวม`:`ครบ ${metrics.length}/${evaluations.length} เกณฑ์ · รักษาค่าปัจจุบัน`,
  };
}
function renderAdminAtmosphere(result){
  const summary=document.getElementById('adminAtmosphereSummary'),levelEl=document.getElementById('adminAtmosphereLevel'),coverage=document.getElementById('adminAtmosphereCoverage'),icon=document.getElementById('adminAtmosphereIcon'),guide=document.getElementById('adminAtmosphereLevelGuide'),criteria=document.getElementById('adminAtmosphereCriteria'),thresholds=document.getElementById('adminAtmosphereThresholds'),actions=document.getElementById('adminAtmosphereActions');
  if(!summary||!levelEl||!coverage||!icon||!guide||!criteria||!thresholds||!actions)return;
  summary.className=`admin-atmosphere-summary atmosphere-${result.key}`;
  const evaluations=Array.isArray(result.evaluations)?result.evaluations:[];
  const unavailable=evaluations.filter(metric=>metric.status!=='live');
  const blockingUnavailable=unavailable.filter(metric=>metric.required_for_overall!==false);
  const advisoryUnavailable=unavailable.filter(metric=>metric.required_for_overall===false);
  const required=evaluations.filter(metric=>(metric.status!=='live'&&metric.required_for_overall!==false)||metric.decision==='required'||Number(metric.score)<2);
  const belowExpected=required.filter(metric=>metric.status==='live');
  const optimise=evaluations.filter(metric=>metric.status==='live'&&(metric.decision==='optimise'||Number(metric.score)===2));
  const passed=evaluations.filter(metric=>metric.status==='live'&&Number(metric.score)>=2).length;
  // The dashboard card above is the single source for the current overall
  // level. This Admin summary reports workload instead of repeating it.
  levelEl.textContent=blockingUnavailable.length?`${blockingUnavailable.length} Sensor หลักไม่พร้อม`:belowExpected.length?`${belowExpected.length} จุดควรปรับ`:advisoryUnavailable.length?`${advisoryUnavailable.length} Sensor เสริมไม่พร้อม`:optimise.length?`${optimise.length} จุดปรับเพิ่ม`:'ค่าที่พร้อมอยู่ในเกณฑ์';
  coverage.textContent=`ผ่านขั้นต่ำ ${passed}/${evaluations.length||7} · ควรปรับ ${belowExpected.length} · หลักไม่พร้อม ${blockingUnavailable.length} · เสริมไม่พร้อม ${advisoryUnavailable.length}`;
  icon.textContent=result.symbol;
  const levels=Array.isArray(result.levels)&&result.levels.length?result.levels:dashboardAtmosphereLevels;
  guide.innerHTML=[...levels].reverse().map(level=>`<article class="atmosphere-guide-${level.key}${level.key===result.key?' active':''}"><span>${level.symbol}</span><div><b>${level.label} · ${level.english}</b><small>${level.description||level.principle||''}</small></div></article>`).join('');
  criteria.innerHTML=[...required,...advisoryUnavailable].map(metric=>{
    if(metric.status!=='live')return `<article class="admin-criterion unavailable"><div><b>${metric.name}</b><span>${metric.source} · ${metric.deviceStatus||'ไม่พร้อม'}</span></div><strong>${metric.display||'--'}</strong><small>เป้าหมาย ${metric.target}<br>${metric.principle}<br><em>${metric.bands}</em><br>${metric.required_for_overall===false?'Sensor เสริม · ไม่บล็อกภาพรวม':metric.deviceStatus==='stale'?'ค่าล่าสุดก่อน Restart · รอข้อมูลสด':'ตรวจ Sensor และ freshness'}</small></article>`;
    return `<article class="admin-criterion criterion-${metric.level.key}"><div><b>${metric.name}</b><span>${metric.source} · ${metric.level.label}</span></div><strong>${metric.display}</strong><small>ผ่านขั้นต่ำ ${metric.expected_floor||metric.target} · เป้าหมายสูงสุด ${metric.target}<br>${metric.recommendation||metric.principle}${metric.control?` · ตรวจที่ ${metric.control}`:''}</small></article>`;
  }).join('')||'<div class="admin-atmosphere-success"><span>✓</span><div><b>ผ่านขั้นต่ำพอใช้ขึ้นไปครบทุกเกณฑ์</b><small>ค่าที่พร้อมอยู่ในเกณฑ์ · ระดับพอใช้ยังแสดงเป็นข้อเสนอให้ปรับเพิ่มด้านล่าง</small></div></div>';
  const policyCriteria=Array.isArray(result.criteria)&&result.criteria.length?result.criteria:evaluations;
  thresholds.innerHTML=policyCriteria.map(metric=>`<article><b>${metric.label||metric.name}</b><span>${metric.bands_text||metric.bands}</span><small>${metric.source}${metric.mode?` · ${metric.mode}`:''}<br>${ADMIN_EXPLANATION_CONTEXT[metric.id||metric.key]||metric.principle||''}</small></article>`).join('');
  const basis=document.getElementById('adminAtmosphereBasis'),basisInfo=current.safety?.threshold_basis||{};
  if(basis)basis.textContent=`Environment ${result.version||'ยังไม่กำหนด'} · Mode ${result.mode||'sleep'} · Safety Basis ${basisInfo.version||'ยังไม่กำหนด'} ${basisInfo.approved?'APPROVED':'NOT APPROVED'} · เกณฑ์นี้เป็น ZEEP Wellness Context ไม่ใช่การวินิจฉัย และไม่เปลี่ยน Safety Alarm`;
  const requiredActions=Array.isArray(result.required_actions)?result.required_actions:required.map(metric=>({name:metric.name,current:metric.display||'ไม่มีข้อมูล Live',target:metric.expected_floor||metric.target,control:metric.control||metric.source,action:metric.recommendation||`ตรวจ ${metric.source}`}));
  const optimisationActions=Array.isArray(result.optimisation_actions)?result.optimisation_actions:optimise.map(metric=>({name:metric.name,current:metric.display,target:metric.target,control:metric.control,action:metric.recommendation}));
  // Required items already contain their corrective action in the cards on
  // the left. Keep this column for optional optimisation so the same warning
  // is not rendered twice.
  const actionRows=optimisationActions.map(action=>({...action,group:'ผ่านขั้นต่ำ · ปรับเพิ่มได้',kind:'optimise'}));
  if(!actionRows.length){
    actions.innerHTML=requiredActions.length
      ?'<div class="admin-atmosphere-empty">แก้รายการที่ระบุด้านซ้ายก่อน แล้วระบบจะประเมินใหม่จาก packet ถัดไป</div>'
      :'<div class="admin-atmosphere-success"><span>★</span><div><b>อยู่ระดับดีหรือยอดเยี่ยม</b><small>รักษาค่าปัจจุบันและติดตาม freshness ต่อเนื่อง</small></div></div>';
  }else{
    actions.innerHTML=actionRows.map((action,index)=>`<article class="admin-atmosphere-action ${action.kind}"><span>${index+1}</span><div><b>${action.group} · ${action.name} ${action.current} → ${action.target}</b><small>${action.action} · ตรวจที่ ${action.control}</small></div></article>`).join('');
  }
}
function renderDashboardAtmosphere(environment={},devices={}){
  const card=document.getElementById('dashAtmosphereCard'),levelEl=document.getElementById('dashAtmosphereLevel'),reasonEl=document.getElementById('dashAtmosphereReason'),icon=document.getElementById('dashAtmosphereIcon');
  if(!card||!levelEl||!reasonEl||!icon)return;
  // Pi is the source of truth so every User/Admin view uses exactly the same
  // Mode-aware, versioned bands. The local evaluator remains only as a
  // backward-compatible fallback while an older Pi is being upgraded.
  const sourceResult=environment.assessment||assessDashboardAtmosphere(environment,devices);
  const adminView=currentPrincipal?.role==='admin';
  const result=adminView?sourceResult:userEnvironmentPresentation(sourceResult);
  card.classList.remove('live','offline','atmosphere-unknown',...dashboardAtmosphereLevels.map(level=>`atmosphere-${level.key}`));
  card.classList.add(`atmosphere-${result.key}`,result.key==='unknown'?'offline':'live');
  levelEl.textContent=result.label;reasonEl.textContent=result.reason;icon.textContent=result.symbol;
  card.setAttribute('aria-label',`ภาพรวมภายใน ZEEP ${result.label} ${result.description} ${result.reason}`);
  const readings=result.metrics.length?result.metrics.map(metric=>`${metric.name} ${metric.display}`).join(' · '):result.reason;
  card.title=`${result.description} · ${readings} · คะแนนต่ำสุดจาก ${result.metrics.length||0} เกณฑ์ที่พร้อมเป็นระดับรวม`;
  // This card describes Wellness and comfort. True emergency signalling is
  // driven by renderSafety() from the Pi-local Safety Supervisor state.
  card.setAttribute('aria-live','polite');
  card.querySelectorAll('.atmosphere-scale > i').forEach(marker=>{
    const active=marker.dataset.level===result.key;
    marker.classList.toggle('active',active);
    if(active)marker.setAttribute('aria-current','true');else marker.removeAttribute('aria-current');
  });
  renderAdminAtmosphere(sourceResult);
  return sourceResult;
}

const ADMIN_EXPLANATION_CONTEXT=Object.freeze({
  temperature:'ใช้ประเมินความสบายเชิงความร้อน; ความรู้สึกร้อนหรือเย็นแตกต่างกันรายบุคคล',
  humidity:'ใช้ติดตามอากาศแห้ง ความชื้นสะสม และความเสี่ยงการควบแน่น',
  light:'OPT3001 วัด photopic lux; ไม่ใช่ melanopic EDI และต้องอ่านตาม Mode',
  sound:'ค่าประมาณจาก SPH0645LM4H-B ตาม Field Calibration; ไม่ใช่เครื่องวัดเสียง Class 1',
  co2:'ใช้เป็นตัวชี้การระบายอากาศ; ไม่ใช่ค่าปริมาณออกซิเจนในอากาศหรือในเลือด',
  pm25:'เป็นค่าฝุ่น ณ ขณะวัด; ค่าแนะนำ WHO แบบเฉลี่ยตามเวลาไม่ใช่ Alarm ทุก 10 วินาที',
  voc:'SGP40 เป็น Adaptive VOC Index แบบสัมพัทธ์; ระบุชนิดสารหรือแหล่งกำเนิดไม่ได้',
});
const ADMIN_LEVEL_COPY=Object.freeze({
  excellent:'ยอดเยี่ยมตามเป้าหมายของ Mode นี้',
  good:'ดีและผ่านเกณฑ์ขั้นต่ำของ Mode นี้',
  fair:'พอใช้ แต่ยังปรับให้เหมาะขึ้นได้',
  poor:'ต่ำกว่าเกณฑ์ที่คาดหวัง ควรปรับ',
  critical:'ควรปรับสภาพแวดล้อมตอนนี้',
  unknown:'ยังแปลผลไม่ได้',
});
const ADMIN_EXPLANATION_ICON=Object.freeze({
  hr:'♥',rr:'≈',sleep:'☾',temperature:'°',humidity:'%',light:'☼',sound:'dB',co2:'CO₂',pm25:'PM',voc:'VOC',unknown:'•',
});
const ADMIN_EXPLANATION_STATUS=Object.freeze({
  excellent:'ยอดเยี่ยม',good:'อยู่ในช่วง',info:'ยืนยันแล้ว',fair:'ควรติดตาม',poor:'ควรปรับ',critical:'ควรปรับตอนนี้',unknown:'รอข้อมูล',
});
function adminExplanationRow({tone='unknown',icon='unknown',title,value='--',status,summary,detail}){
  const marker=ADMIN_EXPLANATION_ICON[icon]||ADMIN_EXPLANATION_ICON.unknown;
  const state=status||ADMIN_EXPLANATION_STATUS[tone]||ADMIN_EXPLANATION_STATUS.unknown;
  const valueMarkup=value?`<strong>${value}</strong>`:'';
  return `<article class="admin-live-explanation-row tone-${tone}${value?'':' is-summary'}"><div class="admin-live-explanation-row-head"><span class="admin-live-explanation-metric-icon" aria-hidden="true">${marker}</span><b>${title}</b><em>${state}</em></div>${valueMarkup}<p>${summary}</p><small><i aria-hidden="true">→</i>${detail}</small></article>`;
}
function adminBaselineComparison(value,range,unit){
  if(!Number.isFinite(Number(value))||!Array.isArray(range)||range.length<2)return 'ยังไม่มีช่วงอ้างอิงของ State model ที่ใช้เทียบได้';
  const numeric=Number(value),minimum=Number(range[0]),maximum=Number(range[1]);
  if(!Number.isFinite(minimum)||!Number.isFinite(maximum))return 'ยังไม่มีช่วงอ้างอิงของ State model ที่ใช้เทียบได้';
  const band=`${minimum.toLocaleString('th-TH-u-nu-latn',{maximumFractionDigits:1})}–${maximum.toLocaleString('th-TH-u-nu-latn',{maximumFractionDigits:1})} ${unit}`;
  if(numeric<minimum)return `ต่ำกว่าช่วงอ้างอิงของ State model ${band}`;
  if(numeric>maximum)return `สูงกว่าช่วงอ้างอิงของ State model ${band}`;
  return `อยู่ในช่วงอ้างอิงของ State model ${band}`;
}
function adminBaselineTone(value,range){
  if(!Number.isFinite(Number(value))||!Array.isArray(range)||range.length<2)return 'unknown';
  const numeric=Number(value),minimum=Number(range[0]),maximum=Number(range[1]);
  if(!Number.isFinite(minimum)||!Number.isFinite(maximum))return 'unknown';
  return numeric>=minimum&&numeric<=maximum?'good':'fair';
}
function renderAdminLiveExplanation({bcg={},sleep={},session={},atmosphere}={}){
  const bioRoot=document.getElementById('adminBioExplanation');
  const environmentRoot=document.getElementById('adminEnvironmentExplanation');
  const modeRoot=document.getElementById('adminExplanationMode');
  if(!bioRoot||!environmentRoot||!modeRoot)return;
  const stageKey=sleep.classification_active===true?(sleep.confirmed_state||sleep.state):null;
  const stage=SLEEP_TH[stageKey]||SLEEP_TH.no_data;
  const baseline=(sleep.baseline||sleep.age_baseline||{})[stageKey]||{};
  const live=!!bcg.connected&&!bcg.stale&&bcg.analysis_stale!==true;
  const restored=bcg.restored_after_restart===true;
  const onBed=live&&[0,2,3,5].includes(Number(bcg.status_code));
  const rawHr=bcg.heart_rate_bpm,rawRr=bcg.respiration_rate;
  const hr=Number(rawHr),rr=Number(rawRr);
  const pairedPackets=Number(bcg.paired_vital_packets);
  const pairedCoverage=Number(bcg.paired_vital_coverage);
  const analysisEligible=live&&!restored
    &&bcg.analysis_valid===true
    &&[0,5].includes(Number(bcg.status_code))
    &&bcg.motion_contaminated!==true
    &&bcg.respiratory_signal_contaminated!==true
    &&Number.isFinite(pairedPackets)&&pairedPackets>=8
    &&Number.isFinite(pairedCoverage)&&pairedCoverage>=0.8;
  // ``Number(null)`` is zero in JavaScript. Preserve the explicit missing-data
  // contract so an empty vital can never be described as a real 0 reading.
  const rawHrVisible=rawHr!==null&&rawHr!==undefined&&rawHr!==''&&Number.isFinite(hr);
  const rawRrVisible=rawRr!==null&&rawRr!==undefined&&rawRr!==''&&Number.isFinite(rr);
  const hrValid=analysisEligible&&bcg.heart_rate_current_valid===true
    &&bcg.heart_rate_held!==true&&rawHrVisible;
  const rrValid=analysisEligible&&bcg.respiration_current_valid===true
    &&bcg.respiration_held!==true&&rawRrVisible;
  const hrRestored=restored&&rawHr!==null&&rawHr!==undefined&&rawHr!==''&&Number.isFinite(hr);
  const rrRestored=restored&&rawRr!==null&&rawRr!==undefined&&rawRr!==''&&Number.isFinite(rr);
  const stageTone=stageKey?'info':'unknown';
  const source=sleep.classification_source==='personal'?'Baseline ส่วนบุคคล':'Baseline อายุและเพศ';
  const confidence=({high:'สูง',medium:'ปานกลาง',low:'ต่ำ'})[sleep.confidence]||'ไม่ระบุ';
  const bedLabel=BCG_STATUS_TH[bcg.status_code]||bcg.status_text||'รอสัญญาณจากเตียง';
  const hrTone=hrValid?adminBaselineTone(hr,baseline.hr):'unknown';
  const rrTone=rrValid?adminBaselineTone(rr,baseline.rr):'unknown';
  const bioRows=[];
  // Current numbers already have one authoritative home in the health cards.
  // Repeat a vital here only when an operator must investigate it.
  if(!hrValid||hrRestored||hrTone!=='good')bioRows.push(adminExplanationRow({
    tone:hrTone,icon:'hr',title:'ชีพจร',value:(hrValid||hrRestored)?`${hr.toFixed(1)} ครั้ง/นาที`:'--',
    status:hrRestored?'ก่อน Restart':hrValid?(hrTone==='unknown'?'ไม่มีช่วงเทียบ':hrTone==='good'?'สอดคล้อง':'ต่างจากช่วงอ้างอิง'):rawHrVisible?'ยังไม่ใช้ตีความ':'รอข้อมูล',
    summary:hrRestored?'แสดงค่าล่าสุดเพื่อความต่อเนื่อง · ยังไม่เทียบช่วงอ้างอิง':hrValid?adminBaselineComparison(hr,baseline.hr,'ครั้ง/นาที'):rawHrVisible?'มีค่าแสดงผล แต่ Data-quality gate ยังไม่ครบ จึงไม่ใช้ตีความ':(onBed?'ยังคำนวณชีพจรไม่ได้':'ไม่มีสัญญาณผู้ใช้งานบนเตียง'),
    detail:hrRestored?'รอ BCG packet สดก่อนนำกลับไปวิเคราะห์':hrValid?`ค่าประมาณจาก BCG${bcg.heart_rate_held?' · เป็นค่าล่าสุดที่คงไว้ระหว่างตรวจคุณภาพสัญญาณ':''}; ตรวจแนวโน้มร่วมกับ ${source}`:'ตรวจสถานะเตียง ตำแหน่งผู้ใช้ และคุณภาพสัญญาณ BCG',
  }));
  if(!rrValid||rrRestored||rrTone!=='good')bioRows.push(adminExplanationRow({
    tone:rrTone,icon:'rr',title:'อัตราการหายใจ',value:(rrValid||rrRestored)?`${rr.toFixed(1)} ครั้ง/นาที`:'--',
    status:rrRestored?'ก่อน Restart':rrValid?(rrTone==='unknown'?'ไม่มีช่วงเทียบ':rrTone==='good'?'สอดคล้อง':'ต่างจากช่วงอ้างอิง'):rawRrVisible?'ยังไม่ใช้ตีความ':'รอข้อมูล',
    summary:rrRestored?'แสดงค่าล่าสุดเพื่อความต่อเนื่อง · ยังไม่เทียบช่วงอ้างอิง':rrValid?adminBaselineComparison(rr,baseline.rr,'ครั้ง/นาที'):rawRrVisible?'มีค่าแสดงผล แต่ Data-quality gate ยังไม่ครบ จึงไม่ใช้ตีความ':(onBed?'ยังคำนวณอัตราการหายใจไม่ได้':'ไม่มีสัญญาณผู้ใช้งานบนเตียง'),
    detail:rrRestored?'รอ BCG packet สดก่อนนำกลับไปวิเคราะห์':rrValid?`ค่าประมาณจาก BCG${bcg.respiration_held?' · เป็นค่าล่าสุดที่คงไว้ระหว่างตรวจคุณภาพสัญญาณ':''}; ตรวจความนิ่งร่วมกับ HR และ Movement`:'ยังไม่ใช้เป็นหลักฐาน Sleep Stage จนกว่า HR และ RR จะผ่าน Data-quality gate',
  }));
  if(hrValid&&rrValid&&!hrRestored&&!rrRestored&&hrTone==='good'&&rrTone==='good')bioRows.push(adminExplanationRow({
    tone:'good',icon:'hr',title:'สัญญาณชีพ',value:'',status:'สอดคล้องกับโมเดล',
    summary:'ชีพจรและอัตราการหายใจอยู่ในช่วงอ้างอิงของ State model ที่ยืนยัน',
    detail:`ติดตามแนวโน้มร่วมกับ Movement และ ${source} · ค่าปัจจุบันดูจากการ์ดด้านบน`,
  }));
  bioRows.push(adminExplanationRow({
      tone:stageTone,icon:'sleep',title:'สถานะการนอน',value:stageKey?`${stage.code} · ${stage.label}`:'รอยืนยัน',status:stageKey?'ยืนยันแล้ว':'รอหลักฐาน',
      summary:stageKey?(stage.meaning||stage.title):'ระบบยังไม่มีสถานะยืนยัน จึงไม่แสดง W/N1/N2/N3/REM แทนข้อมูลที่หาย',
      detail:stageKey?`${source} · ความมั่นใจ ${confidence} · Evidence 30 วินาทีและยืนยันแนวโน้ม 60 วินาที · ไม่ใช่ผล PSG`:`สถานะเตียง ${bedLabel} · ต้องมี Session, ผู้ใช้งานบนเตียง, HR และ RR ที่ใช้ได้ก่อน`,
  }));
  bioRoot.innerHTML=bioRows.join('');

  const result=atmosphere||{key:'unknown',evaluations:[]};
  const evaluations=Array.isArray(result.evaluations)?result.evaluations:[];
  const unavailable=evaluations.filter(metric=>metric.status!=='live');
  const blockingUnavailable=unavailable.filter(metric=>metric.required_for_overall!==false);
  const advisoryUnavailable=unavailable.filter(metric=>metric.required_for_overall===false);
  const required=evaluations.filter(metric=>(metric.status!=='live'&&metric.required_for_overall!==false)||metric.decision==='required'||Number(metric.score)<2);
  const optimise=evaluations.filter(metric=>metric.status==='live'&&(metric.decision==='optimise'||Number(metric.score)===2));
  const available=evaluations.filter(metric=>metric.status==='live').length;
  const environmentTone=result.key&&result.key!=='unknown'?result.key:'unknown';
  const environmentStatus=result.key==='unknown'?'รอข้อมูล':result.label||ADMIN_LEVEL_COPY[environmentTone]||environmentTone;
  const environmentSummary=blockingUnavailable.length
    ?`${blockingUnavailable.length} Sensor หลักไม่มีข้อมูล Live · ยังไม่ยืนยันภาพรวม`
    :required.length?`${required.length} จุดต่ำกว่าเกณฑ์ขั้นต่ำ · เริ่มจาก ${required[0].name}`
    :advisoryUnavailable.length?`ประเมินได้จาก ${available}/${evaluations.length||7} เกณฑ์ · ${advisoryUnavailable[0].name}เป็น Sensor เสริมที่ไม่มีข้อมูล`
    :optimise.length?`ผ่านขั้นต่ำแล้ว · มี ${optimise.length} จุดที่ปรับให้ดีขึ้นได้`:`Sensor พร้อม ${available}/${evaluations.length||7} เกณฑ์ · ไม่พบจุดที่ต้องแก้`;
  const environmentAction=required.length
    ?(required[0].recommendation||`ตรวจ ${required[0].source||required[0].name}`)
    :optimise.length?(optimise[0].recommendation||`ปรับ ${optimise[0].name}`)
    :advisoryUnavailable.length?`ตรวจ ${advisoryUnavailable[0].source} ภายหลัง โดยภาพรวมและ Safety ยังทำงานต่อ`
    :'รักษาการตั้งค่าปัจจุบันและติดตาม freshness ต่อเนื่อง';
  environmentRoot.innerHTML=evaluations.length?adminExplanationRow({
    tone:environmentTone,icon:'unknown',title:'ภาพรวมสภาพแวดล้อม',value:'',status:environmentStatus,
    summary:environmentSummary,detail:`${environmentAction} · ค่าราย Sensor อยู่ด้านบน`,
  }):'<div class="admin-live-explanation-empty">ยังไม่มีข้อมูล Sensor ที่ใช้แปลผลได้</div>';
  const modeLabel=({sleep:'Overnight Recovery',nap_recovery:'Nap & Refresh',relax_meditation:'Relax / Meditation',recovery_readiness:'Recovery / Readiness'})[result.mode]||session.rest_mode||'รอ Mode';
  modeRoot.textContent=`โหมด · ${modeLabel}`;
}
function renderSimpleDashboard(state={},environment={},bcg={},session={}){
  const active=!!session.active,recording=!!session.recording;
  const adminView=currentPrincipal?.role==='admin';
  renderHealthReference(session);
  const avatar=document.getElementById('dashAvatar');
  const account=active?identityLabel(session):'ยังไม่เริ่ม Session';
  avatar.textContent=active?String(account||'Z').trim().slice(0,1).toUpperCase():'Z';
  document.getElementById('dashUserName').textContent=account;
  document.getElementById('dashUserMeta').textContent=active
    ? `${genderTh(session.gender)} · ${displayAge(session)} · ${adminView
      ?recording?`บันทึกแล้ว ${session.samples||0} จุด`:sessionStartGateText(session,state.system||{})
      :recording?'กำลังบันทึกการพัก':'กำลังเตรียมเริ่มบันทึก'}`
    : adminView?'เลือกผู้ใช้งานเพื่อเริ่มติดตามสุขภาพและสภาพแวดล้อม':'เข้าสู่ระบบเพื่อเริ่มการพัก';
  const badge=document.getElementById('dashSessionBadge');
  badge.textContent=adminView
    ?recording?'● RECORDING':active?'WAITING FOR VITALS':'NO SESSION'
    :recording?'● กำลังบันทึก':active?'กำลังเตรียม':'ยังไม่เริ่ม';
  badge.classList.toggle('live',recording);
  const bcgLive=!!bcg.connected&&!bcg.stale,bcgStatus=Number(bcg.status_code),bcgRestored=bcg.restored_after_restart===true;
  const personOnBed=bcgLive&&[0,2,3,5].includes(bcgStatus);
  const vitalFallbackNote=adminView
    ?!bcgLive?'รอสัญญาณ BCG':bcgStatus===1?'ไม่พบผู้ใช้งานบนเตียง':personOnBed?'กำลังวิเคราะห์สัญญาณ':'รอข้อมูลจาก Sensor'
    :!bcgLive?'กำลังเชื่อมต่อข้อมูล':bcgStatus===1?'ออกจากเตียง':personOnBed?'กำลังอ่านสัญญาณ':'กำลังเตรียมข้อมูล';
  document.getElementById('dashHr').textContent=bcg.heart_rate_bpm??(personOnBed?'…':'--');
  document.getElementById('dashRr').textContent=bcg.respiration_rate==null?(personOnBed?'…':'--'):Number(bcg.respiration_rate).toFixed(1);
  document.getElementById('dashHrNote').textContent=bcg.heart_rate_bpm==null?vitalFallbackNote:bcgRestored?(adminView?'ค่าล่าสุดก่อน Restart · รอ BCG สด':'กำลังเชื่อมต่อข้อมูลล่าสุด'):(bcg.heart_rate_held?(adminView?'ค่าล่าสุด · กำลังวิเคราะห์':'กำลังตรวจความต่อเนื่อง'):'ครั้ง/นาที');
  document.getElementById('dashRrNote').textContent=bcg.respiration_rate==null?vitalFallbackNote:bcgRestored?(adminView?'ค่าล่าสุดก่อน Restart · รอ BCG สด':'กำลังเชื่อมต่อข้อมูลล่าสุด'):(bcg.respiration_held?(adminView?'ค่าล่าสุด · กำลังวิเคราะห์':'กำลังตรวจความต่อเนื่อง'):'ครั้ง/นาที');
  const bedShort=(adminView
    ?{0:'ON BED',1:'OFF BED',2:'MOVING',3:'WEAK',4:'OBJECT',5:'SNORING'}
    :{0:'อยู่บนเตียง',1:'ออกจากเตียง',2:'กำลังขยับ',3:'กำลังอ่านสัญญาณ',4:'พบแรงกด',5:'อยู่บนเตียง'})[bcg.status_code]||'--';
  document.getElementById('dashBed').textContent=bedShort;
  document.getElementById('dashBedNote').textContent=adminView
    ?BCG_STATUS_TH[bcg.status_code]||bcg.status_text||'รอสัญญาณจากเตียง'
    :USER_BED_STATUS_TH[bcg.status_code]||'กำลังอ่านสถานะเตียง';
  const sleep=state.sleep||{};
  const restartSleepHold=sleep.display_only_after_restart===true
    &&sleep.held_previous_state===true&&sleep.classification_active===true;
  const vitalPairValid=bcg.heart_rate_bpm!=null&&bcg.respiration_rate!=null
    &&Number.isFinite(Number(bcg.heart_rate_bpm))&&Number.isFinite(Number(bcg.respiration_rate));
  const sleepOccupancyValid=personOnBed||restartSleepHold;
  const classificationActive=active&&recording&&sleepOccupancyValid
    &&(vitalPairValid||restartSleepHold)&&sleep.classification_active===true;
  const initialWait=['confirming_initial_state','collecting_evidence_epoch']
    .includes(sleep.data_status);
  const sleepStateKey=!active||!sleepOccupancyValid?'off_bed'
    : classificationActive?sleep.state
    : recording&&initialWait?'wait_initial':'no_data';
  const sleepMeta=SLEEP_TH[sleepStateKey]||SLEEP_TH.no_data;
  document.getElementById('dashSleep').textContent=!adminView&&['wait_initial','no_data'].includes(sleepStateKey)
    ?'กำลังประเมินการพัก'
    :sleepStateKey==='wait_initial'?sleepMeta.title:sleepMeta.label;
  document.getElementById('dashSleep').title=sleepMeta.meaning||sleepMeta.title||'';
  const confidence=({high:'สูง',medium:'ปานกลาง',low:'ต่ำ'})[sleep.confidence]||'ไม่ระบุ';
  const sleepSource=sleep.classification_source==='personal'?'Baseline ส่วนบุคคล':'Baseline อายุและเพศ';
  const evidenceCandidate=sleep.evidence?.candidate||sleep.probability_winner||sleep.raw_candidate;
  const confirmation=sleep.confirmation||{};
  document.getElementById('dashSleepNote').textContent=adminView
    ?classificationActive
      ?restartSleepHold
        ?`${sleepMeta.code} ก่อน Restart · กำลังรับหลักฐานสด · ไม่บันทึกซ้ำ`
        :sleep.held_previous_state
          ?`${sleepMeta.code} · ${sleep.provisional?'provisional · ':''}คง State ก่อนหน้า · ผู้ท้าชิง ${(confirmation.pending_state||evidenceCandidate||'--').toUpperCase()} ยังไม่นับเป็น State ใหม่ · ${sleep.score_eligible?'นับเวลาตาม State เดิม':'ยังไม่นับคะแนน'}`
          :`${sleepMeta.code} ยืนยันแล้ว · หลักฐาน ${(evidenceCandidate||'--').toUpperCase()} · ${sleepSource} · มั่นใจ ${confidence}`
      :sleep.evidence_active
        ?`หลักฐาน ${(evidenceCandidate||'--').toUpperCase()} · กำลังยืนยัน ${confirmation.candidate_epochs||0}/${confirmation.required_epochs||2} epoch`
        :`${sleepMeta.code} · ${sleep.reason||vitalFallbackNote} · ยังไม่จัดประเภทการนอน`
    :restartSleepHold
      ?'กำลังเชื่อมต่อข้อมูลล่าสุด · แสดงสถานะเดิมต่อเนื่อง'
      :classificationActive&&sleep.held_previous_state
        ?'กำลังยืนยันการเปลี่ยนแปลง · แสดงสถานะเดิมต่อเนื่อง'
        :classificationActive
          ?'ประเมินจากแนวโน้มชีพจร การหายใจ และการพักนิ่ง'
          :sleep.evidence_active?'กำลังดูแนวโน้มให้ชัดขึ้น':'กำลังอ่านสัญญาณจากเตียง';
  renderAdminSleepBaseline(sleep,session);
  const devices=environment.devices||{};
  setDashboardSensor('dashSensorTemp','dashTemp',environment.temperature_c,'°C',devices.sht3x_dis,1);
  setDashboardSensor('dashSensorHumidity','dashHumidity',environment.humidity_rh,'%RH',devices.sht3x_dis,1);
  setDashboardSensor('dashSensorLight','dashLight',environment.lux,'lux',devices.opt3001,1);
  setDashboardSensor('dashSensorCo2','dashCo2',environment.co2_ppm,'ppm',devices.mhz19c,0);
  setDashboardSensor('dashSensorPm','dashPm',environment.pm2_5_ug_m3,'µg/m³',devices.pms7003,1);
  setDashboardSensor('dashSensorVoc','dashVoc',environment.voc_index,'',devices.sgp40,0);
  const soundMetric=soundDisplayMetric(environment);
  setDashboardSensor('dashSensorSound','dashSound',soundMetric.value,soundMetric.unit,devices.sph0645,soundMetric.digits);
  const atmosphere=renderDashboardAtmosphere(environment,devices);
  renderAdminLiveExplanation({bcg,sleep,session,atmosphere});
  document.getElementById('dashSensorSummary').textContent=adminView
    ?`Sensor ${environment.live_count||0}/${environment.total_count||6} · ${environment.status||'offline'}`
    :`ข้อมูลพร้อม ${environment.live_count||0}/${environment.total_count||6}`;
}

function renderAdminSleepBaseline(sleep={},session={}){
  const grid=document.getElementById('dashSleepBaselineGrid');
  const sourceEl=document.getElementById('dashSleepBaselineSource');
  const progressEl=document.getElementById('dashSleepBaselineProgress');
  const policyEl=document.getElementById('dashSleepBaselinePolicy');
  if(!grid||!sourceEl||!progressEl)return;
  const stages=[
    {key:'wake',code:'W',label:'ตื่น'},
    {key:'n1',code:'N1',label:'หลับตื้น'},
    {key:'n2',code:'N2',label:'หลับสนิทขึ้น'},
    {key:'n3',code:'N3',label:'หลับลึก'},
    {key:'rem',code:'REM',label:'ฝัน'},
  ];
  const baseline=sleep.baseline||sleep.age_baseline||{};
  const probabilities=sleep.evidence_probabilities||sleep.probabilities||{};
  const probabilityValue=key=>{
    const value=Number(probabilities[key]);
    return Number.isFinite(value)?Math.max(0,value):0;
  };
  const currentStage=sleep.classification_active===true
    &&stages.some(stage=>stage.key===sleep.confirmed_state||stage.key===sleep.state)
      ? (sleep.confirmed_state||sleep.state):null;
  const fitSummary=sleep.baseline_fit_summary||{};
  const baselineWinner=stages.some(stage=>stage.key===fitSummary.winner)
    ? fitSummary.winner:null;
  const evidenceStage=stages.some(stage=>stage.key===(sleep.evidence?.candidate||sleep.probability_winner))
    ? (sleep.evidence?.candidate||sleep.probability_winner):null;
  const formatProbability=value=>(value*100).toLocaleString('th-TH-u-nu-latn',{
    minimumFractionDigits:1,maximumFractionDigits:1,
  });
  const formatRange=pair=>Array.isArray(pair)&&pair.length>=2
    ? `${Number(pair[0]).toLocaleString('th-TH-u-nu-latn',{maximumFractionDigits:1})}–${Number(pair[1]).toLocaleString('th-TH-u-nu-latn',{maximumFractionDigits:1})}`
    : '--';
  const hasBaseline=stages.some(stage=>baseline[stage.key]);
  if(!hasBaseline){
    grid.innerHTML='<div class="admin-sleep-baseline-empty">ยังไม่มีข้อมูล Baseline สำหรับ Session นี้</div>';
  }else{
    grid.innerHTML=stages.map(stage=>{
      const range=baseline[stage.key]||{};
      const proximity=(sleep.baseline_proximity||{})[stage.key]||{};
      const probability=probabilityValue(stage.key);
      const isCurrent=stage.key===currentStage;
      const isEvidence=stage.key===evidenceStage;
      const isBaselineWinner=stage.key===baselineWinner;
      return `<article class="admin-sleep-stage stage-${stage.key}${isCurrent?' current':''}${isEvidence?' evidence':''}${isBaselineWinner?' baseline-nearest':''}" data-stage="${stage.key}">
        <div class="admin-sleep-stage-head"><span><b>${stage.code}</b><small>${stage.label}</small></span><em aria-label="หลักฐาน ${stage.label} ${formatProbability(probability)} เปอร์เซ็นต์">${isCurrent?'ยืนยัน · ':isEvidence?'หลักฐาน · ':''}${formatProbability(probability)}%</em></div>
        <div class="admin-sleep-stage-ranges"><span><small>HR</small><b>${formatRange(range.hr)}</b><em>BPM</em></span><span><small>RR</small><b>${formatRange(range.rr)}</b><em>ครั้ง/นาที</em></span></div>
        <div class="mini">${isBaselineWinner?'HR/RR ใกล้สุด · ':''}Fit ${Number.isFinite(Number(proximity.weighted_percent))?Number(proximity.weighted_percent).toFixed(1)+'%':'--'} · ΔHR ${Number(proximity.hr?.distance_to_range)||0} · ΔRR ${Number(proximity.rr?.distance_to_range)||0}</div>
      </article>`;
    }).join('');
  }
  const personal=sleep.personal_baseline||{};
  sourceEl.textContent=sleep.classification_source==='personal'
    ? `Personal Baseline · ${personal.nights_used||0} คืน`
    : `Age + Gender · ${sleep.age_group||session.age_group||'18-29'} ปี · ${genderTh(sleep.gender||session.gender)}`;
  const frame=current.sensor_frame||current.analysis_frame||{};
  const frameTime=frame.timestamp?new Date(frame.timestamp).toLocaleTimeString('th-TH',{hour12:false}):'--:--:--';
  const clock=sleep.sensor_frame_clock||{},confirmation=sleep.confirmation||{};
  progressEl.textContent=`Frame #${frame.sequence??'--'} · ${frameTime} · Sensor ${sleep.sample_s||10} วิ (${clock.frame_in_epoch||0}/${clock.sensor_frames_per_epoch||3}) · Evidence ${sleep.evidence_epoch_s||30} วิ · Confirm ${confirmation.candidate_epochs||0}/${confirmation.required_epochs||2} epoch`;
  if(policyEl){
    const context=(sleep.environment||{}).zeep_context||{};
    const support=Number.isFinite(Number(context.sleep_support_score))
      ? ` · Environment ${Number(context.sleep_support_score)}/100`
      : '';
    const transition=sleep.transition_policy||{};
    const pending=transition.held
      ? ` · Evidence ${(transition.raw_candidate||'--').toUpperCase()} ${transition.candidate_epochs||0}/${transition.required_epochs||2} epoch`
      : '';
    const scoring=sleep.scoring_weights||sleep.baseline_definition?.scoring_weights||{};
    const hrWeight=Number(scoring.hr_baseline),rrWeight=Number(scoring.rr_baseline);
    const weightText=Number.isFinite(hrWeight)&&Number.isFinite(rrWeight)
      ? ` · Weight HR ${Math.round(hrWeight*100)} / RR ${Math.round(rrWeight*100)}`:'';
    const rrConflict=Number(sleep.rr_stage_guard?.conflict);
    const rrGuard=Number.isFinite(rrConflict)&&rrConflict>=0.05
      ? ` · RR guard N2>N3 ${Math.round(rrConflict*100)}%`:'';
    const filter=sleep.probability_filter||{};
    const filterText=Number.isFinite(Number(filter.alpha))
      ? ` · Stability EMA ${Math.round(Number(filter.alpha)*100)}% / margin ${Math.round(Number(filter.candidate_switch_margin||0)*100)}%`
      : '';
    const fitExplanation=fitSummary.explanation_th
      ? ` · ${fitSummary.explanation_th}`:'';
    policyEl.textContent=`G2: W / N1 / N2 / N3 / REM${weightText}${rrGuard}${filterText} · หลักฐาน 30 วิแยกจากสถานะยืนยัน 60 วิ · HR/RR Fit เป็นหลักฐานสนับสนุน ไม่ใช่ State โดยลำพัง${fitExplanation} · Safety/Bed Exit ไม่รอ Sleep State${pending}${support} · ยังไม่ใช่ผล PSG`;
  }
}
