function fmt(v,d=1){ return (v===undefined||v===null) ? '--' : Number(v).toFixed(d); }
function sensorNumber(source, paths){
  for(const path of paths){let value=source;for(const key of path.split('.'))value=value&&typeof value==='object'?value[key]:undefined;if(value===undefined||value===null||typeof value==='boolean'||value==='')continue;const number=Number(value);if(Number.isFinite(number))return number;}return null;
}
const sensorUi={
  sht3x_dis:{card:'sensorSht',status:'shtStatus',icon:'T',value:e=>`${fmt(e.temperature_c,1)}°C · ${fmt(e.humidity_rh,1)}%RH`},
  opt3001:{card:'sensorOpt',status:'optStatus',icon:'☼',value:e=>`${fmt(e.lux,0)} lux`},
  sph0645:{card:'sensorSph',status:'sphStatus',icon:'≈',value:e=>{const s=soundDisplayMetric(e);return `${fmt(s.value,s.digits)} ${s.unit}`;}},
  mhz19c:{card:'sensorCo2',status:'co2Status',icon:'CO₂',value:e=>`${fmt(e.co2_ppm,0)} ppm`},
  pms7003:{card:'sensorPms',status:'pmsStatus',icon:'••',value:e=>`PM1.0 ${fmt(e.pm1_0_ug_m3,0)} · PM2.5 ${fmt(e.pm2_5_ug_m3,0)} · PM10 ${fmt(e.pm10_ug_m3,0)} µg/m³`},
  sgp40:{card:'sensorSgp',status:'sgpStatus',icon:'VOC',value:e=>`Index ${fmt(e.voc_index,0)} · SRAW ${fmt(e.sgp40_raw,0)}`},
};
const sensorStatusTh={live:'Live',stale:'ข้อมูลค้าง',held:'คงค่าล่าสุด',warming:'Warm-up',fault:'Sensor fault',invalid:'ค่าผิดช่วง',no_data:'ไม่มีข้อมูล',offline:'Offline'};
function legacyEnvironment(e={},h2={}){
  const value=(sources,paths)=>{for(const source of sources){const n=sensorNumber(source,paths);if(n!==null)return n;}return null;};
  const directSound=e.sound_dba_est??e.sound_dba;
  const data={temperature_c:value([e],['temperature','temperature_c']),humidity_rh:value([e],['humidity','humidity_rh']),lux:value([e],['lux']),sound_dba_est:typeof directSound==='number'&&Number.isFinite(directSound)&&directSound>=30&&directSound<=130?directSound:null,sound_dbfs_raw:value([e],['sound_dbfs_raw','sound_dbfs']),co2_ppm:value([h2,e],['co2_ppm','co2']),pm1_0_ug_m3:value([h2,e],['pm1_0_ug_m3']),pm2_5_ug_m3:value([h2,e],['pm2_5_ug_m3']),pm10_ug_m3:value([h2,e],['pm10_ug_m3']),voc_index:value([h2,e],['voc_index']),sgp40_raw:value([h2,e],['sgp40_raw','sraw_voc'])};
  const d1=e.connected?'live':e.last_update?'stale':'offline',d2=h2.connected?'live':h2.last_update?'stale':'offline';
  data.devices={sht3x_dis:{model:'SHT3x-DIS',status:data.temperature_c!=null&&data.humidity_rh!=null?d1:'no_data',source:'hub1',source_label:'Pi5 Sensor Set 1 · USB',data_age_s:e.data_age_s},opt3001:{model:'OPT3001',status:data.lux!=null?d1:'no_data',source:'hub1',source_label:'Pi5 Sensor Set 1 · USB',data_age_s:e.data_age_s},sph0645:{model:'SPH0645LM4H-B',status:data.sound_dba_est!=null?d1:'no_data',source:'hub1',source_label:'Pi5 Sensor Set 1 · USB',data_age_s:e.data_age_s},mhz19c:{model:'MH-Z19C',status:data.co2_ppm!=null?d2:'no_data',source:'hub2',source_label:'ESP32 Air Sensor · MQTT',data_age_s:h2.data_age_s},pms7003:{model:'PMS7003',status:data.pm2_5_ug_m3!=null?d2:'no_data',source:'hub2',source_label:'ESP32 Air Sensor · MQTT',data_age_s:h2.data_age_s},sgp40:{model:'SGP40',status:data.voc_index!=null?d2:'no_data',source:'hub2',source_label:'ESP32 Air Sensor · MQTT',data_age_s:h2.data_age_s}};
  data.live_count=Object.values(data.devices).filter(d=>d.status==='live').length;data.total_count=6;data.status=data.live_count===6?'live':data.live_count?'degraded':'offline';return data;
}
function setSensorDeviceState(key,device={}){
  const ui=sensorUi[key],card=document.getElementById(ui.card),status=document.getElementById(ui.status);if(!card||!status)return;
  card.classList.remove('live','fallback','warming','error','offline');
  const state=device.status||'offline';
  card.classList.add(state==='live'?'live':['stale','held'].includes(state)?'fallback':state==='warming'?'warming':['fault','invalid'].includes(state)?'error':'offline');
  const age=Number(device.data_age_s);status.textContent=sensorStatusTh[state]||state;status.title=Number.isFinite(age)?`ข้อมูลล่าสุด ${age.toFixed(1)} วินาที`:'ยังไม่มีเวลา packet';
}
function renderAssessment(id,meterId,result){
  const root=document.getElementById(id),meter=document.getElementById(meterId);if(!root||!meter)return;
  root.className=`sensor-assessment ${result.level||''}`;root.querySelector('strong').textContent=result.label;root.querySelector('span').textContent=result.detail;meter.style.width=`${Math.max(0,Math.min(100,result.pct||0))}%`;
}
function renderSensorAssessments(e){
  const t=e.temperature_c,h=e.humidity_rh,l=e.lux,s=e.sound_dba_est,c=e.co2_ppm,p=e.pm2_5_ug_m3,v=e.voc_index;
  renderAssessment('shtAssessment','shtMeter',t==null||h==null?{label:'รอข้อมูล',detail:'18–27°C · 40–60%RH',pct:0}:{label:t>29||h>65?'นอก Comfort band':t<18||h<40||t>27||h>60?'ควรติดตาม':'ยอดเยี่ยม',detail:`${fmt(t,1)}°C · ${fmt(h,1)}%RH`,level:t>29||h>65?'bad':t<18||h<40||t>27||h>60?'warn':'good',pct:(t-10)/30*100});
  renderAssessment('optAssessment','optMeter',l==null?{label:'รอข้อมูล',detail:'โหมดนอน ≤5 lux',pct:0}:{label:l<=5?'มืดเหมาะกับโหมดนอน':l<=20?'แสงสลัว':'สว่าง',detail:`${fmt(l,1)} lux`,level:l<=5?'good':l<=20?'warn':'bad',pct:l/50*100});
  renderAssessment('sphAssessment','sphMeter',s==null?{label:'รอข้อมูล',detail:'รอ sound_dba จาก ESP32 · เป้าหมาย ≤35 dBA',pct:0}:{label:s<=35?'อยู่ในเป้าหมาย':s<=45?'สูงกว่าเป้าหมาย':'เสียงสูง',detail:`${fmt(s,1)} dBA`,level:s<=35?'good':s<=45?'warn':'bad',pct:s/80*100});
  renderAssessment('co2Assessment','co2Meter',c==null?{label:'รอข้อมูล',detail:'เตือน 1,000 ppm',pct:0}:{label:c<800?'การระบายอากาศดี':c<1000?'ควรติดตาม':c<1300?'ควร Boost ลม':'ถึง Critical band',detail:`${fmt(c,0)} ppm`,level:c<800?'good':c<1000?'warn':'bad',pct:(c-400)/900*100});
  renderAssessment('pmsAssessment','pmsMeter',p==null?{label:'รอข้อมูล',detail:'อ้างอิง PM2.5',pct:0}:{label:p<=15?'ฝุ่นต่ำ':p<=35?'ควรติดตาม':'ฝุ่นสูง',detail:`PM2.5 ${fmt(p,0)} µg/m³`,level:p<=15?'good':p<=35?'warn':'bad',pct:p/75*100});
  renderAssessment('sgpAssessment','sgpMeter',v==null?{label:'รอข้อมูล',detail:'เทียบ Adaptive baseline',pct:0}:{label:v<80?'ต่ำกว่า Baseline':v<=150?'ใกล้ Baseline':'VOC เพิ่มขึ้น',detail:`VOC Index ${fmt(v,0)}`,level:v<=150?'good':'warn',pct:v/300*100});
}
function controllerSourceName(label=''){
  return String(label).replace('Hub 1 · USB','Pi5 Sensor Set 1 · USB').replace('Hub 2 · MQTT','ESP32 Air Sensor · MQTT');
}
function bcgIntegrityDevice(b={}){
  const connected=!!b.connected,age=Number(b.analysis_data_age_s??b.data_age_s);
  const stale=!!b.stale||(Number.isFinite(age)&&age>15);
  return {model:'LSM-800-T · BCG',status:!connected?'offline':stale?'stale':b.error?'fault':'live',source_label:'Pi5 · BCG Serial',data_age_s:Number.isFinite(age)?age:null};
}
function bcgIntegrityValue(b={}){
  const bed=BCG_STATUS_CONTROL_TH[Number(b.status_code)]||b.status_text||'รอ Bed Status';
  return `${bed} · HR ${fmt(b.heart_rate_bpm,0)} BPM · RR ${fmt(b.respiration_rate,1)} ครั้ง/นาที · ${b.analysis_valid?'ผ่าน analysis':'รอ physiology'}`;
}
function renderSensorIntegrity(e,b={}){
  const devices=e.devices||{},root=document.getElementById('sensorIntegrityRows');if(!root)return;root.innerHTML='';
  const rows=Object.entries(sensorUi).map(([key,ui])=>({key,ui,device:devices[key]||{model:key,status:'offline'},value:ui.value(e)}));
  rows.push({key:'bcg',ui:{icon:'BCG'},device:bcgIntegrityDevice(b),value:bcgIntegrityValue(b)});
  rows.forEach(({key,ui,device:d,value})=>{const row=document.createElement('div');row.className=`integrity-row ${d.status||'offline'}`;row.dataset.sensor=key;row.innerHTML=`<div class="integrity-icon">${ui.icon}</div><div class="integrity-main"><b>${d.model||key}</b><span>${controllerSourceName(d.source_label||'ไม่ทราบ Source')} · ${value}</span></div><div class="integrity-state"><b>${sensorStatusTh[d.status]||d.status}</b><span>${d.data_age_s==null?'ไม่มีเวลา packet':`${Number(d.data_age_s).toFixed(1)}s ago`}</span></div>`;root.appendChild(row);});
  const total=rows.length,live=rows.filter(row=>row.device.status==='live').length,chip=document.getElementById('integrityChip');document.getElementById('integrityHeadline').textContent=`Sensor พร้อม ${live}/${total} ตัว`;document.getElementById('integrityDetail').textContent=live===total?'ทุก Sensor ส่งข้อมูลสด · ค่าหลักครบทุกอุปกรณ์':'ตรวจแถวที่ไม่เป็น Live และเวลา packet ก่อนใช้งาน';chip.className=`status-chip ${live===total?'success':live?'warning':'danger'}`;chip.textContent=live===total?'ALL LIVE':live?'DEGRADED':'OFFLINE';
}
function renderEnvironmentSensors(raw,e={},h2={},b={}){
  const env=raw?.devices?raw:legacyEnvironment(e,h2);
  [['temperature',env.temperature_c,1],['humidity',env.humidity_rh,1],['lux',env.lux,env.lux!=null&&env.lux<10?1:0],['co2',env.co2_ppm,0],['pm1',env.pm1_0_ug_m3,0],['pm25',env.pm2_5_ug_m3,0],['pm10',env.pm10_ug_m3,0],['vocIndex',env.voc_index,0],['vocRaw',env.sgp40_raw,0]].forEach(([id,value,d])=>document.getElementById(id).textContent=fmt(value,d));
  const soundMetric=soundDisplayMetric(env);document.getElementById('sound').textContent=fmt(soundMetric.value,soundMetric.digits);document.getElementById('soundUnit').textContent=soundMetric.unit;
  Object.entries(env.devices||{}).forEach(([key,device])=>setSensorDeviceState(key,device));renderSensorAssessments(env);renderSensorIntegrity(env,b);
  const live=Number(env.live_count)||0,total=Number(env.total_count)||6,status=document.getElementById('environmentStatus');status.className=`status-chip ${live===total?'success':live?'warning':'danger'}`;status.textContent=live===total?`Sensor ${live}/${total} · Live`:live?`Sensor ${live}/${total} · Degraded`:'Sensor offline';
  const ages=Object.values(env.devices||{}).map(d=>Number(d.data_age_s)).filter(Number.isFinite),latest=ages.length?Math.max(...ages):null;document.getElementById('environmentFreshness').textContent=latest==null?'ยังไม่มี packet':`packet เก่าสุด ${latest.toFixed(1)} วินาที`;
  return env;
}
function fmtUptime(s){
  if (s==null) return '--';
  const h = Math.floor(s/3600), m = Math.floor((s%3600)/60);
  return h > 0 ? `${h} ชม. ${m} น.` : `${m} นาที`;
}
function setPill(id, ok, labelOk, labelBad){
  const el = document.getElementById(id);
  el.className = 'pill ' + (ok ? 'good' : 'bad');
  el.innerHTML = `<span class="dot"></span>${ok ? labelOk : labelBad}`;
}

