/* ---- Red ambient: 3 independent persistent HIGH/LOW Pi GPIO outputs ---- */
const redLightZones = {
  red_light_face:{label:'หัวเตียง', btn:'redLightFaceBtn', state:'redLightFaceState', zone:'redLightFaceZone'},
  red_light_body:{label:'กลางเตียง', btn:'redLightBodyBtn', state:'redLightBodyState', zone:'redLightBodyZone'},
  red_light_leg:{label:'ปลายเตียง', btn:'redLightLegBtn', state:'redLightLegState', zone:'redLightLegZone'},
};
async function redLightAction(name, btn){
  const cfg=redLightZones[name];
  if(!cfg)return;
  const targetOn=!current.gpio?.[name];
  if(btn){
    btn.dataset.interactionIntent=targetOn?'on':'off';
    btn.dataset.interactionTarget=name;
    btn.dataset.interactionLabel=`${targetOn?'เปิด':'ปิด'} แสงแดง${cfg.label}`;
  }
  const result=await withBusy(btn,()=>post(`/api/output/${name}`,{on:targetOn}));
  if(!result){flashCommandResult(btn,false);return;}
  if(!current.gpio)current.gpio={};
  current.gpio[name]=targetOn;
  updateRedLights(current.gpio);
  syncUnifiedRedLights(current.gpio,!!current.system?.gpio_available&&!current.safety?.latched);
  flashCommandResult(btn,true);
  toast(
    currentPrincipal?.role==='admin'
      ?`Red Light ${cfg.label}: ${targetOn?'ON · GPIO HIGH':'OFF · GPIO LOW'}`
      :`${targetOn?'เปิด':'ปิด'}แสงแดง${cfg.label}แล้ว`,
    'ok',
    2400,
  );
}
function updateRedLights(gpio={}){
  const gpioOk=!!current.system?.gpio_available;
  const safetyLatched=!!current.safety?.latched;
  const adminView=currentPrincipal?.role==='admin';
  const pinMap=current.system?.gpio_pins||{};
  Object.entries(redLightZones).forEach(([name,cfg])=>{
    const on=!!gpio[name];
    const btn=document.getElementById(cfg.btn);
    const stateEl=document.getElementById(cfg.state);
    const zone=document.getElementById(cfg.zone);
    if(!btn||!stateEl||!zone)return;
    const pin=pinMap[name] ?? '--';
    zone.classList.toggle('active',on);
    btn.classList.toggle('on',on);
    if(!gpioOk){
      stateEl.textContent=adminView?`GPIO ${pin} · unavailable`:'กำลังเชื่อมต่อ';
      btn.textContent=adminView?'OFF':'—';
      btn.disabled=true;
      btn.classList.remove('on');
      zone.classList.remove('active');
      return;
    }
    if(safetyLatched){
      stateEl.textContent=adminView?`GPIO ${pin} · Safety locked`:'โหมดปลอดภัย';
      btn.textContent=adminView?(on?'ON':'OFF'):(on?'เปิดอยู่':'ปิดอยู่');
      btn.disabled=true;
      return;
    }
    stateEl.textContent=adminView?`GPIO ${pin} · ${on?'HIGH':'LOW'}`:(on?'เปิดอยู่':'ปิดอยู่');
    if(!btn.classList.contains('busy')){
      btn.textContent=adminView?(on?'ON':'OFF'):(on?'ปิด':'เปิด');
      btn.disabled=false;
    }
  });
}

