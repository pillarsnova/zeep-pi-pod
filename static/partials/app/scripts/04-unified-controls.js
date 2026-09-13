function unifiedAirconPowerToggle(btn){
  const aircon=current.aircon||{};
  if(!aircon.connected||aircon.stale)return;
  // The controller exposes its latest acknowledged IR command rather than a
  // physical feedback contact. Toggle from that acknowledged reference; an
  // unknown state intentionally sends ON as the safe first interaction.
  const command=aircon.power===true?'off':'on';
  if(btn)btn.dataset.airconCommand=command;
  airconCommand(command,btn);
}
function resolveUnifiedAirconSwingState(aircon={}){
  const reported=[aircon.swing,aircon.swing_enabled,aircon.swing_on]
    .find(value=>typeof value==='boolean');
  if(typeof reported==='boolean')unifiedAirconSwingState=reported;
  else if(aircon.last_command_ok!==false&&aircon.last_command==='swing_on')unifiedAirconSwingState=true;
  else if(aircon.last_command_ok!==false&&aircon.last_command==='swing_off')unifiedAirconSwingState=false;
  return unifiedAirconSwingState;
}
function unifiedSwingToggle(btn){
  const aircon=current.aircon||{};
  if(!aircon.connected||aircon.stale)return;
  const swingOn=resolveUnifiedAirconSwingState(aircon)===true;
  const command=swingOn?'swing_off':'swing_on';
  if(btn)btn.dataset.airconCommand=command;
  airconCommand(command,btn);
}
function normalizedAirconFanLevel(value){
  const level=Number(value);
  return Number.isInteger(level)&&level>=1&&level<=5?level:null;
}
function unifiedFanLevelCycle(btn){
  const aircon=current.aircon||{};
  if(!aircon.connected||aircon.stale)return;
  airconCommand('fan',btn);
}
function renderUnifiedAudioModeControls(){
  const toggle=document.getElementById('unifiedAudioModeToggle');
  if(toggle){
    const repeat=unifiedAudioMode==='repeat_one';
    toggle.dataset.mode=unifiedAudioMode;
    toggle.setAttribute('aria-pressed',repeat?'true':'false');
    toggle.setAttribute('aria-label',repeat
      ? 'Loop เปิดอยู่ กดเพื่อเปลี่ยนเป็นเล่นตามคิว'
      : 'เล่นตามคิวอยู่ กดเพื่อเปิด Loop เล่นซ้ำ');
    toggle.title=repeat?'Loop · เล่นซ้ำ':'Queue · เล่นตามคิว';
    toggle.classList.toggle('on',repeat);
    setUiIconReference(document.getElementById('unifiedAudioModeIcon'),repeat?'repeat-one':'queue');
    const label=document.getElementById('unifiedAudioModeLabel');
    if(label)label.textContent=repeat?'เล่นซ้ำ':'ตามคิว';
  }
  const legacy=document.getElementById('loopChk');
  if(legacy)legacy.checked=unifiedAudioMode==='repeat_one';
}
function toggleUnifiedAudioMode(btn){
  const nextMode=unifiedAudioMode==='repeat_one'?'queue':'repeat_one';
  return setUnifiedAudioMode(nextMode,btn);
}
async function setUnifiedAudioMode(mode,btn){
  if(!['repeat_one','queue'].includes(mode))return;
  if(current.safety?.latched){
    toast(currentPrincipal?.role==='admin'?'Safety Stop กำลังทำงาน':'ระบบอยู่ในโหมดปลอดภัย จึงยังเปลี่ยนเสียงไม่ได้','error');
    return;
  }
  unifiedAudioMode=mode;
  unifiedAudioModeInitialized=true;
  renderUnifiedAudioModeControls();
  const label=mode==='repeat_one'?'เล่นซ้ำ':'คิวเพลง';
  if(current.music?.playing){
    selectedTrack=current.music.track||selectedTrack;
    toast(`เปลี่ยนเป็น ${label} · เริ่มเพลงใหม่`,'ok',1800);
    return playSelected(btn);
  }
  toast(`เลือก ${label} แล้ว`,'ok',1600);
}
function unifiedQueueTracks(){
  const select=document.getElementById('unifiedTrackSelect');
  return select?[...select.options].map(option=>option.value).filter(Boolean):[];
}
function unifiedAudioToggle(btn){
  const music=current.music||{};
  const stopping=!!music.playing;
  if(btn){
    btn.dataset.interactionIntent=stopping?'stop':'play';
    btn.dataset.interactionLabel=stopping?'หยุดเสียงใน ZEEP':'เล่นเสียงใน ZEEP';
  }
  // The bedside player uses one unambiguous transport action: Play when idle,
  // Stop when audio is loaded. This is easier to understand on a touch screen
  // than separate Pause and Stop buttons.
  if(stopping)return musicCmd(btn,'/api/music/stop');
  return playSelected(btn);
}
async function unifiedSelectTrack(track,control=null){
  if(!track)return;
  selectedTrack=track;
  const select=document.getElementById('unifiedTrackSelect');if(select&&select.value!==track)select.value=track;
  Object.entries(trackEls).forEach(([name,entry])=>entry.row.classList.toggle('sel',name===track));
  // Selecting a new item while audio is loaded behaves like a streaming app:
  // it replaces the current track immediately. While stopped it only updates
  // the visible selection, leaving the large Play button as the final action.
  if(current.music?.playing)return playSelected(control);
  renderUnifiedAudioPlayer(current.music||{},current.safety||{});
  toast(`เลือก ${trackMeta(track).title} แล้ว`,'ok',1400);
}
function unifiedStepTrack(direction,btn){
  const select=document.getElementById('unifiedTrackSelect');
  const tracks=unifiedQueueTracks();
  if(!tracks.length){toast('ยังไม่มีรายการเพลง','warning',1800);return;}
  const active=selectedTrack||current.music?.track;
  const index=Math.max(0,tracks.indexOf(active));
  selectedTrack=tracks[(index+direction+tracks.length)%tracks.length];
  select.value=selectedTrack;
  Object.entries(trackEls).forEach(([name,entry])=>entry.row.classList.toggle('sel',name===selectedTrack));
  // Previous/next selects only while stopped; during playback it starts the
  // adjacent track immediately, matching familiar streaming-player behavior.
  if(current.music?.playing){playSelected(btn);return;}
  renderUnifiedAudioPlayer(current.music||{},current.safety||{});
}
function unifiedTrackTone(track=''){
  return [...String(track)].reduce((sum,char)=>sum+char.charCodeAt(0),0)%5;
}
function renderUnifiedAudioPlayer(music={},safety={}){
  const playing=!!music.playing&&!music.paused,loaded=!!music.playing;
  if(!unifiedAudioModeInitialized){
    const backendMode=['repeat_one','queue'].includes(music.mode)?music.mode:null;
    unifiedAudioMode=music.playing
      ? (backendMode||(music.loop?'repeat_one':'queue'))
      : (backendMode||'repeat_one');
    unifiedAudioModeInitialized=true;
  }
  renderUnifiedAudioModeControls();
  const pending=!!unifiedAudioPendingTrack;
  if(!pending&&loaded&&music.track&&selectedTrack!==music.track){
    selectedTrack=music.track;
    const select=document.getElementById('unifiedTrackSelect');if(select)select.value=music.track;
    Object.entries(trackEls).forEach(([name,entry])=>entry.row.classList.toggle('sel',name===music.track));
  }
  const displayTrack=unifiedAudioPendingTrack||selectedTrack||music.track;
  const meta=displayTrack?trackMeta(displayTrack):{title:'ยังไม่มีเสียง',desc:'เลือกจากรายการ'};
  const cover=document.getElementById('unifiedAlbumArt');
  const title=document.getElementById('unifiedTrackTitle');
  const hint=document.getElementById('unifiedTrackHint');
  const mode=document.getElementById('unifiedPlayerMode');
  if(cover)cover.dataset.tone=String(unifiedTrackTone(displayTrack));
  if(title)title.textContent=meta.title;
  if(hint)hint.textContent=meta.desc;
  if(mode)mode.textContent=pending?'กำลังเริ่มเพลง…':playing?'เล่นอยู่':music.paused?'พักอยู่':'พร้อมเล่น';

  const play=document.getElementById('unifiedAudioBtn'),playIcon=document.getElementById('unifiedAudioPlayIcon'),playLabel=document.getElementById('unifiedAudioPlayLabel');
  if(play&&playIcon){
    setUiIconReference(playIcon,loaded?'stop':'play');
    if(playLabel)playLabel.textContent=loaded?'หยุด':'เล่น';
    play.classList.toggle('on',loaded);
    play.setAttribute('aria-pressed',loaded?'true':'false');
    play.setAttribute('aria-label',loaded?'หยุดเสียงใน ZEEP':'เล่นเสียงใน ZEEP');
    play.title=play.getAttribute('aria-label');
    // A safety latch may stop active audio, but it must never allow a new
    // stream to start from this control.
    if(!play.classList.contains('busy'))play.disabled=(!displayTrack)||(!!safety.latched&&!loaded);
  }
  const trackCount=document.getElementById('unifiedTrackSelect')?.options.length||0;
  ['unifiedAudioPrev','unifiedAudioNext'].forEach(id=>{
    const button=document.getElementById(id);
    if(button&&!button.classList.contains('busy'))button.disabled=trackCount<2||!!safety.latched;
  });
  const zone=document.querySelector('.audio-zone');
  if(zone){zone.classList.toggle('playing',playing);zone.classList.toggle('paused',!!music.paused);zone.classList.toggle('audio-loading',pending);}
  // ภาพ ZEEP และเครื่องเล่นใช้สถานะเดียวกัน เพื่อไม่ให้ภาพสื่อว่ากำลังเล่น
  // ในขณะที่ Pi รายงานว่าหยุดหรือพักเพลงอยู่
  const podMap=document.getElementById('audioPodMap'),podState=document.getElementById('audioPodState');
  const podLabel=pending?'กำลังเริ่มเพลง':playing?'เล่นอยู่':music.paused?'พักอยู่':displayTrack?'พร้อม':'เลือกเสียง';
  if(podMap){podMap.dataset.state=pending?'loading':playing?'playing':music.paused?'paused':'ready';podMap.setAttribute('aria-label',`ระบบเสียงภายใน ZEEP ${podLabel}`);}
  if(podState)podState.textContent=podLabel;

  // Queue progression belongs exclusively to the Pi player. A browser must
  // never interpret a stopped WebSocket state as a natural track end: with
  // two tablets open that caused one client to restart audio after another
  // client had explicitly pressed Stop.
}
function setUnifiedAirconTempFeedback(state,text,resetMs=0){
  const control=document.getElementById('unifiedAirconTempControl');
  const label=document.getElementById('unifiedAirconTempState');
  if(!control||!label)return;
  clearTimeout(unifiedAirconTempFeedbackTimer);
  control.dataset.state=state;
  label.textContent=text;
  if(resetMs){
    unifiedAirconTempFeedbackTimer=setTimeout(()=>{
      control.dataset.state='ready';
      setTimeout(()=>{if(control.dataset.state==='ready')label.textContent='';},220);
    },resetMs);
  }
}
async function applyUnifiedAirconTemperature(select){
  const desired=Number(select?.value);
  if(!Number.isInteger(desired)||desired<AIRCON_DESIRED_TEMPERATURE_MIN_C||desired>AIRCON_DESIRED_TEMPERATURE_MAX_C){
    toast(`เลือกอุณหภูมิได้ ${AIRCON_DESIRED_TEMPERATURE_MIN_C}–${AIRCON_DESIRED_TEMPERATURE_MAX_C} °C`,'error');
    select?.focus();
    return;
  }
  // Selection is the command: retain this draft while WebSocket frames arrive,
  // then replace it with the confirmed controller state after the API returns.
  unifiedAirconDraftTemp=desired;
  setUnifiedAirconTempFeedback('sending',`กำลังปรับ ${desired}°C`);
  const result=await airconCommand(`temp ${desired}`,select);
  unifiedAirconDraftTemp=null;
  if(result){
    setUnifiedAirconTempFeedback('success',`ตั้ง ${desired}°C แล้ว`,1800);
  }else{
    const confirmed=Number(current.aircon?.desired_temperature_c);
    if(Number.isInteger(confirmed)&&confirmed>=AIRCON_DESIRED_TEMPERATURE_MIN_C&&confirmed<=AIRCON_DESIRED_TEMPERATURE_MAX_C)select.value=String(confirmed);
    setUnifiedAirconTempFeedback(
      'error',
      currentPrincipal?.role==='admin'?'ปรับไม่สำเร็จ':'ยังปรับไม่ได้ · ลองอีกครั้ง',
      2400,
    );
  }
}
function syncUnifiedSwitch(id,on,enabled,onText='ปิด',offText='เปิด'){
  const button=document.getElementById(id);if(!button)return;
  const actionLabel=on?onText:offText;
  const accessibleLabel=button.dataset.controlLabel?`${actionLabel} ${button.dataset.controlLabel}`:actionLabel;
  // Buttons with an icon and two-line label retain their children; only the
  // visible state caption changes. Simple switches still use a text label.
  if(button.classList.contains('stateful-content')){
    const stateLabel=button.querySelector('[data-state-label]');
    if(stateLabel)stateLabel.textContent=on?'เปิดอยู่':'ปิดอยู่';
    const action=button.querySelector('[data-action-label]');
    if(action)action.textContent=actionLabel;
  }else{
    button.textContent=button.classList.contains('icon-switch')
      ? (on?button.dataset.symbolOn:button.dataset.symbolOff)||button.textContent
      : actionLabel;
  }
  button.title=accessibleLabel;button.setAttribute('aria-label',accessibleLabel);button.classList.toggle('on',!!on);
  if(!button.classList.contains('busy'))button.disabled=!enabled;
  button.setAttribute('aria-pressed',on?'true':'false');
}
// The chamber drawing follows the confirmed Pi GPIO state.  It is deliberately
// not toggled optimistically, so the ceiling glow never implies an unconfirmed
// hardware command.
function updateUnifiedPodSceneLabel(){
  const map=document.getElementById('podRoomLightMap');
  const caption=document.getElementById('podSceneCaption');
  if(!map)return;
  const roomLight=map.dataset.roomLight==='on'?'เปิด':'ปิด';
  const starLight=map.dataset.starLight==='on'?'เปิด':'ปิด';
  const aircon=map.dataset.aircon==='on'?'เปิด':map.dataset.aircon==='offline'?'Offline':'ปิด';
  const redZones=map.dataset.redZones||'';
  const redText=redZones||'ปิดทุกส่วน';
  if(caption)caption.textContent=`ไฟเพดาน ${roomLight} · ไฟดาว ${starLight} · แสงแดง ${redText}`;
  map.setAttribute('aria-label',`ภาพรวม ZEEP เครื่องปรับอากาศ${aircon} ไฟเพดาน${roomLight} ไฟดาวบนท้องฟ้า${starLight} แสงแดง${redText}`);
}