function percentile(sorted, p){
  if (!sorted.length) return 0;
  const i = (sorted.length-1)*p, lo = Math.floor(i), hi = Math.ceil(i);
  return sorted[lo] + (sorted[hi]-sorted[lo])*(i-lo);
}
function updateBCGWave(b={}){
  const packetCount = Number.isFinite(Number(b.packets)) ? Number(b.packets) : null;
  if (packetCount != null && bcgWave.lastPacketCount != null && packetCount < bcgWave.lastPacketCount){
    bcgWave.samples = [];
  }
  if (packetCount != null && packetCount !== bcgWave.lastPacketCount && Array.isArray(b.samples)){
    const clean = b.samples.map(Number).filter(Number.isFinite);
    bcgWave.samples.push(...clean);
    if (bcgWave.samples.length > bcgWave.maxSamples){
      bcgWave.samples.splice(0, bcgWave.samples.length-bcgWave.maxSamples);
    }
  }
  bcgWave.lastPacketCount = packetCount;
  return bcgWave.samples;
}
function bcgStatusExplanation(b, stats={}){
  const dynamicRange=stats.dynamicRange||0, saturated=!!stats.saturated;
  if (!b.connected) return ['ไม่มีสัญญาณล่าสุด', 'ตรวจการเชื่อมต่อเซ็นเซอร์และตำแหน่งใต้ที่นอนก่อนตีความค่า'];
  const status = Number(b.status_code);
  if (status === 1) return ['ไม่พบคนนอนบนเตียง', 'กราฟช่วงนี้ไม่ควรใช้แปล Heart Rate หรือการหายใจ'];
  if (status === 2) return ['พบการขยับตัว', 'แรงจากการเคลื่อนไหวรบกวน BCG ได้ ควรรอให้นิ่งก่อนอ่านแนวโน้ม HR/RR'];
  if (status === 3) return ['สัญญาณการหายใจอ่อน', 'เป็นสถานะจากอุปกรณ์ ไม่ใช่การแจ้งเตือนทางการแพทย์ ควรตรวจตำแหน่งเซ็นเซอร์และการสัมผัสกับที่นอน'];
  if (status === 4) return ['พบวัตถุน้ำหนักบนเตียง', 'อุปกรณ์ยังไม่ยืนยันว่าเป็นคนนอน จึงไม่ควรแปล HR/RR'];
  if (status === 5) return ['อุปกรณ์ระบุรูปแบบคล้ายเสียงกรน', 'เป็น flag จากเซ็นเซอร์สำหรับการทดสอบเท่านั้น ไม่ใช้วินิจฉัยการกรนหรือภาวะหยุดหายใจ'];
  if (status === 0 && b.heart_rate_bpm != null && b.respiration_rate != null){
    if (saturated || dynamicRange >= 60000) return ['รับสัญญาณขณะอยู่บนเตียง', 'Raw BCG แตะขอบช่วง int16 (-32768/32767) จึงเกิด span 65535; จัดเป็นสัญญาณ saturation/ค่ากระโดดและไม่ใช้ตีความแอมพลิจูด'];
    return ['รับสัญญาณขณะอยู่บนเตียง', `Signal span ${Math.round(dynamicRange)} counts คำนวณจาก percentile 5–95 ของ BCG raw 300 จุดล่าสุด`];
  }
  return ['รับข้อมูลจากเซ็นเซอร์แล้ว', 'ข้อมูลสรุปยังไม่ครบ ควรรอ HR/RR และหลาย packet ต่อเนื่องก่อนตีความ'];
}
function renderBCGReading(b, stats){
  const [title, detail] = bcgStatusExplanation(b, stats);
  const root = document.getElementById('bcgReading');
  root.textContent = '';
  const titleEl = document.createElement('span');
  titleEl.className = 'reading-title'; titleEl.textContent = title;
  root.append(titleEl, document.createTextNode(` · ${detail}`));
  document.getElementById('bcgChartRange').textContent = stats.count
    ? `${stats.count} จุดล่าสุด · P5–P95 ${Math.round(stats.dynamicRange)} counts${stats.saturated ? ' · SATURATED' : ''}` : 'รอข้อมูล';
}

