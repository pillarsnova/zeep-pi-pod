const names = {led:'Lighting Room', star_light:'ไฟดาวบนท้องฟ้า', aroma1:'ลาเวนเดอร์', aroma2:'ยูคาลิปตัส', aroma3:'ส้ม', aroma4:'อากาศสดชื่น', steam:'ไอน้ำ'};
const outputIcons = {led:'lamp', star_light:'star', aroma1:'flower', aroma2:'leaf', aroma3:'orange', aroma4:'air', steam:'steam'};
function setUiIconReference(svg,name){
  const use=svg?.querySelector('use');
  if(use)use.setAttribute('href',`#ui-icon-${name}`);
}
let alertSoundEnabled = localStorage.getItem('zeep_monitor_sound') === '1';
const monitorAlertState = {};
let monitorAudioContext = null;
const USER_PRODUCT_COPY=Object.freeze({
  scoreLevels:Object.freeze({
    very_good:'ดีมาก',good:'ดี',fair:'พอใช้',low:'ให้เวลากับการพักเพิ่ม',
    unavailable:'กำลังเตรียมผลสรุป',unknown:'ผลการพักครั้งนี้',
  }),
  environmentLevels:Object.freeze({
    excellent:'ยอดเยี่ยม',good:'ดี',fair:'พอใช้',poor:'ควรปรับ',
    critical:'แนะนำให้ปรับตอนนี้',unknown:'กำลังรวบรวมข้อมูล',
  }),
  confidenceLevels:Object.freeze({
    high:'ข้อมูลชัดเจน',medium:'ข้อมูลเพียงพอ',low:'กำลังรวบรวมข้อมูลเพิ่ม',
    unknown:'กำลังเตรียมผลสรุป',
  }),
  environmentMetrics:Object.freeze({
    temperature:'อุณหภูมิ',temp:'อุณหภูมิ',humidity:'ความชื้น',hum:'ความชื้น',
    sound:'เสียง',dba:'เสียง',co2:'CO₂',pm25:'PM2.5',pm2_5:'PM2.5',voc:'VOC Index',
  }),
});
function userScoreLevelLabel(quality={}){
  return USER_PRODUCT_COPY.scoreLevels[String(quality.level_key||'').toLowerCase()]
    ||USER_PRODUCT_COPY.scoreLevels.unknown;
}
function userConfidenceLevelLabel(level){
  return USER_PRODUCT_COPY.confidenceLevels[String(level||'unknown').toLowerCase()]
    ||USER_PRODUCT_COPY.confidenceLevels.unknown;
}
function userScoreMeaning(quality={}){
  if(!quality?.available)return 'ZEEP กำลังรวบรวมข้อมูลเพื่อสรุปผลการพักครั้งนี้';
  const level=String(quality.level_key||'unknown').toLowerCase();
  const recovery=quality.quality_type==='rest_goal'||String(quality.score_title||'').includes('Recovery');
  const meanings=recovery?{
    very_good:'ช่วงพักนี้เป็นไปได้ดีมากตามเป้าหมายที่เลือก',
    good:'ช่วงพักนี้เป็นไปได้ดีตามเป้าหมายที่เลือก',
    fair:'ช่วงพักนี้ช่วยให้ร่างกายได้หยุดนิ่งและผ่อนคลาย',
    low:'ครั้งนี้ยังมีบางจุดที่ช่วยให้ช่วงพักสบายขึ้นได้',
  }:{
    very_good:'เวลา ความต่อเนื่อง และรูปแบบการนอนคืนนี้อยู่ในระดับดีมาก',
    good:'ภาพรวมการนอนคืนนี้อยู่ในระดับดี',
    fair:'คืนนี้ได้พักในระดับหนึ่ง และยังมีบางจุดที่ดูแลเพิ่มได้',
    low:'ครั้งนี้ยังมีบางจุดที่ช่วยให้การพักสบายและต่อเนื่องขึ้นได้',
  };
  return meanings[level]||'ดูภาพรวมการพักครั้งนี้ร่วมกับรายละเอียดด้านล่าง';
}
function userReportFinding(item={}){
  const metricKey=String(item.metric_key||item.key||'')
    .replace(/_safety_excursion$/,'').toLowerCase();
  const metric=USER_PRODUCT_COPY.environmentMetrics[metricKey]||'สภาพแวดล้อม';
  const severity=String(item.severity||'unavailable');
  const safetyReview=item.decision==='safety_review';
  const label=safetyReview
    ?'ควรให้ทีมตรวจสอบ'
    :USER_PRODUCT_COPY.environmentLevels[severity]||'กำลังรวบรวมข้อมูล';
  const detail=safetyReview
    ?'มีค่าบางช่วงแตะเกณฑ์ความปลอดภัย กรุณาแจ้งทีมงานก่อนใช้งานครั้งถัดไป'
    :severity==='unavailable'
      ?'ZEEP กำลังรวบรวมข้อมูลส่วนนี้'
      :['good','excellent'].includes(severity)
        ?'อยู่ในช่วงที่เหมาะกับการพักครั้งนี้'
        :severity==='fair'
          ?'ยังปรับให้เหมาะกับการพักได้อีกเล็กน้อย'
          :'มีปัจจัยที่ปรับให้การพักสบายขึ้นได้';
  const action=safetyReview
    ?'กรุณาแจ้งทีมงาน'
    :['critical','poor'].includes(severity)
      ?'ทีมงานช่วยปรับค่านี้ให้เหมาะกับครั้งถัดไปได้'
      :'';
  return {metric,severity,label,detail,action};
}
function userEnvironmentPresentation(result={}){
  const key=String(result.key||'unknown').toLowerCase();
  const limiting=Array.isArray(result.limiting)&&result.limiting.length
    ?result.limiting[0].name:null;
  const reason={
    excellent:'ทุกค่าที่พร้อมอยู่ในช่วงเป้าหมาย',
    good:'สภาพแวดล้อมโดยรวมเหมาะกับการพัก',
    fair:`ใช้งานได้${limiting?` · ${limiting} ยังปรับให้สบายขึ้นได้`:''}`,
    poor:`${limiting||'บางปัจจัย'} ควรปรับเพื่อให้พักสบายขึ้น`,
    critical:`${limiting||'สภาพแวดล้อม'} แนะนำให้ปรับสำหรับการพักครั้งนี้`,
    unknown:'กำลังรวบรวมข้อมูลภายใน ZEEP',
  }[key]||'กำลังรวบรวมข้อมูลภายใน ZEEP';
  return {...result,label:USER_PRODUCT_COPY.environmentLevels[key]
    ||USER_PRODUCT_COPY.environmentLevels.unknown,reason};
}
function updateAlertButton(){
  const b=document.getElementById('alertSoundBtn');if(!b)return;
  setUiIconReference(b.querySelector('.ui-icon'),alertSoundEnabled?'volume-on':'volume-off');
  const label=b.querySelector('.ui-button-label');
  if(label)label.textContent=alertSoundEnabled?'ปิดเสียงแจ้งเตือน':'เปิดเสียงแจ้งเตือน';
  b.setAttribute('aria-pressed',alertSoundEnabled?'true':'false');
}
function toggleAlertSound(){alertSoundEnabled=!alertSoundEnabled;localStorage.setItem('zeep_monitor_sound',alertSoundEnabled?'1':'0');updateAlertButton();if(alertSoundEnabled){playMonitorTone('info');toast('เปิดเสียง Monitor alerts แล้ว','ok');}}
function playMonitorTone(level='warn'){
  if(!alertSoundEnabled)return;
  try{monitorAudioContext||=new(window.AudioContext||window.webkitAudioContext)();const o=monitorAudioContext.createOscillator(),g=monitorAudioContext.createGain();o.type=level==='bad'?'square':'sine';o.frequency.value=level==='bad'?330:level==='warn'?520:720;g.gain.setValueAtTime(.0001,monitorAudioContext.currentTime);g.gain.exponentialRampToValueAtTime(.08,monitorAudioContext.currentTime+.02);g.gain.exponentialRampToValueAtTime(.0001,monitorAudioContext.currentTime+.22);o.connect(g);g.connect(monitorAudioContext.destination);o.start();o.stop(monitorAudioContext.currentTime+.24);}catch{}
}
function setMonitorAlert(key,active,message,level='warn'){
  const hadAnyAlert=Object.values(monitorAlertState).some(Boolean);
  const previous=!!monitorAlertState[key];
  monitorAlertState[key]=active?{message,level}:null;
  const announceNewEmergency=key==='safety_emergency'&&level==='bad';
  if(active&&!previous&&(!hadAnyAlert||announceNewEmergency)){
    playMonitorTone(level);toast(`${level==='bad'?'⛔':'⚠️'} ${message} · ดูรายการรวมด้านล่าง`,level==='bad'?'error':'',4200);
  }
  const activeAlerts=Object.values(monitorAlertState).filter(Boolean),root=document.getElementById('monitorAlertStatus');if(!root)return;
  if(!activeAlerts.length){root.className='monitor-alert-status good';root.textContent=`✅ ระบบรับข้อมูลปกติ · เสียง${alertSoundEnabled?'เปิด':'ปิด'}`;return;}
  const badCount=activeAlerts.filter(a=>a.level==='bad').length;
  root.className=`monitor-alert-status ${badCount?'bad':'warn'}`;
  root.textContent=badCount
    ? `⛔ ต้องตรวจ ${activeAlerts.length} รายการ · Fault ${badCount}`
    : `⚠️ ต้องติดตาม ${activeAlerts.length} รายการ`;
}
function evaluateMonitorAlerts(e,h2,env,b,sys){
  const age=b.last_update?Date.now()/1000-b.last_update:Infinity;
  setMonitorAlert('esp',!e.connected,'Pi5 Sensor Set 1 (USB) ไม่เชื่อมต่อ','bad');
  setMonitorAlert('hub2',!h2.connected,'ESP32 Air Sensor (MQTT) ไม่เชื่อมต่อ','bad');
  Object.entries(env.devices||{}).forEach(([key,device])=>{
    const bad=['fault','invalid','offline'].includes(device.status),warn=['stale','held','warming','no_data'].includes(device.status);
    setMonitorAlert(`sensor_${key}`,bad||warn,`${device.model||key}: ${device.status}`,bad?'bad':'warn');
  });
  setMonitorAlert('bcg',!b.connected,'BCG Sensor ไม่เชื่อมต่อ','bad');
  setMonitorAlert('flow',b.connected&&age>15,`BCG ไม่มี Frame ใหม่ ${Math.round(age)} วินาที`,'warn');
  setMonitorAlert('gpio',!sys.gpio_available,'GPIO unavailable','warn');
  setMonitorAlert('saturation',(b.samples||[]).some(v=>v<=-32768||v>=32767),'Raw BCG พบค่าแตะขอบ int16','warn');
}