function syncUnifiedPodRoomLight(on,enabled){
  syncUnifiedSwitch('unifiedRoomLightBtn',on,enabled,'ปิดไฟ','เปิดไฟ');
  const map=document.getElementById('podRoomLightMap');
  if(!map)return;
  map.classList.toggle('on',!!on);
  map.classList.toggle('unavailable',!enabled);
  map.dataset.roomLight=on?'on':'off';
  map.dataset.roomLightAvailable=enabled?'true':'false';
  updateUnifiedPodSceneLabel();
}
// Star Light is a persistent, independent GPIO output. The ceiling points
// illuminate only from the confirmed state returned by the Pi.
function syncUnifiedStarLight(on,enabled){
  syncUnifiedSwitch('unifiedStarLightBtn',on,enabled,'ปิดไฟดาว','เปิดไฟดาว');
  const map=document.getElementById('podRoomLightMap');
  if(!map)return;
  map.classList.toggle('stars-on',!!on);
  map.dataset.starLight=on?'on':'off';
  map.dataset.starLightAvailable=enabled?'true':'false';
  updateUnifiedPodSceneLabel();
}
// Translate controller data into a calm, glanceable air-flow scene.  The
// animation starts only from confirmed ESP32 power state. The user-facing
// scene shows the selected comfort target, never the biased IR setpoint.
function syncUnifiedAirconComfort(on,online,targetTemperature,measuredTemperature){
  const map=document.getElementById('airconComfortMap');
  const caption=document.getElementById('airconComfortCaption');
  if(!map||!caption)return;
  const target=Number(targetTemperature);
  const measured=measuredTemperature===null||measuredTemperature===undefined||measuredTemperature===''?NaN:Number(measuredTemperature);
  const hasTarget=Number.isInteger(target)&&target>=AIRCON_DESIRED_TEMPERATURE_MIN_C&&target<=AIRCON_DESIRED_TEMPERATURE_MAX_C;
  const targetText=hasTarget?`${Math.round(target)}°C`:'';
  const adminView=currentPrincipal?.role==='admin';
  map.classList.toggle('on',!!on&&!!online);
  map.classList.toggle('offline',!online);
  map.dataset.cool=hasTarget&&target<=20?'deep':hasTarget&&target<=22?'cool':'gentle';
  caption.textContent=!online?(adminView?'ระบบแอร์ Offline':'กำลังเชื่อมต่อแอร์'):on?(targetText?`${targetText} · กำลังทำความเย็น`:'กำลังทำความเย็น'):'แอร์ปิดอยู่';
  const measuredText=Number.isFinite(measured)?` อุณหภูมิแอร์ ${measured.toFixed(1)}°C`:'';
  map.setAttribute('aria-label',!online?(adminView?'เครื่องปรับอากาศ Offline':'กำลังเชื่อมต่อเครื่องปรับอากาศ'):on?`เครื่องปรับอากาศเปิดอยู่ ตั้งไว้ที่ ${targetText||'รอข้อมูล'}${adminView?measuredText:''}`:'เครื่องปรับอากาศปิดอยู่');
  const podScene=document.getElementById('podRoomLightMap');
  if(podScene){
    podScene.classList.toggle('aircon-on',!!on&&!!online);
    podScene.classList.toggle('aircon-offline',!online);
    podScene.dataset.aircon=!online?'offline':on?'on':'off';
    updateUnifiedPodSceneLabel();
  }
}
// Keep the three physical bed-light zones and their controls on the same GPIO
// truth. Hardware names remain unchanged for API compatibility, while the UI
// translates them to their real installation positions on the mattress.
// No optimistic visual state is invented here; the caller supplies the state
// returned by the Pi API (or the locally confirmed API response after a tap).
function syncUnifiedRedLights(gpio={},enabled=true){
  const zones=[
    ['red_light_face','unifiedRedFaceBtn','redMapFace','บน'],
    ['red_light_body','unifiedRedBodyBtn','redMapBody','กลาง'],
    ['red_light_leg','unifiedRedLegBtn','redMapLeg','ปลาย'],
  ];
  const active=[];
  zones.forEach(([name,buttonId,mapId,label])=>{
    const on=!!gpio[name];
    syncUnifiedSwitch(buttonId,on,enabled,'ปิด','เปิด');
    document.getElementById(mapId)?.classList.toggle('on',on);
    if(on)active.push(label);
  });
  const map=document.getElementById('podRoomLightMap');
  if(map){
    map.dataset.redZones=active.join(' · ');
    updateUnifiedPodSceneLabel();
  }
}
function setControllerNode(nodeId,statusId,state,label,detail){
  const node=document.getElementById(nodeId),status=document.getElementById(statusId);if(!node||!status)return;
  node.classList.remove('live','degraded','offline');node.classList.add(state);
  status.textContent=detail?`${label} · ${detail}`:label;
}
// A control-zone reading carries the same freshness state as its source
// sensor; this prevents a stale value from looking like live telemetry.
function setUnifiedSensor(cardId,valueId,displayValue,device={}){
  const card=document.getElementById(cardId),value=document.getElementById(valueId);if(!card||!value)return;
  value.textContent=displayValue;
  const status=device.status||'offline',live=status==='live';
  card.classList.toggle('live',live);
  card.classList.toggle('warning',!live&&['stale','held','warming'].includes(status));
  card.classList.toggle('offline',!live&&!['stale','held','warming'].includes(status));
  card.title=currentPrincipal?.role==='admin'
    ?`${device.model||'Sensor'} · ${sensorStatusTh[status]||status}${Number.isFinite(Number(device.data_age_s))?` · ${Number(device.data_age_s).toFixed(1)}s`:''}`
    :live?'ข้อมูลพร้อม':'กำลังรวบรวมข้อมูล';
}
const unifiedComfortProfiles=Object.freeze({
  // These are wellness ambience profiles, not treatment claims. The physical
  // cartridge label is checked separately in Admin because the four GPIO
  // slots are reusable and the UI must never silently redefine their loadout.
  aroma1:{name:'ลาเวนเดอร์',purpose:'ก่อนนอน · ผ่อนคลาย',aliases:['ลาเวนเดอร์','lavender']},
  aroma2:{name:'ยูคาลิปตัส',purpose:'เย็นสดชื่น · รู้สึกหายใจโล่ง',aliases:['ยูคาลิปตัส','eucalyptus']},
  aroma3:{name:'ส้ม',purpose:'ผ่อนคลาย · สดชื่น',aliases:['ส้ม','orange','sweet orange']},
  aroma4:{name:'อากาศสดชื่น',purpose:'กลิ่นสะอาด · ไม่ใช่ O₂',aliases:['อากาศสดชื่น','fresh air','oxygen']},
  steam:{name:'ไอน้ำ',purpose:'เพิ่มความชื้น'},
});
const unifiedComfortButtonIds=Object.freeze({
  aroma1:'unifiedAroma1Btn',aroma2:'unifiedAroma2Btn',aroma3:'unifiedAroma3Btn',
  aroma4:'unifiedAroma4Btn',steam:'unifiedSteamBtn',
});