/* ---- BCG waveform: rolling packets, robust zero-centred relative scale ---- */
function drawBCG(samples=[]){
  const c = document.getElementById('bcgCanvas');
  const dpr = window.devicePixelRatio || 1;
  const w = c.clientWidth, h = c.clientHeight;
  if (c.width !== Math.round(w*dpr) || c.height !== Math.round(h*dpr)){
    c.width = Math.round(w*dpr); c.height = Math.round(h*dpr);
  }
  const x = c.getContext('2d');
  x.setTransform(dpr,0,0,dpr,0,0);
  x.clearRect(0,0,w,h);
  x.strokeStyle = '#0a2c40'; x.lineWidth = 1;
  for (let gy = h/4; gy < h; gy += h/4){ x.beginPath(); x.moveTo(0,gy); x.lineTo(w,gy); x.stroke(); }
  for (let gx = w/8; gx < w; gx += w/8){ x.beginPath(); x.moveTo(gx,0); x.lineTo(gx,h); x.stroke(); }
  if (samples.length < 2) return {count:samples.length,dynamicRange:0};
  const sorted = [...samples].sort((a,b)=>a-b);
  const centre = percentile(sorted,.5);
  const low = percentile(sorted,.05), high = percentile(sorted,.95);
  const halfRange = Math.max(Math.abs(high-centre), Math.abs(low-centre), 1);
  const min = centre-halfRange, max = centre+halfRange;
  const pad = h*0.08;
  const zeroY = (h-pad) - ((centre-min)/(max-min)) * (h-pad*2);
  x.save(); x.setLineDash([5,5]); x.strokeStyle='#31536a'; x.beginPath();
  x.moveTo(0,zeroY); x.lineTo(w,zeroY); x.stroke(); x.restore();
  const grad = x.createLinearGradient(0,0,w,0);
  grad.addColorStop(0,'#0fa8c9'); grad.addColorStop(.5,'#19e3ff'); grad.addColorStop(1,'#8ef2ff');
  x.strokeStyle = grad; x.lineWidth = 2; x.lineJoin = 'round';
  x.shadowColor = '#19e3ff66'; x.shadowBlur = 8;
  x.beginPath();
  samples.forEach((v,i)=>{
    const px = i * (w/(samples.length-1));
    const clipped = Math.max(min, Math.min(max, v));
    const py = (h-pad) - ((clipped-min)/(max-min)) * (h - pad*2);
    i === 0 ? x.moveTo(px,py) : x.lineTo(px,py);
  });
  x.stroke();
  x.shadowBlur = 0;
  return {count:samples.length,dynamicRange:high-low,centre,saturated:samples.some(v=>v<=-32768||v>=32767)};
}