/* ---- air-conditioner: Pi MQTT -> ESP32 Control Hub 1 -> IR ---- */
function airconCommandLabel(command){
  const labels={on:'POWER ON',off:'POWER OFF',fan:'FAN NEXT',swing_on:'SWING ON',swing_off:'SWING OFF',light_on:'LIGHT ON',light_off:'LIGHT OFF',status:'STATUS'};
  return labels[command] || command.toUpperCase();
}
async function airconCommand(command,btn){
  if(airconRequestBusy)return null;
  if(btn){
    const tempMatch=String(command).match(/^temp\s+(\d+)$/);
    btn.dataset.interactionIntent=tempMatch?'temperature':command;
    btn.dataset.interactionLabel=tempMatch?`ปรับอุณหภูมิ ${tempMatch[1]}°C`:{on:'เปิดเครื่องปรับอากาศ',off:'ปิดเครื่องปรับอากาศ',swing_on:'เปิดสวิงลม',swing_off:'ปิดสวิงลม'}[command]||airconCommandLabel(command);
  }
  airconRequestBusy=true;
  renderAircon(current.aircon||{});
  try{
    const result=await withBusy(btn,()=>post('/api/aircon/command',{command}));
    if(!result){flashCommandResult(btn,false);return null;}
    const label=airconCommandLabel(result.command||command);
    const hasDesiredTemperature=Number.isInteger(result.desired_temperature_c);
    const adminView=currentPrincipal?.role==='admin';
    const userMessages={
      status:'อัปเดตข้อมูลแอร์แล้ว',
      on:'ส่งคำสั่งเปิดแอร์แล้ว · กรุณาสังเกตการตอบสนองของแอร์',
      off:'ส่งคำสั่งปิดแอร์แล้ว · กรุณาสังเกตการตอบสนองของแอร์',
      fan:'ส่งคำสั่งปรับแรงลมแล้ว · กรุณาสังเกตการตอบสนองของแอร์',
      swing_on:'ส่งคำสั่งเปิดสวิงแล้ว · กรุณาสังเกตการตอบสนองของแอร์',
      swing_off:'ส่งคำสั่งปิดสวิงแล้ว · กรุณาสังเกตการตอบสนองของแอร์',
    };
    const message=adminView
      ?command==='status'
        ?'ESP32 Aircon: รับสถานะล่าสุดแล้ว'
        :command==='on'
          ?'ส่ง IR เปิดแอร์และตั้งค่าเริ่มต้นแล้ว · กรุณาตรวจการตอบสนองของแอร์'
          :command==='fan'&&normalizedAirconFanLevel(result.fan_level)!=null
            ?`ส่ง IR ปรับแรงลมแล้ว · ค่าอ้างอิง ${result.fan_level}/5 (ไม่ใช่ค่าที่วัดจากแอร์)`
            :hasDesiredTemperature
              ?`ส่ง IR ตั้งอุณหภูมิ ${result.desired_temperature_c}°C แล้ว`
              :`ESP32 Aircon ยิง IR: ${label} แล้ว`
      :hasDesiredTemperature
        ?`ส่งคำสั่งตั้งอุณหภูมิ ${result.desired_temperature_c}°C แล้ว · กรุณาสังเกตการตอบสนองของแอร์`
        :userMessages[command]||'ส่งคำสั่งแอร์แล้ว · กรุณาสังเกตการตอบสนองของแอร์';
    toast(message,'ok',3200);
    if(result.aircon)current.aircon=result.aircon;
    if(command==='swing_on'||command==='swing_off'){
      unifiedAirconSwingState=command==='swing_on';
      current.aircon={...(current.aircon||{}),swing:unifiedAirconSwingState};
    }
    if(result.aircon||command==='swing_on'||command==='swing_off')renderAircon(current.aircon||{});
    flashCommandResult(btn,true);
    return result;
  }finally{
    airconRequestBusy=false;
    renderAircon(current.aircon||{});
  }
}
function airconSendTemperature(btn){
  const input=document.getElementById('airconTempInput');
  const value=Number(input.value);
  if(!Number.isInteger(value)||value<AIRCON_DESIRED_TEMPERATURE_MIN_C||value>AIRCON_DESIRED_TEMPERATURE_MAX_C){
    toast(`อุณหภูมิที่เลือกต้องเป็นเลขจำนวนเต็ม ${AIRCON_DESIRED_TEMPERATURE_MIN_C}–${AIRCON_DESIRED_TEMPERATURE_MAX_C} °C`,'error');
    input.focus();
    return;
  }
  airconCommand(`temp ${value}`,btn);
}
function renderAircon(a={}){
  const connected=!!a.connected&&!a.stale;
  const pending=airconRequestBusy||!!a.command_pending;
  const safetyLatched=!!current.safety?.latched;
  const age=Number(a.data_age_s);
  const conn=document.getElementById('airconConn');
  if(!conn)return;
  conn.textContent=connected?'ESP32 Aircon · Online':a.stale?'ESP32 Aircon · Stale':'ESP32 Aircon · Offline';
  conn.className=`status-chip ${connected?'success':a.stale?'warning':'danger'}`;
  const fresh=document.getElementById('airconFreshness');
  fresh.textContent=Number.isFinite(age)?`ล่าสุด ${age.toFixed(1)} วินาที`:'ยังไม่มีข้อมูล';
  fresh.className=`status-chip ${connected?'success':a.stale?'warning':''}`;
  document.getElementById('airconPowerState').textContent=a.power===true?'ON':a.power===false?'OFF':'--';
  document.getElementById('airconTempState').textContent=a.temperature_c==null
    ? '-- / -- °C'
    : `${a.desired_temperature_c??'--'} / ${a.temperature_c} °C`;
  document.getElementById('airconLastCommand').textContent=a.last_command||'--';
  document.getElementById('airconTxCount').textContent=a.tx_count??0;
  // Hardware mapping is intentionally Admin-only. User controls show only the
  // selected comfort target and never expose the installation bias.
  const debugDesired=document.getElementById('debugAirconDesiredTemp'),debugBias=document.getElementById('debugAirconBias'),debugCommanded=document.getElementById('debugAirconCommandedTemp'),debugDefault=document.getElementById('debugAirconDefaultTemp');
  const desired=Number(a.desired_temperature_c),bias=Number(a.temperature_bias_c),commanded=Number(a.temperature_c),powerOnDefault=Number(a.power_on_default_temperature_c);
  if(debugDesired)debugDesired.textContent=Number.isInteger(desired)?`${desired}°C`:'--';
  if(debugBias)debugBias.textContent=Number.isInteger(bias)?`${bias<0?'−':bias>0?'+':''}${Math.abs(bias)}°C`:'--';
  if(debugCommanded)debugCommanded.textContent=Number.isInteger(commanded)?`${commanded}°C`:'--';
  if(debugDefault)debugDefault.textContent=Number.isInteger(powerOnDefault)?`${powerOnDefault}°C · สวิง`:'18°C · สวิง';
  const debugFanLevel=document.getElementById('debugAirconFanLevel');
  if(debugFanLevel)debugFanLevel.textContent=normalizedAirconFanLevel(a.fan_level)??'--';
  const debugFanReference=document.getElementById('debugAirconFanReference');
  const fanLevel=normalizedAirconFanLevel(a.fan_level);
  if(debugFanReference&&document.activeElement!==debugFanReference&&fanLevel!=null)debugFanReference.value=String(fanLevel);
  const debugFanSource=document.getElementById('debugAirconFanSource');
  if(debugFanSource){
    const sourceLabels={pod_default_reference:'ค่าเริ่มต้นของ ZEEP',recovered_default_reference:'กู้คืนเป็นค่าเริ่มต้น',admin_declared_reference:'Admin ระบุจากเครื่องจริง',esp_ack:'ESP32 ACK พร้อมระดับ',acknowledged_ir_cycle:'คำนวณจาก IR ที่ ACK ล่าสุด'};
    debugFanSource.textContent=`ระดับ ${fanLevel??'--'}/5 · ${sourceLabels[a.fan_level_source]||'สถานะอ้างอิง'} · ไม่ใช่ค่าที่วัดจากแอร์`;
  }
  const detail=document.getElementById('airconDetail');
  if(pending)detail.textContent=`กำลังรอคำยืนยัน: ${a.pending_command||'command'}`;
  else if(a.error)detail.textContent=`ข้อผิดพลาด: ${a.error}`;
  else if(a.last_event)detail.textContent=`ผลล่าสุด: ${a.last_event.ok?'สำเร็จ':'ไม่สำเร็จ'} · ${a.last_event.detail||a.last_event.command||'ไม่มีรายละเอียด'}`;
  else detail.textContent=connected?'พร้อมรับคำสั่ง':'รอการเชื่อมต่อ MQTT';

  document.querySelectorAll('.aircon-action').forEach(button=>{
    const command=button.dataset.airconCommand;
    const blockedBySafety=safetyLatched&&!['off','status'].includes(command);
    if(!button.classList.contains('busy'))button.disabled=!connected||pending||blockedBySafety;
    button.title=!connected?'ESP32 Aircon Offline':pending?'กำลังรอคำยืนยันจาก ESP32 Aircon':blockedBySafety?'Safety latch: อนุญาตเฉพาะ OFF และ STATUS':button.getAttribute('aria-label')||'';
  });
  const tempInput=document.getElementById('airconTempInput');
  tempInput.disabled=!connected||pending||safetyLatched;
  const desiredTemperature=Number(a.desired_temperature_c);
  if(document.activeElement!==tempInput&&Number.isInteger(desiredTemperature)&&desiredTemperature>=AIRCON_DESIRED_TEMPERATURE_MIN_C&&desiredTemperature<=AIRCON_DESIRED_TEMPERATURE_MAX_C){
    tempInput.value=desiredTemperature;
  }
}