// Admin-only verification: compare the planned profile with the persisted
// cartridge label. Generic labels mean the cartridge has not yet been
// confirmed; a different specific label is a hard mismatch for technicians.
function renderDebugAromaReference(labels={}){
  Object.entries(unifiedComfortProfiles).forEach(([slot,profile])=>{
    if(slot==='steam')return;
    const row=document.querySelector(`.debug-aroma-slot[data-slot="${slot}"]`);
    const status=row?.querySelector('[data-runtime-label]');
    if(!row||!status)return;
    const runtime=String(labels?.[slot]||'').trim();
    const generic=!runtime||/^aroma\s*[1-4]$/i.test(runtime);
    const normalized=runtime.toLocaleLowerCase('th-TH');
    const matches=!generic&&profile.aliases.some(alias=>normalized===alias.toLocaleLowerCase('th-TH'));
    row.dataset.mapping=generic?'unconfirmed':matches?'matched':'mismatch';
    status.textContent=generic
      ? 'ยังไม่ยืนยันชื่อตลับ'
      : matches?`ตรงกับระบบ · ${runtime}`:`ไม่ตรง · ตลับตั้งชื่อ ${runtime}`;
  });
}

// Aroma/steam pulse commands take five seconds on the Pi. Keep the control aligned
// with the real lifecycle instead of showing a generic button flash: SENT is
// pending, GPIO HIGH is actively dispensing, then the API result is retained
// briefly as ACK or ERROR before returning to the ready state.
function setComfortCommandFeedback(name,status,holdMs=0){
  comfortCommandFeedback[name]={status,updatedAt:Date.now(),expiresAt:holdMs?Date.now()+holdMs:null};
  clearTimeout(comfortFeedbackTimer);
  if(holdMs){
    comfortFeedbackTimer=setTimeout(()=>{
      if(comfortCommandFeedback[name]?.status===status)delete comfortCommandFeedback[name];
      renderUnifiedComfort(current.gpio||{},!!current.system?.gpio_available,!!current.safety?.latched);
    },holdMs+30);
  }
  renderUnifiedComfort(current.gpio||{},!!current.system?.gpio_available,!!current.safety?.latched);
}