/* ---- แนวโน้ม 10 นาที: HR/RR + แถบบนเตียง/ขยับตัว (จาก /api/bcg/trend) ---- */
function drawBcgTrend(data){
  const c = document.getElementById('bcgTrend');
  if (!c) return;
  const dpr = window.devicePixelRatio || 1;
  const w = c.clientWidth, h = c.clientHeight;
  if (w && (c.width !== Math.round(w*dpr) || c.height !== Math.round(h*dpr))){
    c.width = Math.round(w*dpr); c.height = Math.round(h*dpr);
  }
  const x = c.getContext('2d');
  x.setTransform(dpr,0,0,dpr,0,0);
  x.clearRect(0,0,w,h);
  const buckets = data.buckets || [];
  const n = buckets.length;
  if (!n) return;
  const bw = w / n;
  // พื้นหลัง: เทา = ไม่อยู่บนเตียง/ไม่มีข้อมูล · ขีดส้มล่าง = ขยับตัว
  buckets.forEach((b,i)=>{
    if (!b.onbed){
      x.fillStyle = '#28303f55';
      x.fillRect(i*bw, 0, bw+0.5, h);
    }
    if (b.move != null && b.move >= 0.15){
      x.fillStyle = '#ffb02e';
      x.fillRect(i*bw, h-4, bw+0.5, 3);
    }
  });
  x.strokeStyle = '#0a2c40'; x.lineWidth = 1;
  for (let gy = h/3; gy < h; gy += h/3){ x.beginPath(); x.moveTo(0,gy); x.lineTo(w,gy); x.stroke(); }
  const plot = (key, color)=>{
    const vals = buckets.map(b=>b[key]);
    const nums = vals.filter(v=>typeof v === 'number');
    if (nums.length < 2) return null;
    let mn = Math.min(...nums), mx = Math.max(...nums);
    if (mx === mn) mx = mn + 1;
    x.strokeStyle = color; x.lineWidth = 2; x.lineJoin = 'round';
    x.beginPath(); let started = false;
    vals.forEach((v,i)=>{
      if (typeof v !== 'number'){ started = false; return; }
      const px = i*bw + bw/2;
      const py = (h-12) - ((v-mn)/(mx-mn)) * (h-24);
      if (!started){ x.moveTo(px,py); started = true; } else x.lineTo(px,py);
    });
    x.stroke();
    return {mn, mx};
  };
  const hrR = plot('hr', '#ffb02e');
  const rrR = plot('rr', '#19e3ff');
  const parts = [];
  if (hrR) parts.push(`HR ${hrR.mn}–${hrR.mx} ครั้ง/นาที (BPM)`);
  if (rrR) parts.push(`RR ${rrR.mn}–${rrR.mx} ครั้ง/นาที`);
  document.getElementById('bcgTrendRange').textContent =
    parts.length ? parts.join(' · ') : 'ยังไม่มีสัญญาณจากคนบนเตียงในช่วง 10 นาที';
}

async function fetchBcgTrend(){
  if(!currentPrincipal||(currentPrincipal.role!=='admin'&&!authPod.owns_active_session))return;
  try {
    const r = await fetch('/api/bcg/trend?minutes=10');
    if (r.ok) drawBcgTrend(await r.json());
  } catch {}
}
setInterval(fetchBcgTrend, 10000);

const calibrationReferenceDraft={};
const calibrationBiasDraft={};
let calibrationInspectorState=null;

function calibrationNumber(value,step=0.1){
  if(value===null||value===undefined||value==='')return '--';
  const number=Number(value);
  if(!Number.isFinite(number))return '--';
  return Math.abs(Number(step)||0.1)>=1?String(Math.round(number)):number.toFixed(2).replace(/\.00$/,'').replace(/(\.\d)0$/,'$1');
}

function calibrationReferenceChanged(metric,input){
  calibrationReferenceDraft[metric]=input.value;
  const channel=(calibrationInspectorState?.channels||[]).find(item=>item.metric===metric);
  const raw=Number(channel?.raw),reference=Number(input.value);
  if(!Number.isFinite(raw)||!Number.isFinite(reference))return;
  const suggested=reference-raw;
  calibrationBiasDraft[metric]=String(Math.round(suggested*1000)/1000);
  const biasInput=document.querySelector(`input[data-calibration-bias="${metric}"]`);
  if(biasInput)biasInput.value=calibrationBiasDraft[metric];
}

function calibrationBiasChanged(metric,input){calibrationBiasDraft[metric]=input.value;}