/* ---- adjustable bed: Pi MQTT -> ESP32 Control Hub 2 -> four servos ---- */
function bedCommandLabel(command){
  const labels={none:'ไม่มีคำสั่ง',head_up:'กำลังยกหัวเตียง',head_down:'กำลังลดหัวเตียง',foot_up:'กำลังยกปลายเท้า',foot_down:'กำลังลดปลายเท้า',bed_stop:'หยุดแล้ว',flat:'กำลังปรับเตียงปกติ',center_all:'กำลังจัดตำแหน่งกลาง',status:'กำลังตรวจสถานะ'};
  return labels[command]||String(command||'').toUpperCase();
}
function syncBedLevelsFromController(bed={}){
  // Use controller-reported levels when firmware provides them. Current
  // firmware reports direction/ACK only, so the UI otherwise keeps the five
  // bounded two-second steps that were successfully acknowledged by the Pi.
  const reportedHead=bed.head_level??bed.head_position_level;
  const reportedFoot=bed.foot_level??bed.foot_position_level;
  let changed=false;
  if(reportedHead!=null&&Number.isFinite(Number(reportedHead))){bedVisualLevels.head=clampBedLevel(reportedHead);changed=true;}
  if(reportedFoot!=null&&Number.isFinite(Number(reportedFoot))){bedVisualLevels.foot=clampBedLevel(reportedFoot);changed=true;}
  if(changed)saveBedVisualLevels();
}
function applyBedLevelVisual(active='none'){
  const podMap=document.getElementById('bedPodMap'),podState=document.getElementById('bedPodSceneState');
  if(podMap){
    podMap.dataset.headLevel=String(bedVisualLevels.head);
    podMap.dataset.footLevel=String(bedVisualLevels.foot);
    podMap.dataset.command=active;
    podMap.setAttribute('aria-label',active==='none'
      ? `เตียงภายใน ZEEP หัวระดับ ${bedVisualLevels.head} จาก ${BED_LEVEL_MAX} ปลายระดับ ${bedVisualLevels.foot} จาก ${BED_LEVEL_MAX}`
      : `${bedCommandLabel(active)} หัวระดับ ${bedVisualLevels.head} จาก ${BED_LEVEL_MAX} ปลายระดับ ${bedVisualLevels.foot} จาก ${BED_LEVEL_MAX}`);
  }
  const levelText=`หัว ${bedVisualLevels.head}/${BED_LEVEL_MAX} · ปลาย ${bedVisualLevels.foot}/${BED_LEVEL_MAX}`;
  if(podState)podState.textContent=active==='none'?levelText:`${bedCommandLabel(active)} · ${levelText}`;
  document.querySelectorAll('[data-bed-command]').forEach(button=>{
    const command=button.dataset.bedCommand;
    const atLimit=(command==='head_up'&&bedVisualLevels.head>=BED_LEVEL_MAX)||(command==='head_down'&&bedVisualLevels.head<=0)||(command==='foot_up'&&bedVisualLevels.foot>=BED_LEVEL_MAX)||(command==='foot_down'&&bedVisualLevels.foot<=0);
    button.classList.toggle('at-level-limit',atLimit);
  });
}
function bedLevelCommandAllowed(command){
  if(command==='head_up'&&bedVisualLevels.head>=BED_LEVEL_MAX)return `หัวเตียงอยู่ระดับสูงสุด ${BED_LEVEL_MAX}/${BED_LEVEL_MAX} แล้ว`;
  if(command==='head_down'&&bedVisualLevels.head<=0)return 'หัวเตียงอยู่ระดับปกติแล้ว';
  if(command==='foot_up'&&bedVisualLevels.foot>=BED_LEVEL_MAX)return `ปลายเตียงอยู่ระดับสูงสุด ${BED_LEVEL_MAX}/${BED_LEVEL_MAX} แล้ว`;
  if(command==='foot_down'&&bedVisualLevels.foot<=0)return 'ปลายเตียงอยู่ระดับปกติแล้ว';
  return '';
}
function updateBedLevelsAfterAck(command){
  if(command==='head_up')bedVisualLevels.head=clampBedLevel(bedVisualLevels.head+1);
  else if(command==='head_down')bedVisualLevels.head=clampBedLevel(bedVisualLevels.head-1);
  else if(command==='foot_up')bedVisualLevels.foot=clampBedLevel(bedVisualLevels.foot+1);
  else if(command==='foot_down')bedVisualLevels.foot=clampBedLevel(bedVisualLevels.foot-1);
  else if(command==='flat')bedVisualLevels={head:0,foot:0};
  saveBedVisualLevels();
}
function renderUnifiedBedMotion(bed={}){
  syncBedLevelsFromController(bed);
  const movementCommands=['head_up','head_down','foot_up','foot_down','flat','center_all'];
  const reported=bed.active_command&&bed.active_command!=='none'?bed.active_command:bed.pending_command;
  const active=bed.auto_stop_pending&&movementCommands.includes(reported)?reported:'none';
  const headActive=['head_up','head_down','flat','center_all'].includes(active);
  const footActive=['foot_up','foot_down','flat','center_all'].includes(active);
  document.getElementById('bedMapHead')?.classList.toggle('active',headActive);
  document.getElementById('bedMapFoot')?.classList.toggle('active',footActive);
  document.getElementById('bedSceneHead')?.classList.toggle('active',headActive);
  document.getElementById('bedSceneFoot')?.classList.toggle('active',footActive);
  const map=document.getElementById('bedMotionMap'),arrow=document.getElementById('bedMotionArrow');
  const commandLabel=bedCommandLabel(active);
  const arrowIcon=active.endsWith('_up')?'up':active.endsWith('_down')?'down':['flat','center_all'].includes(active)?'center':'bed-flat';
  if(arrow)setUiIconReference(arrow.querySelector('.ui-icon'),arrowIcon);
  const label=document.getElementById('unifiedBedCommand');
  if(label)label.textContent=active==='none'?'เตียงปกติ':commandLabel;
  if(map){map.classList.toggle('moving',active!=='none');map.title=active==='none'?'ปรับเตียงปกติ':`${commandLabel} · จะหยุดอัตโนมัติ`;}
  const podMap=document.getElementById('bedPodMap');
  if(podMap){
    podMap.classList.toggle('moving',active!=='none');
  }
  applyBedLevelVisual(active);
}
async function bedCommand(command,btn){
  if(bedRequestBusy)return;
  const limitMessage=bedLevelCommandAllowed(command);
  if(limitMessage){toast(limitMessage,'warning',2200);return;}
  if(btn){
    btn.dataset.interactionIntent=command;
    btn.dataset.interactionLabel=bedCommandLabel(command).replace(/^กำลัง/,'');
  }
  // Show which mattress section was selected before the controller ACK. This
  // changes only the illustration, never the stored five-step position.
  applyBedLevelVisual(command);
  bedRequestBusy=true;
  renderBedControl(current.bed_control||{});
  try{
    const result=await withBusy(btn,()=>post('/api/bed/command',{command}));
    if(!result){renderUnifiedBedMotion(current.bed_control||{});flashCommandResult(btn,false);return;}
    const acceptedCommand=result.command||command;
    updateBedLevelsAfterAck(acceptedCommand);
    const message=acceptedCommand==='flat'
      ? 'กำลังปรับหัวและปลายเตียงกลับสู่แนวขนาน'
      : `${bedCommandLabel(acceptedCommand)} · ระดับหัว ${bedVisualLevels.head}/${BED_LEVEL_MAX} · ปลาย ${bedVisualLevels.foot}/${BED_LEVEL_MAX}`;
    toast(message,'ok',2800);
    if(result.bed_control){current.bed_control=result.bed_control;renderBedControl(result.bed_control);renderUnifiedBedMotion(result.bed_control);}
    else applyBedLevelVisual('none');
    flashCommandResult(btn,true);
  }finally{
    bedRequestBusy=false;
    renderBedControl(current.bed_control||{});
  }
}
function renderBedControl(bed={}){
  const connected=!!bed.connected&&!bed.stale;
  const pending=bedRequestBusy||!!bed.command_pending;
  const safetyLatched=!!current.safety?.latched;
  const age=Number(bed.data_age_s);
  const conn=document.getElementById('bedControlConn');
  if(!conn)return;
  conn.textContent=connected?'ESP32 Bed · Online':bed.stale?'ESP32 Bed · Stale':'ESP32 Bed · Offline';
  conn.className=`status-chip ${connected?'success':bed.stale?'warning':'danger'}`;
  const fresh=document.getElementById('bedControlFreshness');
  fresh.textContent=Number.isFinite(age)?`ล่าสุด ${age.toFixed(1)} วินาที`:'ยังไม่มีข้อมูล';
  fresh.className=`status-chip ${connected?'success':bed.stale?'warning':''}`;
  const reportedActive=bed.active_command&&bed.active_command!=='none'?bed.active_command:bed.pending_command;
  const active=bed.auto_stop_pending&&['head_up','head_down','foot_up','foot_down','flat','center_all'].includes(reportedActive)?reportedActive:'none';
  document.getElementById('bedActiveCommand').textContent=bedCommandLabel(active);
  document.getElementById('bedActiveServo').textContent=bed.active_servo==null?'--':`Servo ${bed.active_servo}`;
  document.getElementById('bedCommandCount').textContent=bed.command_count??0;
  const detail=document.getElementById('bedControlDetail');
  if(pending)detail.textContent=`กำลังรอคำยืนยัน: ${bed.pending_command||'command'}`;
  else if(bed.error)detail.textContent=`ข้อผิดพลาด: ${bed.error}`;
  else if(bed.last_event)detail.textContent=`ผลล่าสุด: ${bed.last_event.ok?'สำเร็จ':'ไม่สำเร็จ'} · ${bed.last_event.detail||bed.last_event.command||'ไม่มีรายละเอียด'}`;
  else detail.textContent=connected?'พร้อมรับคำสั่ง':'รอการเชื่อมต่อ MQTT';
  document.querySelectorAll('.bed-action').forEach(button=>{
    const command=button.dataset.bedCommand;
    const alwaysAllowed=['bed_stop','status'].includes(command);
    const blockedBySafety=safetyLatched&&!alwaysAllowed;
    if(!button.classList.contains('busy'))button.disabled=!connected||pending||blockedBySafety;
    button.classList.toggle('active',command===active);
    button.setAttribute('aria-pressed',command===active?'true':'false');
    button.title=!connected?'ESP32 Bed Offline':pending?'กำลังรอคำยืนยันจาก ESP32 Bed':blockedBySafety?'Safety latch: อนุญาตเฉพาะ BED STOP และ STATUS':command===active?'กำลังขยับและจะหยุดอัตโนมัติ':button.getAttribute('aria-label')||'';
  });
}

/* ---- inline label editing for aroma slots ---- */
function startEditLabel(k){
  const el = outputEls[k];
  if (el.editing) return;
  el.editing = true;
  const input = document.createElement('input');
  input.type = 'text'; input.maxLength = 24; input.className = 'label-edit';
  input.value = currentLabel(k);
  el.title.replaceWith(input);
  input.focus(); input.select();
  let finished = false;
  const done = async (save)=>{
    if (finished) return;
    finished = true;
    const label = input.value.trim();
    input.replaceWith(el.title);
    el.editing = false;
    if (save && label && label !== currentLabel(k)){
      const r = await post(`/api/labels/${k}`, {label});
      if (r){
        el.title.textContent = r.label;
        toast(`เปลี่ยนชื่อเป็น "${r.label}" แล้ว`, 'ok', 2400);
      }
    }
  };
  input.onkeydown = e=>{
    if (e.key === 'Enter') done(true);
    if (e.key === 'Escape') done(false);
  };
  input.onblur = ()=>done(true);
}