// Pulse outputs do not have a persistent ON state.  The ZEEP illustration
// therefore follows only the real command lifecycle: sending, GPIO HIGH,
// acknowledged or failed, before returning to ready.
function syncUnifiedComfortDelivery(status='ready',profile=null){
  const map=document.getElementById('comfortDeliveryMap');
  const caption=document.getElementById('comfortDeliveryState');
  if(!map||!caption)return;
  const profileName=profile?.name||'';
  const adminView=currentPrincipal?.role==='admin';
  const labels={
    ready:'พร้อมใช้งาน',
    active:`กำลังพ่น${profileName?` · ${profileName}`:''}`,
    pending:`กำลังส่ง${profileName?` · ${profileName}`:''}`,
    success:`ส่งสำเร็จ${profileName?` · ${profileName}`:''}`,
    error:adminView?'ส่งไม่สำเร็จ':'ยังไม่ตอบสนอง · ลองอีกครั้ง',
    locked:adminView?'Safety Locked':'โหมดปลอดภัย',
    offline:adminView?'ระบบ Offline':'กำลังเชื่อมต่อ',
  };
  const label=labels[status]||labels.ready;
  map.dataset.state=status;
  caption.textContent=label;
  map.setAttribute('aria-label',`ระบบกลิ่นและไอน้ำ ${label}`);
}