function escapeMarkup(value=''){
  const entities={'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'};
  return String(value).replace(/[&<>"']/g,character=>entities[character]);
}

function adaptiveValue(value,digits=1){
  const number=Number(value);
  return Number.isFinite(number)?number.toFixed(digits).replace(/\.0$/,''):'--';
}

function adaptiveComparison(metric={}){
  const labels={near_reference:'ใกล้ Reference',above_reference:'สูงกว่า Reference',below_reference:'ต่ำกว่า Reference',no_reference:'กำลังเรียนรู้',no_live_value:'ไม่มีข้อมูลสด'};
  const tone={near_reference:'near',above_reference:'above',below_reference:'below',no_reference:'unknown',no_live_value:'missing'}[metric.comparison]||'unknown';
  const delta=metric.delta==null?Number.NaN:Number(metric.delta);
  const suffix=Number.isFinite(delta)?` · ${delta>0?'+':''}${adaptiveValue(delta,1)} ${metric.unit||''}`:'';
  return {label:`${labels[metric.comparison]||metric.comparison||'รอข้อมูล'}${suffix}`,tone};
}

function adaptiveModeLabel(mode){
  return ({sleep:'Overnight Recovery',overnight:'Overnight Recovery',nap_recovery:'Nap & Refresh',short_nap:'Nap & Refresh',cycle_nap:'Nap & Refresh'})[mode]||mode||'ยังไม่เลือก Mode';
}

function adaptiveReferenceScope(scope){
  return ({prior_completed_same_mode_sessions:'ส่วนบุคคล · โหมดเดียวกัน',qualified_overnight_reference:'ส่วนบุคคล · Overnight',sensor_owned:'Sensor baseline',none:'ยังไม่มี Reference'})[scope]||`Reference · ${scope||'กำลังเรียนรู้'}`;
}

function renderAdaptiveFeatures(data={}){
  const root=document.getElementById('adaptiveFeatureRows');if(!root)return;
  const rows=Array.isArray(data.live_features)?data.live_features:[];
  if(!rows.length){root.innerHTML='<div class="adaptive-empty">กำลังรอ Adaptive dataset</div>';return;}
  root.innerHTML=rows.map(metric=>{
    const comparison=adaptiveComparison(metric),window=metric.window||{};
    const current=metric.value==null?'--':`${adaptiveValue(metric.value,metric.key==='co2'?0:1)} ${escapeMarkup(metric.unit||'')}`;
    const reference=metric.reference==null?'กำลังเรียนรู้':`${adaptiveValue(metric.reference,metric.key==='co2'?0:1)} ${escapeMarkup(metric.unit||'')}`;
    const mean=window.mean==null?'--':`${adaptiveValue(window.mean,metric.key==='co2'?0:1)} ${escapeMarkup(metric.unit||'')}`;
    const coverage=window.coverage_pct==null?'':` · ${adaptiveValue(window.coverage_pct,0)}%`;
    const scope=adaptiveReferenceScope(metric.reference_scope);
    return `<article class="adaptive-feature-row ${comparison.tone}"><div><b>${escapeMarkup(metric.label)}</b><small>${escapeMarkup(metric.live_source||'ไม่ทราบ Source')}</small><i class="adaptive-reference-scope">${escapeMarkup(scope)}</i></div><span><em>ค่าปัจจุบัน</em><strong>${current}</strong></span><span><em>Reference</em><strong>${reference}</strong></span><span><em>เฉลี่ย 5 นาที</em><strong>${mean}${coverage}</strong></span><mark>${escapeMarkup(comparison.label)}</mark></article>`;
  }).join('');
}

function renderAdaptiveDecision(data={}){
  const recommendations=(data.candidate_recommendations||[]).filter(item=>item&&item.level!=='stable');
  const shown=recommendations.length?recommendations:(data.candidate_recommendations||[]).slice(0,3);
  const root=document.getElementById('adaptiveRecommendations');
  root.innerHTML=shown.length?shown.slice(0,6).map(item=>`<article class="${escapeMarkup(item.level||'stable')}"><b>${escapeMarkup(item.title||item.domain||'ข้อเสนอ')}</b><span>${escapeMarkup(item.candidate||item.evidence||'คงค่าปัจจุบันและติดตาม')}</span><small>OBSERVE ONLY · ไม่ได้ส่งคำสั่ง</small></article>`).join(''):'<div class="adaptive-empty">ยังไม่มีคำแนะนำ</div>';
  const blockers=Array.isArray(data.blockers)?data.blockers:[];
  document.getElementById('adaptiveBlockers').innerHTML=blockers.map(item=>`<span>${escapeMarkup(item.message||item.code)}</span>`).join('');
  const sleep=data.sleep_estimator||{};
  document.getElementById('adaptiveSleepContext').textContent=`Sleep State · ${String(sleep.confirmed_state||sleep.state||'--').toUpperCase()} · ${sleep.provisional?'Provisional':sleep.confidence||'รอหลักฐาน'}`;
}

function renderAdaptiveDevices(data={}){
  const root=document.getElementById('adaptiveDeviceState'),devices=data.device_intent||{};if(!root)return;
  const air=devices.aircon||{},music=devices.music||{},bed=devices.bed||{};
  const items=[
    ['แอร์',air.connected?(air.power?'เปิด':'ปิด'):'Offline',`เป้าหมาย ${air.desired_temperature_c??'--'}°C · ลมอ้างอิง ${air.fan_level_reference??'--'}`],
    ['เสียง',music.playing&&!music.paused?'กำลังเล่น':music.paused?'พัก':'หยุด',`${music.volume_pct??'--'}% · ${music.mode||'--'}`],
    ['เตียง',bed.connected?(bed.active_command||'พร้อม'):'Offline',bed.adaptive_motion_allowed?'Adaptive allowed':'ผู้ใช้ควบคุมเท่านั้น'],
    ['Safety',data.control_policy?.safety_supervisor_authoritative?'Authoritative':'ผิดปกติ','มีสิทธิ์เหนือ Model เสมอ'],
  ];
  root.innerHTML=items.map(item=>`<article><span>${escapeMarkup(item[0])}</span><b>${escapeMarkup(item[1])}</b><small>${escapeMarkup(item[2])}</small></article>`).join('');
}

function renderAdaptiveVersions(data={}){
  const root=document.getElementById('adaptiveVersionRows');if(!root)return;
  const versions=data.versions||{};
  root.innerHTML=Object.entries(versions).map(([key,value])=>`<div><span>${escapeMarkup(key.replaceAll('_',' '))}</span><b>${escapeMarkup(value??'MISSING')}</b></div>`).join('');
  document.getElementById('adaptiveGuardrails').textContent=(data.guardrails||[]).join(' · ');
}

function renderAdaptiveLearning(data={}){
  const root=document.getElementById('adaptiveMonitorCard');if(!root)return;
  const session=data.session||{},quality=data.data_quality||{},baseline=data.baseline||{},versions=data.versions||{};
  const valid=data.schema_version&&data.mode==='shadow'&&data.control_policy?.automatic_actuation===false;
  root.classList.toggle('contract-error',!valid);
  document.getElementById('adaptiveSessionState').textContent=session.recording?'กำลังบันทึก':session.active?'รอเริ่มบันทึก':'ยังไม่มี Session';
  document.getElementById('adaptiveSessionMeta').textContent=`${adaptiveModeLabel(session.rest_mode)}${session.session_id?` · ${String(session.session_id).slice(0,8)}`:''}`;
  document.getElementById('adaptiveFrameState').textContent=quality.sensor_frame_stale?'STALE':versions.sensor_frame_sequence==null?'รอ Frame':`SEQ ${versions.sensor_frame_sequence}`;
  document.getElementById('adaptiveFrameMeta').textContent=`อายุ ${quality.sensor_frame_age_s==null?'--':adaptiveValue(quality.sensor_frame_age_s,1)}s · ทุก ${data.cadence?.sensor_frame_s||10}s`;
  const referenceCount=Number(baseline.reference_metrics)||0;
  document.getElementById('adaptiveBaselineState').textContent=referenceCount?`มี Reference ${referenceCount} ค่า`:baseline.status==='learning'?'กำลังเรียนรู้':'ยังไม่มี Reference';
  document.getElementById('adaptiveBaselineMeta').textContent=`คำแนะนำ ${baseline.sessions_used||0}/${baseline.minimum_sessions||3} Sessions · Sleep State ${baseline.active_stage_source==='personal'?'Personal':'Age + Gender'}`;
  document.getElementById('adaptiveQualityState').textContent=quality.vital_pair_live?'HR/RR พร้อม':'HR/RR ไม่ครบ';
  document.getElementById('adaptiveQualityMeta').textContent=`Environment ${quality.environment_live||0}/${quality.environment_total||6} · Window ${quality.window_coverage_pct??0}%`;
  document.getElementById('adaptiveWindowMeta').textContent=`Rolling window · ${Math.round((data.cadence?.rolling_window_s||300)/60)} นาที · ${quality.window_samples||0} จุด`;
  const activeSession=current.session||{};
  const owner=document.getElementById('adaptiveReferenceOwner');
  if(owner)owner.textContent=activeSession.active
    ?`${monitorMaskedAccount(activeSession)} · ${adaptiveModeLabel(session.rest_mode)} · Reference แยกตามข้อมูลแต่ละค่า`
    :'ยังไม่มีผู้ใช้งานใน Session · ระบบจะไม่ข้ามข้อมูลระหว่างบัญชี';
  document.getElementById('adaptiveDecisionSummary').textContent=data.summary||'กำลังรอข้อมูล';
  document.getElementById('adaptiveEvaluationTime').textContent=data.generated_at?new Date(data.generated_at).toLocaleTimeString('th-TH',{hour12:false}):'--';
  renderAdaptiveFeatures(data);renderAdaptiveDecision(data);renderAdaptiveDevices(data);renderAdaptiveVersions(data);
}

function acousticPhaseStatus(status='planned'){
  return ({in_progress:'กำลังทำ',planned:'วางแผน',approved:'ผ่านแล้ว',blocked:'ติดเงื่อนไข'})[status]||status;
}

function acousticFeatureLabel(key=''){
  return ({feature_coverage:'Coverage',clip_ratio:'Clipping',crest_factor:'Crest factor',transient_count:'Transient',spectral_bands:'Spectral bands',spectral_centroid:'Centroid',spectral_flatness:'Flatness',periodicity:'Periodicity',modulation_index:'Modulation'})[key]||key.replaceAll('_',' ');
}

function renderAcousticIntelligence(data={}){
  const root=document.getElementById('acousticIntelligenceCard');if(!root)return;
  const level=data.level||{},aggregation=data.aggregation||{},validation=data.validation||{};
  const value=level.sound_dba==null?Number.NaN:Number(level.sound_dba);
  const packetAverage=aggregation.packet_energy_average_dba==null?Number.NaN:Number(aggregation.packet_energy_average_dba);
  const valid=Number.isFinite(value)&&level.status==='valid';
  root.classList.toggle('level-unavailable',!valid);
  document.getElementById('acousticStatusBadge').textContent='LEVEL ONLY · SHADOW';
  document.getElementById('acousticLevel').textContent=valid?`${value.toFixed(1)} dBA`:'-- dBA';
  document.getElementById('acousticLevelMeta').textContent=valid
    ?`ESP32 direct${Number.isFinite(packetAverage)?` · เฉลี่ย packet ${packetAverage.toFixed(1)} dBA`:''} · ${aggregation.sample_count||0} จุด`
    :`ยังไม่มีระดับเสียงที่ใช้ได้ · ${level.status||data.status||'unavailable'}`;
  document.getElementById('acousticClassification').textContent='ยังไม่ประเมินประเภทเสียง';
  document.getElementById('acousticClassificationMeta').textContent='ต้องมี DSP feature ก่อน · ไม่เดาจาก dBA ค่าเดียว';

  const phases=Array.isArray(validation.phases)?validation.phases:[];
  const active=phases.find(item=>item.status==='in_progress')||phases[0]||{};
  document.getElementById('acousticProofPhase').textContent=active.phase?`${active.phase} · ${acousticPhaseStatus(active.status)}`:'รอ Validation Plan';
  document.getElementById('acousticProofMeta').textContent=active.title||'ยังไม่มีข้อมูลแผนพิสูจน์';

  const groups=Array.isArray(data.candidate_label_groups)?data.candidate_label_groups:[];
  const candidateRoot=document.getElementById('acousticCandidateGroups');
  candidateRoot.innerHTML=groups.length?groups.map(group=>`<section><h4>${escapeMarkup(group.display_name||group.key)}</h4><div>${(group.labels||[]).map(label=>`<span title="สถานะ: ${escapeMarkup(label.proof_status||'planned')}">${escapeMarkup(label.display_name||label.key)}<small>กำลังพิสูจน์</small></span>`).join('')}</div></section>`).join(''):'<div class="acoustic-empty">ยังไม่มี Candidate Registry</div>';

  document.getElementById('acousticValidationSteps').innerHTML=phases.slice(0,4).map(item=>`<span class="${escapeMarkup(item.status||'planned')}"><b>${escapeMarkup(item.phase)}</b>${escapeMarkup(item.title)}<small>${escapeMarkup(acousticPhaseStatus(item.status))}</small></span>`).join('');
  document.getElementById('acousticGuardrail').textContent='ไม่ส่งหรือเก็บ Raw audio · ไม่ถอดคำ/ระบุตัวบุคคล · ไม่เปลี่ยน Sleep State, Sleep Score, Recovery Score หรือ Control';

  const pipeline=document.getElementById('acousticPipelineRows');
  pipeline.innerHTML=phases.map(item=>`<article class="${escapeMarkup(item.status||'planned')}"><b>${escapeMarkup(item.phase)}</b><div><strong>${escapeMarkup(item.title)}</strong><span>${escapeMarkup(item.exit_gate||'รอเกณฑ์ผ่าน')}</span></div><em>${escapeMarkup(acousticPhaseStatus(item.status))}</em></article>`).join('')||'<div class="acoustic-empty">ยังไม่มี Pipeline</div>';
  const missing=Array.isArray(data.evidence?.missing)?data.evidence.missing:[];
  document.getElementById('acousticMissingFeatures').innerHTML=missing.map(item=>`<span>${escapeMarkup(acousticFeatureLabel(item))}</span>`).join('')||'<span>รอ Feature Contract</span>';
  const provenance=data.provenance||{};
  document.getElementById('acousticProvenance').innerHTML=`<div><span>Sound source</span><b>${escapeMarkup(provenance.sound_source||'--')}</b></div><div><span>Firmware</span><b>${escapeMarkup(provenance.firmware_version||'ยังไม่ยืนยัน')}</b></div><div><span>Feature schema</span><b>${escapeMarkup(provenance.feature_schema_version||'ยังไม่มี')}</b></div><div><span>Classifier</span><b>${escapeMarkup(provenance.classifier_version||'ยังไม่มี')}</b></div><div><span>Protocol</span><b>${escapeMarkup(validation.protocol_id||'--')}</b></div><div><span>BCG Snoring flag</span><b>หลักฐานแยก · ไม่ใช่ไมค์</b></div>`;
  document.getElementById('acousticContractVersion').textContent=data.contract_version||'contract --';
}

function renderCalibrationInspector(data,{force=false}={}){
  calibrationInspectorState=data;
  const root=document.getElementById('calibrationInspector');
  if(!root)return;
  if(!force&&root.contains(document.activeElement))return;
  const sessionNote=document.getElementById('calibrationSessionNote');
  if(sessionNote){
    sessionNote.className=`calibration-session-note${data.session_active?' active':''}`;
    sessionNote.textContent=data.session_active
      ? '⚠ มี Session ทำงานอยู่ · ค่าปรับใหม่มีผลกับ Packet หลังจากกด Apply เท่านั้น และไม่แก้ข้อมูลย้อนหลัง'
      : '✓ ZEEP ว่าง · พร้อมเทียบเครื่องอ้างอิงและปรับค่าที่อนุญาต';
  }
  const grouped=new Map();
  (data.channels||[]).forEach(channel=>{
    if(!grouped.has(channel.device))grouped.set(channel.device,[]);
    grouped.get(channel.device).push(channel);
  });
  if(!grouped.size){root.innerHTML='<div class="mini">ยังไม่มีข้อมูล Sensor สำหรับ Calibration</div>';return;}
  root.innerHTML=[...grouped.entries()].map(([device,channels])=>{
    const primary=channels[0]||{},state=primary.status||'offline';
    const age=primary.data_age_s==null?NaN:Number(primary.data_age_s),source=primary.source||'ไม่ทราบ Source';
    const channelHtml=channels.map(channel=>{
      const metric=channel.metric,step=Number(channel.step)||0.1;
      const raw=calibrationNumber(channel.raw,step),bias=calibrationNumber(channel.bias,step),output=calibrationNumber(channel.calibrated,step);
      const unit=channel.unit||'',rawUnit=channel.raw_unit||unit,parameterUnit=channel.parameter_unit||unit;
      const isSoundEstimate=metric==='sound_dba_est';
      const outputLabel=isSoundEstimate?'DIRECT':'CALIBRATED';
      const parameterLabel='NEW BIAS';
      const genericValues=`<div class="calibration-values">
        <div class="calibration-value"><span>RAW</span><b>${raw}</b><small>${rawUnit}</small></div>
        <div class="calibration-value"><span>${channel.bias_label||'BIAS'}</span><b>${channel.editable?(Number(channel.bias)>=0?'+':'')+bias:'LOCK'}</b><small>${channel.editable?parameterUnit:channel.bias_source||'algorithm'}</small></div>
        <div class="calibration-value output"><span>${outputLabel}</span><b>${output}</b><small>${unit}</small></div>
      </div>`;
      const values=isSoundEstimate?`<div class="calibration-values sound-direct-value">
        <div class="calibration-value output"><span>ESP32 DIRECT</span><b>${output}</b><small>${unit}</small></div>
      </div>`:genericValues;
      if(!channel.editable){
        return `<section class="calibration-channel"><div class="calibration-channel-title"><b>${channel.label}</b><span>${metric}</span></div>${values}<div class="calibration-lock">🔒 ${channel.lock_reason||'ค่าจาก Algorithm แสดงแบบ read-only'}</div></section>`;
      }
      const referenceDraft=calibrationReferenceDraft[metric]??'';
      const biasDraft=calibrationBiasDraft[metric]??channel.bias;
      return `<section class="calibration-channel"><div class="calibration-channel-title"><b>${channel.label}</b><span>${metric}</span></div>${values}
        <div class="calibration-tools">
          <div class="calibration-input"><label>REFERENCE · ${unit}</label><input type="number" inputmode="decimal" step="${step}" value="${referenceDraft}" placeholder="Meter" oninput="calibrationReferenceChanged('${metric}',this)"></div>
          <div class="calibration-input"><label>${parameterLabel} · ${channel.bias_min}…${channel.bias_max}</label><input type="number" inputmode="decimal" data-calibration-bias="${metric}" min="${channel.bias_min}" max="${channel.bias_max}" step="${step}" value="${biasDraft}" oninput="calibrationBiasChanged('${metric}',this)"></div>
          <button class="calibration-apply" onclick="applyCalibrationBias('${metric}',this)">APPLY</button>
        </div></section>`;
    }).join('');
    const soundDevice=channels.some(channel=>channel.metric==='sound_dba_est');
    const genericState=soundDevice?'':`<span class="calibration-live ${state}">${state}</span>`;
    return `<article class="calibration-device${soundDevice?' sound-calibration-device':''}"><header class="calibration-device-head"><div><strong>${device}</strong><small>${source}${Number.isFinite(age)?` · ${age.toFixed(1)}s ago`:''}</small></div>${genericState}</header>${channelHtml}</article>`;
  }).join('');
}

async function fetchCalibrationInspector(btn,force=false){
  const run=async()=>{
    let response;
    try{response=await fetch('/api/admin/calibration',{headers:authenticatedHeaders()});}
    catch{toast('โหลด Sensor calibration ไม่ได้','error');return null;}
    if(!response.ok){if(response.status!==401)toast(`Calibration: HTTP ${response.status}`,'error');return null;}
    const data=await response.json();renderCalibrationInspector(data,{force});return data;
  };
  return btn?withBusy(btn,run):run();
}

async function applyCalibrationBias(metric,btn){
  const channel=(calibrationInspectorState?.channels||[]).find(item=>item.metric===metric);
  const bias=Number(calibrationBiasDraft[metric]??channel?.bias);
  const rawReference=calibrationReferenceDraft[metric];
  const reference=rawReference===''||rawReference==null?null:Number(rawReference);
  if(!channel?.editable){toast('Sensor channel นี้เป็น Algorithm locked','error');return;}
  const parameterName='Bias';
  const parameterPrefix=bias>=0?'+':'';
  if(!Number.isFinite(bias)||bias<Number(channel.bias_min)||bias>Number(channel.bias_max)){toast(`${parameterName} ต้องอยู่ระหว่าง ${channel.bias_min} ถึง ${channel.bias_max}`,'error');return;}
  if(reference!==null&&!Number.isFinite(reference)){toast('ค่า Reference ไม่ถูกต้อง','error');return;}
  return withBusy(btn,async()=>{
    const result=await post('/api/admin/calibration/bias',{metric,bias,reference_value:reference});
    if(!result)return null;
    delete calibrationBiasDraft[metric];delete calibrationReferenceDraft[metric];
    renderCalibrationInspector(result.calibration,{force:true});
    toast(`${channel.device} · ${channel.label}: บันทึก ${parameterName} ${parameterPrefix}${bias} แล้ว`,'ok',3000);
    return result;
  });
}

async function refreshPacketInspector(btn){
  return withBusy(btn,async()=>{
    const [calibration,raw]=await Promise.all([fetchCalibrationInspector(null,true),fetchRawPackets()]);
    return calibration||raw;
  });
}

function fmtPacketTime(t){
  try { return new Date(t*1000).toLocaleTimeString('th-TH',{hour12:false}); } catch { return '--:--:--'; }
}
function rawByteField(i){
  if (i <= 4) return `Header Odata [${i}]`;
  if (i >= 5 && i <= 54) return `BCG sample ${Math.floor((i-5)/2)} · ${i%2 ? 'low byte' : 'high byte'}`;
  if (i === 55 || i === 56) return 'Reserved / undocumented';
  if (i >= 57 && i <= 61) return `Marker Bdata [${i-57}]`;
  if (i === 62) return 'Packet ID';
  if (i === 63) return 'Bed status code';
  if (i === 64) return 'HR raw · ครั้ง/นาที (BPM)';
  if (i === 65) return 'RR raw · หาร 10 = ครั้ง/นาที';
  return 'Unknown';
}
function rawAscii(v){ return v >= 32 && v <= 126 ? String.fromCharCode(v) : '·'; }
function renderRawPacket(p){
  const bytes=(p.raw_hex||'').trim().split(/\s+/).filter(Boolean).map(h=>parseInt(h,16));
  const statusText=BCG_STATUS_TH[p.status_code] || 'Unknown';
  const header=bytes.slice(0,5).map(rawAscii).join('');
  const marker=bytes.slice(57,62).map(rawAscii).join('');
  const sampleValues=p.samples||[];
  const sampleMin=sampleValues.length?Math.min(...sampleValues):null, sampleMax=sampleValues.length?Math.max(...sampleValues):null;
  const sampleMean=sampleValues.length?sampleValues.reduce((a,b)=>a+b,0)/sampleValues.length:null;
  const saturatedCount=sampleValues.filter(v=>v<=-32768||v>=32767).length;
  const sampleSpan=sampleValues.length?sampleMax-sampleMin:null;
  const headerOk=header==='Odata', markerOk=marker==='Bdata', lengthOk=bytes.length===66;
  const statusAnalysis={0:'ตรวจพบคนอยู่บนเตียง',1:'ไม่พบคนบนเตียง/ลุกออก',2:'ตรวจพบการขยับตัว',3:'สัญญาณการหายใจอ่อน',4:'ตรวจพบวัตถุน้ำหนักบนเตียง',5:'พบ flag รูปแบบคล้ายเสียงกรน'}[p.status_code]||'Status code ที่ยังไม่ได้กำหนดความหมาย';
  const samples=sampleValues.map((v,i)=>`<span class="${v<=-32768||v>=32767?'saturated':''}">#${String(i).padStart(2,'0')} · bytes ${5+i*2}–${6+i*2} = <b>${v}</b>${v<=-32768?' · LOW LIMIT':v>=32767?' · HIGH LIMIT':''}</span>`).join('');
  const rows=bytes.map((v,i)=>`<tr><td>${i}</td><td>0x${v.toString(16).padStart(2,'0').toUpperCase()}</td><td>${v}</td><td>${rawAscii(v)}</td><td>${rawByteField(i)}</td></tr>`).join('');
  return `<details class="raw-packet" open>
    <summary><strong>🕒 ${fmtPacketTime(p.t)}</strong><span>📦 Packet ${p.packet_id}</span><span>🏷 Code ${p.status_code}</span><span>♥ HR ${p.heart_rate ?? '--'} · 〰 RR ${p.respiration_rate ?? '--'}</span></summary>
    <div class="raw-fields">
      <div class="raw-field"><b>Timestamp</b>${p.t} · ${new Date(p.t*1000).toISOString()}</div>
      <div class="raw-field"><b>Frame length</b>${bytes.length} bytes</div>
      <div class="raw-field"><b>Header · bytes 0–4</b>${header}</div>
      <div class="raw-field"><b>Marker · bytes 57–61</b>${marker}</div>
      <div class="raw-field"><b>Packet ID · byte 62</b>${p.packet_id} · raw ${bytes[62]}</div>
      <div class="raw-field"><b>Status · byte 63</b>${p.status_code} · ${statusText}</div>
      <div class="raw-field"><b>HR · byte 64</b>raw ${bytes[64]} · ${p.heart_rate ?? '--'} ครั้ง/นาที (BPM)</div>
      <div class="raw-field"><b>RR · byte 65</b>raw ${p.respiration_raw ?? bytes[65]} · ${p.respiration_rate ?? '--'} ครั้ง/นาที</div>
      <div class="raw-field"><b>Reserved · bytes 55–56</b>${bytes[55]} / ${bytes[56]} · HEX ${bytes[55]?.toString(16).padStart(2,'0')} ${bytes[56]?.toString(16).padStart(2,'0')}</div>
      <div class="raw-field"><b>BCG payload</b>25 × int16 little-endian · bytes 5–54</div>
    </div>
    <div class="packet-analysis"><strong>🔎 Packet Analysis</strong><div class="analysis-grid">
      <div class="analysis-item"><span class="analysis-icon">✅</span><span class="analysis-label">Frame</span><span class="analysis-value">${lengthOk&&headerOk&&markerOk?'โครงสร้างถูกต้อง':'โครงสร้างไม่สมบูรณ์'}<br>Length ${bytes.length}/66 · Header ${headerOk?'OK':'ERROR'} · Marker ${markerOk?'OK':'ERROR'}</span></div>
      <div class="analysis-item"><span class="analysis-icon">🛏</span><span class="analysis-label">Bed Status</span><span class="analysis-value">Code ${p.status_code}<br>${statusAnalysis}</span></div>
      <div class="analysis-item"><span class="analysis-icon">♥</span><span class="analysis-label">HR</span><span class="analysis-value">${p.heart_rate==null?'ไม่มีค่าจากอุปกรณ์':p.heart_rate+' ครั้ง/นาที (BPM)'}<br>Raw byte ${bytes[64]??'--'}</span></div>
      <div class="analysis-item"><span class="analysis-icon">〰</span><span class="analysis-label">RR</span><span class="analysis-value">${p.respiration_rate==null?'ไม่มีค่าจากอุปกรณ์':p.respiration_rate+' ครั้ง/นาที'}<br>Raw byte ${p.respiration_raw??bytes[65]??'--'} ÷ 10</span></div>
      <div class="analysis-item"><span class="analysis-icon">📈</span><span class="analysis-label">BCG Stats</span><span class="analysis-value">Min ${sampleMin??'--'} · Max ${sampleMax??'--'}<br>Mean ${sampleMean==null?'--':sampleMean.toFixed(1)} · Span ${sampleSpan??'--'} counts</span></div>
      <div class="analysis-item"><span class="analysis-icon">${saturatedCount?'⚠️':'✅'}</span><span class="analysis-label">Signal Limit</span><span class="analysis-value">${saturatedCount?`<span class="warn">Saturated ${saturatedCount}/25 จุด<br>แตะขอบ int16 ไม่ใช้ span ตีความ</span>`:'ไม่พบ sample แตะขอบ int16'}</span></div>
      <div class="analysis-item"><span class="analysis-icon">↕</span><span class="analysis-label">Sample Sign</span><span class="analysis-value">บวก/ลบคือทิศทางเทียบ baseline ของ mechanical signal<br>ไม่ใช่ HR หรือ RR โดยตรง</span></div>
      <div class="analysis-item"><span class="analysis-icon">❓</span><span class="analysis-label">Bytes 55–56</span><span class="analysis-value">ยังไม่มีนิยามยืนยัน<br>แสดงค่าดิบโดยไม่เดาความหมาย</span></div>
    </div></div>
    <div class="sample-grid">${samples}</div>
    <pre class="raw-hex">RAW HEX · 66 BYTES\n${p.raw_hex}</pre>
    <div style="max-height:360px;overflow:auto"><table class="byte-table"><thead><tr><th>Offset</th><th>HEX</th><th>Decimal</th><th>ASCII</th><th>Field</th></tr></thead><tbody>${rows}</tbody></table></div>
  </details>`;
}
async function fetchRawPackets(btn){
  const run = async ()=>{
    let r;
    try { r = await fetch('/api/bcg/raw?limit=20'); }
    catch { toast('โหลด Raw BCG ไม่ได้', 'error'); return; }
    if (!r.ok){ toast(`Raw BCG: HTTP ${r.status}`, 'error'); return; }
    const d = await r.json(), root = document.getElementById('rawPackets');
    if (!root) return;
    if (!d.packets.length){ root.innerHTML='<div class="mini">ยังไม่มี packet หลังเริ่มระบบ</div>'; return; }
    root.innerHTML = d.packets.slice().reverse().map(renderRawPacket).join('');
  };
  return btn ? withBusy(btn, run) : run();
}
setInterval(()=>{
  if(currentPrincipal?.role==='admin'&&document.body.dataset.view==='monitor'){
    fetchCalibrationInspector();
    fetchRawPackets();
  }
},10000);