function renderUnifiedComfort(gpio={},gpioOk=false,safetyLatched=false){
  const now=Date.now(),states=[];
  const adminView=currentPrincipal?.role==='admin';
  Object.entries(unifiedComfortProfiles).forEach(([name,profile],index)=>{
    const button=document.getElementById(unifiedComfortButtonIds[name]);
    if(!button)return;
    if(name!=='steam'){
      const label=document.getElementById(`unifiedAroma${index+1}Label`);
      if(label)label.textContent=profile.name;
    }
    let feedback=comfortCommandFeedback[name];
    if(feedback?.expiresAt&&feedback.expiresAt<=now){delete comfortCommandFeedback[name];feedback=null;}
    const active=!!gpio[name];
    const status=active?'active':feedback?.status||'idle';
    const stateLabel=button.querySelector('[data-command-state]');
    const statusText={
      active:`กำลังพ่น · ${profile.purpose}`,
      pending:'กำลังส่งคำสั่ง…',
      success:`ส่งสำเร็จ · ${profile.purpose}`,
      error:adminView?'ส่งไม่สำเร็จ · ลองอีกครั้ง':'ยังไม่ตอบสนอง · ลองอีกครั้ง',
      idle:`พร้อมพ่น · ${profile.purpose}`,
    }[status];
    if(stateLabel)stateLabel.textContent=statusText;
    button.classList.toggle('active',status==='active');
    button.classList.toggle('command-success',status==='success');
    button.classList.toggle('command-error',status==='error');
    button.setAttribute('aria-pressed',active?'true':'false');
    if(!button.classList.contains('busy'))button.disabled=!gpioOk||safetyLatched||active||status==='pending';
    if(status!=='idle')states.push({name,profile,status,updatedAt:feedback?.updatedAt||now});
  });
  renderDebugAromaReference(current.labels||{});
  const summary=document.getElementById('unifiedComfortStatus');
  if(!summary)return;
  if(safetyLatched){summary.textContent=adminView?'Safety Locked':'โหมดปลอดภัย';summary.dataset.state='locked';syncUnifiedComfortDelivery('locked');return;}
  if(!gpioOk){summary.textContent=adminView?'Offline':'กำลังเชื่อมต่อ';summary.dataset.state='offline';syncUnifiedComfortDelivery('offline');return;}
  const priority={active:4,pending:3,error:2,success:1};
  states.sort((a,b)=>(priority[b.status]-priority[a.status])||(b.updatedAt-a.updatedAt));
  const latest=states[0];
  if(!latest){summary.textContent='พร้อมใช้ · 5 รายการ';summary.dataset.state='ready';syncUnifiedComfortDelivery('ready');return;}
  const prefix={
    active:'กำลังพ่น',pending:'กำลังส่ง',success:'ส่งสำเร็จ',
    error:adminView?'ส่งไม่สำเร็จ':'ลองอีกครั้ง',
  }[latest.status];
  summary.textContent=`${prefix} · ${latest.profile.name}`;
  summary.dataset.state=latest.status;
  syncUnifiedComfortDelivery(latest.status,latest.profile);
}
// Air quality is summarized from the three dedicated air sensors. The worst
// live metric wins; incomplete telemetry is capped at "ปานกลาง" so the UI
// never reports "ดี" or "ดีมาก" from only part of the sensor set.
function renderUnifiedAirQuality(environment={},devices={}){
  const card=document.getElementById('zoneSensorAirQuality'),value=document.getElementById('unifiedAirQuality'),detail=document.getElementById('unifiedAirQualityDetail');
  if(!card||!value||!detail)return;
  const metrics=[
    {name:'CO₂',raw:environment.co2_ppm,value:Number(environment.co2_ppm),device:devices.mhz19c,unit:'ppm',bands:[700,900,1200]},
    {name:'PM2.5',raw:environment.pm2_5_ug_m3,value:Number(environment.pm2_5_ug_m3),device:devices.pms7003,unit:'µg/m³',bands:[12,25,37.5]},
    {name:'VOC',raw:environment.voc_index,value:Number(environment.voc_index),device:devices.sgp40,unit:'Index',bands:[120,150,200]},
  ].filter(metric=>metric.raw!==null&&metric.raw!==undefined&&metric.raw!==''&&Number.isFinite(metric.value)&&metric.device?.status==='live');
  const grade=metric=>metric.value<=metric.bands[0]?3:metric.value<=metric.bands[1]?2:metric.value<=metric.bands[2]?1:0;
  const labels=['ควรปรับ','ปานกลาง','ดี','ดีมาก'],keys=['bad','moderate','good','excellent'];
  let key='unknown',label='รอข้อมูล';
  if(metrics.length){
    let score=Math.min(...metrics.map(grade));
    if(metrics.length<3)score=Math.min(score,1);
    key=keys[score];label=labels[score];
  }
  card.classList.remove('quality-unknown','quality-bad','quality-moderate','quality-good','quality-excellent','live','warning','offline');
  card.classList.add(`quality-${key}`);
  value.textContent=label;
  const adminView=currentPrincipal?.role==='admin';
  detail.textContent=adminView?`Air Sensor ${metrics.length}/3`:`ข้อมูลอากาศ ${metrics.length}/3`;
  card.title=metrics.length
    ? metrics.map(metric=>`${metric.name} ${metric.value} ${metric.unit}`).join(' · ')
    : adminView?'MH-Z19C, PMS7003 และ SGP40 ยังไม่มีข้อมูล Live':'กำลังรวบรวมข้อมูลอากาศ';
}

// Humidity uses the exact same five assessment bands as the Dashboard.
// Keeping one shared criterion prevents Control and Admin from reporting
// different risk levels for the same calibrated SHT3x-DIS reading.
function renderUnifiedHumidity(environment={},device={}){
  const card=document.getElementById('zoneSensorHumidity'),value=document.getElementById('unifiedHumidity'),levelEl=document.getElementById('unifiedHumidityLevel');
  if(!card||!value||!levelEl)return;
  const raw=environment.humidity_rh,humidity=Number(raw),status=device.status||'offline';
  const live=status==='live'&&raw!==null&&raw!==undefined&&raw!==''&&Number.isFinite(humidity);
  card.classList.remove('live','warning','offline','humidity-unknown',...dashboardAtmosphereLevels.map(level=>`humidity-${level.key}`));
  card.querySelectorAll('.humidity-level-scale > i').forEach(marker=>{
    marker.classList.remove('active');
    marker.removeAttribute('aria-current');
  });
  value.textContent=compactMetric(raw,'',1);
  if(!live){
    const warning=['stale','held','warming'].includes(status);
    card.classList.add(warning?'warning':'offline','humidity-unknown');
    levelEl.textContent=warning?'ข้อมูลไม่สด':'รอข้อมูล';
    card.title=currentPrincipal?.role==='admin'
      ?`${device.model||'SHT3x-DIS'} · ${sensorStatusTh[status]||status} · ยังไม่ประเมินระดับความชื้น`
      :'กำลังรวบรวมข้อมูลความชื้น';
    card.setAttribute('aria-label',`ความชื้น ${levelEl.textContent}`);
    return;
  }
  const criterion=dashboardAtmosphereCriteria.find(item=>item.id==='humidity');
  const score=criterion.score(humidity),level=dashboardAtmosphereLevels[score];
  card.classList.add('live',`humidity-${level.key}`);
  levelEl.textContent=level.label;
  const activeMarker=card.querySelector(`.humidity-level-scale > i[data-level="${level.key}"]`);
  if(activeMarker){activeMarker.classList.add('active');activeMarker.setAttribute('aria-current','true');}
  card.title=currentPrincipal?.role==='admin'
    ?`${humidity.toFixed(1)}%RH · ${level.label} · ${criterion.bands}`
    :`ความชื้น ${humidity.toFixed(1)}%RH · ${level.label}`;
  card.setAttribute('aria-label',`ความชื้น ${humidity.toFixed(1)} เปอร์เซ็นต์ ระดับ${level.label}`);
}

function renderUnifiedControl(state={},environment={},aircon={},bed={},music={}){
  const devices=environment.devices||{},gpio=state.gpio||{},sys=state.system||{},safety=state.safety||{};
  const adminView=currentPrincipal?.role==='admin';
  setUnifiedSensor('zoneSensorTemp','unifiedTemp',compactMetric(environment.temperature_c,'',1),devices.sht3x_dis);
  renderUnifiedHumidity(environment,devices.sht3x_dis||{});
  renderUnifiedAirQuality(environment,devices);
  setUnifiedSensor('zoneSensorLight','unifiedLight',compactMetric(environment.lux,'',1),devices.opt3001);
  const soundMetric=soundDisplayMetric(environment);
  setUnifiedSensor('zoneSensorSound','unifiedSound',compactMetric(soundMetric.value,'',soundMetric.digits),devices.sph0645);
  const soundState=document.getElementById('unifiedSoundState');
  if(soundState){
    soundState.textContent=adminView?'ค่าจาก ESP32 · dBA':'ระดับเสียง · dBA';
  }
  const bcg=state.sensor?.bcg||{},bcgBase={model:'BCG Sensor',data_age_s:bcg.data_age_s};
  const bcgMetric=value=>({...bcgBase,status:bcg.restored_after_restart&&value!==null&&value!==undefined?'stale':bcg.connected&&value!==null&&value!==undefined?'live':bcg.connected?'no_data':'offline'});
  setUnifiedSensor('zoneSensorHeart','unifiedHeartRate',compactMetric(bcg.heart_rate_bpm,'',0),bcgMetric(bcg.heart_rate_bpm));
  setUnifiedSensor('zoneSensorRespiration','unifiedRespiration',compactMetric(bcg.respiration_rate,'',1),bcgMetric(bcg.respiration_rate));
  const bedStatusShort=adminView
    ?BCG_STATUS_CONTROL_TH[bcg.status_code]||(bcg.status_text?'ไม่ทราบ':'--')
    :USER_BED_STATUS_TH[bcg.status_code]||'กำลังอ่านสถานะเตียง';
  const bedStatusFull=adminView
    ?BCG_STATUS_TH[bcg.status_code]||bcg.status_text||'รอสัญญาณจากเตียง'
    :USER_BED_STATUS_TH[bcg.status_code]||'กำลังอ่านสถานะเตียง';
  setUnifiedSensor('zoneSensorBed','unifiedBedPresence',bedStatusShort,bcgMetric(bcg.status_code));
  const bedStatusCard=document.getElementById('zoneSensorBed');
  if(bedStatusCard){
    bedStatusCard.title=`${bedStatusCard.title} · ${bedStatusFull}`;
    bedStatusCard.setAttribute('aria-label',`สถานะเตียง ${bedStatusShort} · ${bedStatusFull}`);
  }
  const roomState=document.getElementById('unifiedRoomState'),live=Number(environment.live_count)||0,total=Number(environment.total_count)||6;
  const sensorState=state.sensor||{},piSensorOnline=!!sensorState.esp32?.connected,bcgOnline=!!sensorState.bcg?.connected,gpioOnline=!!sys.gpio_available;
  const piState=gpioOnline&&piSensorOnline&&bcgOnline?'live':'degraded';
  const airSensorConnected=!!sensorState.sensorhub2?.connected;
  const airSensorLive=['mhz19c','pms7003','sgp40'].filter(key=>devices[key]?.status==='live').length;
  const airSensorState=airSensorConnected?(airSensorLive===3?'live':'degraded'):'offline';
  const airconControllerOnline=!!aircon.connected&&!aircon.stale,bedControllerOnline=!!bed.connected&&!bed.stale;
  setControllerNode('controllerPiNode','controllerPiStatus',piState,piState==='live'?'ONLINE':'DEGRADED',`GPIO ${gpioOnline?'OK':'FAIL'} · Sensor Set ${piSensorOnline?'OK':'OFF'} · BCG ${bcgOnline?'OK':'OFF'}`);
  setControllerNode('controllerAirSensorNode','controllerAirSensorStatus',airSensorState,airSensorState==='live'?'ONLINE':airSensorState==='degraded'?'DEGRADED':'OFFLINE',`${airSensorLive}/3 sensors live`);
  setControllerNode('controllerAirconNode','controllerAirconStatus',airconControllerOnline?'live':'offline',airconControllerOnline?'ONLINE':'OFFLINE',aircon.device_id||'controlhub1-pod1');
  setControllerNode('controllerBedNode','controllerBedStatus',bedControllerOnline?'live':'offline',bedControllerOnline?'ONLINE':'OFFLINE',bed.device_id||'controlhub2-bed-pod1');
  const controllerCount=[piState==='live',airSensorState==='live',airconControllerOnline,bedControllerOnline].filter(Boolean).length;
  roomState.textContent=safety.latched?'ฉุกเฉิน · ล็อกการควบคุม':controllerCount===4&&live===total?'พร้อมใช้งาน':controllerCount>0?'พร้อมใช้งานบางส่วน':'ระบบควบคุมไม่พร้อม';
  roomState.classList.toggle('good',!safety.latched&&controllerCount===4&&live===total&&!!safety.ready);

  const airconOnline=airconControllerOnline,airconOn=aircon.power===true;
  document.getElementById('unifiedAirconStatus').textContent=airconOnline
    ? aircon.power==null
      ? adminView?'คำสั่งล่าสุด · ยังไม่ทราบ':'กำลังตรวจสถานะแอร์'
      : airconOn?'แอร์เปิดอยู่':'แอร์ปิดอยู่'
    : adminView?'Offline':'กำลังเชื่อมต่อแอร์';
  // One touch target controls both states. The visual state and next command
  // always derive from the latest ESP32 ACK, never from a click alone.
  const powerButton=document.getElementById('unifiedAirconPowerBtn');
  if(powerButton){
    const powerKnown=typeof aircon.power==='boolean';
    const nextCommand=aircon.power===true?'off':'on';
    const blockedBySafety=!!safety.latched&&nextCommand!=='off';
    const actionLabel=powerButton.querySelector('[data-action-label]');
    const stateLabel=powerButton.querySelector('[data-state-label]');
    powerButton.dataset.airconCommand=nextCommand;
    powerButton.disabled=!airconOnline||airconRequestBusy||!!aircon.command_pending||blockedBySafety;
    powerButton.classList.toggle('command-reference',powerKnown);
    powerButton.classList.toggle('on',aircon.power===true);
    powerButton.classList.toggle('off',aircon.power===false);
    powerButton.classList.toggle('state-unknown',!powerKnown);
    powerButton.setAttribute('aria-pressed',aircon.power===true?'true':'false');
    powerButton.setAttribute('aria-label',nextCommand==='off'?'ปิดเครื่องปรับอากาศ':'เปิดเครื่องปรับอากาศ');
    if(actionLabel)actionLabel.textContent=nextCommand==='off'?'ปิด':'เปิด';
    if(stateLabel)stateLabel.textContent=!powerKnown?'ยังไม่ทราบ':aircon.power===true?'เปิดอยู่':'ปิดอยู่';
    powerButton.title=!airconOnline
      ? adminView?'ESP32 Aircon Offline':'กำลังเชื่อมต่อแอร์'
      : blockedBySafety
        ? 'ระบบอยู่ในโหมดปลอดภัย ขณะนี้ปิดแอร์ได้เท่านั้น'
        : adminView
          ? `${nextCommand==='off'?'ปิด':'เปิด'}เครื่องปรับอากาศ · สถานะอ้างอิงคำสั่ง IR ที่ ESP32 ยืนยันล่าสุด`
          : `${nextCommand==='off'?'ปิด':'เปิด'}แอร์`;
  }
  const swingState=resolveUnifiedAirconSwingState(aircon),swingOn=swingState===true;
  const swingButton=document.getElementById('unifiedSwingBtn');
  const swingAllowed=airconOnline&&airconOn&&!safety.latched;
  syncUnifiedSwitch('unifiedSwingBtn',swingOn,swingAllowed,'ปิด',airconOnline?'เปิด':adminView?'OFFLINE':'รอเชื่อมต่อ');
  if(swingButton){
    swingButton.dataset.airconCommand=swingOn?'swing_off':'swing_on';
    swingButton.classList.toggle('state-unknown',swingState==null);
    const swingStateLabel=swingButton.querySelector('[data-state-label]');
    if(swingStateLabel&&swingState==null)swingStateLabel.textContent='ยังไม่ทราบ';
    swingButton.title=!airconOnline
      ? adminView?'ESP32 Aircon Offline':'กำลังเชื่อมต่อแอร์'
      : !airconOn
        ? 'เปิดแอร์ก่อนควบคุมสวิง'
        : swingState==null
          ? adminView?'ยังไม่มีสถานะสวิงจาก ESP32 · กดเพื่อส่งคำสั่งเปิดสวิง':'กดเพื่อเปิดสวิงพัดลม'
          : adminView
            ? `${swingOn?'ปิด':'เปิด'}สวิงพัดลม · สถานะตามคำสั่ง IR ล่าสุด`
            : `${swingOn?'ปิด':'เปิด'}สวิงพัดลม`;
  }
  const fanButton=document.getElementById('unifiedFanLevelBtn');
  const fanLevel=normalizedAirconFanLevel(aircon.fan_level);
  const nextFanLevel=fanLevel==null?1:(fanLevel%5)+1;
  const fanAllowed=airconOnline&&airconOn&&!safety.latched;
  if(fanButton){
    // The installed AC exposes no physical fan-speed feedback. Users may send
    // the cycle command, but only Admin sees the Pi's logical 1..5 reference.
    // This prevents an acknowledged IR transmission being mistaken for a
    // measured fan-speed state when the remote and AC have drifted out of sync.
    const showFanReference=currentPrincipal?.role==='admin';
    fanButton.disabled=!fanAllowed||airconRequestBusy||!!aircon.command_pending;
    fanButton.classList.toggle('state-unknown',fanLevel==null);
    fanButton.classList.toggle('on',fanLevel!=null&&fanAllowed);
    fanButton.dataset.airconCommand='fan';
    const actionLabel=fanButton.querySelector('[data-action-label]');
    const stateLabel=fanButton.querySelector('[data-state-label]');
    if(actionLabel)actionLabel.textContent=showFanReference
      ? `อ้างอิง ${fanLevel??'--'}/5`
      : 'ปรับแรงลม';
    if(stateLabel)stateLabel.textContent=showFanReference
      ? `คำสั่งถัดไป ${nextFanLevel}`
      : 'กดเพื่อปรับ';
    fanButton.setAttribute('aria-label',showFanReference
      ? `ปรับแรงลม · ค่าอ้างอิงถัดไป ${nextFanLevel} จาก 5`
      : 'ปรับแรงลมแอร์');
    fanButton.title=!airconOnline
      ? adminView?'ESP32 Aircon Offline':'กำลังเชื่อมต่อแอร์'
      : !airconOn
        ? 'เปิดแอร์ก่อนปรับระดับพัดลม'
        : showFanReference
          ? `ค่าอ้างอิงตามคำสั่งล่าสุด ${fanLevel??'ยังไม่ทราบ'} จาก 5 · ไม่ใช่ค่าที่วัดจากแอร์`
          : 'กดเพื่อปรับแรงลมหนึ่งระดับ';
  }
  const tempSelect=document.getElementById('unifiedAirconTemp'),desiredTemp=Number(aircon.desired_temperature_c);
  if(Number.isInteger(unifiedAirconDraftTemp)){
    tempSelect.value=String(unifiedAirconDraftTemp);
  }else if(document.activeElement!==tempSelect&&Number.isInteger(desiredTemp)&&desiredTemp>=AIRCON_DESIRED_TEMPERATURE_MIN_C&&desiredTemp<=AIRCON_DESIRED_TEMPERATURE_MAX_C){
    tempSelect.value=String(desiredTemp);
  }
  tempSelect.disabled=!airconOnline||!!safety.latched||airconRequestBusy||!!aircon.command_pending;
  syncUnifiedAirconComfort(
    airconOn,
    airconOnline,
    Number.isInteger(unifiedAirconDraftTemp)?unifiedAirconDraftTemp:desiredTemp,
    environment.temperature_c
  );

  const gpioOk=!!sys.gpio_available;
  const activeLights=['led','star_light','red_light_face','red_light_body','red_light_leg'].filter(name=>!!gpio[name]).length;
  document.getElementById('unifiedLightStatus').textContent=gpioOk?`${activeLights}/5 เปิด`:adminView?'Offline':'กำลังเชื่อมต่อ';
  syncUnifiedPodRoomLight(!!gpio.led,gpioOk&&!safety.latched);
  syncUnifiedStarLight(!!gpio.star_light,gpioOk&&!safety.latched);
  syncUnifiedRedLights(gpio,gpioOk&&!safety.latched);
  renderUnifiedComfort(gpio,gpioOk,!!safety.latched);

  const audioOn=!!music.playing;
  document.getElementById('unifiedAudioStatus').textContent=audioOn?(music.paused?'พักอยู่':'เล่นอยู่'):'พร้อม';
  const unifiedVolume=document.getElementById('unifiedVolume');
  if(document.activeElement!==unifiedVolume)unifiedVolume.value=music.volume??60;
  unifiedVolume.setAttribute('aria-valuetext',`${music.volume??60}%`);
  unifiedVolume.style.setProperty('--range-value',`${music.volume??60}%`);
  document.getElementById('unifiedVolumeText').textContent=`${music.volume??60}%`;
  const selected=document.getElementById('unifiedTrackSelect');if(selected&&selectedTrack&&selected.value!==selectedTrack)selected.value=selectedTrack;
  renderUnifiedAudioPlayer(music,safety);

  const bedOnline=bedControllerOnline,bedStatus=document.getElementById('unifiedBedStatus');
  bedStatus.textContent=bedOnline?'พร้อมควบคุม':bed.mqtt_connected?'กำลังเชื่อมต่อ':adminView?'ออฟไลน์':'กำลังเชื่อมต่อ';
  bedStatus.title=bedOnline
    ? adminView
      ? `ESP32 Bed Online${Number.isFinite(Number(bed.data_age_s))?` · ล่าสุด ${Number(bed.data_age_s).toFixed(1)} วินาที`:''}`
      : 'เตียงพร้อมปรับระดับ'
    : adminView
      ? bed.error||'ปุ่มขยับเตียงจะเปิดอัตโนมัติเมื่อ ESP32 Bed กลับมา Online'
      : 'กำลังเชื่อมต่อระบบเตียง';
  renderUnifiedBedMotion(bed);
  const doorOpen=document.getElementById('unifiedDoorOpenBtn'),doorClose=document.getElementById('unifiedDoorCloseBtn');
  document.getElementById('unifiedDoorStatus').textContent=gpioOk?'พร้อมใช้งาน':adminView?'Offline':'กำลังเชื่อมต่อ';
  if(!doorOpen.classList.contains('busy'))doorOpen.disabled=!gpioOk||doorBusy;
  if(!doorClose.classList.contains('busy'))doorClose.disabled=!gpioOk||doorBusy||!!safety.latched;

}
