let brainwaveCatalog=null;

async function loadBrainwaveLab(){
  if(currentPrincipal?.role!=='admin')return;
  const select=document.getElementById('brainwavePreset');
  if(!select)return;
  try{
    const response=await fetch('/api/admin/brainwave/presets',{cache:'no-store'});
    if(!response.ok)throw new Error(`HTTP ${response.status}`);
    brainwaveCatalog=await response.json();
    select.replaceChildren();
    brainwaveCatalog.presets.forEach(preset=>{
      const option=document.createElement('option');
      option.value=preset.id;option.textContent=preset.name;
      select.appendChild(option);
    });
    select.disabled=!brainwaveCatalog.presets.length;
    document.getElementById('brainwavePreviewBtn').disabled=!brainwaveCatalog.presets.length||!brainwaveCatalog.player;
    document.getElementById('brainwaveLabVersion').textContent=`${brainwaveCatalog.version} · ${brainwaveCatalog.output.format}`;
    renderBrainwavePreset();
  }catch(error){
    select.innerHTML='<option value="">โหลด Preset ไม่สำเร็จ</option>';select.disabled=true;
    document.getElementById('brainwavePreviewBtn').disabled=true;
    document.getElementById('brainwaveLabVersion').textContent=error instanceof Error?error.message:'โหลดข้อมูลไม่สำเร็จ';
  }
}

function renderBrainwavePreset(){
  const id=document.getElementById('brainwavePreset')?.value;
  const preset=brainwaveCatalog?.presets?.find(item=>item.id===id);
  if(!preset)return;
  document.getElementById('brainwavePresetName').textContent=`${preset.name} · ${preset.evidence}`;
  document.getElementById('brainwavePresetPurpose').textContent=preset.purpose;
  document.getElementById('brainwavePresetPhases').textContent=preset.phases
    .map(phase=>phase.modulation_hz>0?`${phase.name}: ${phase.carrier_hz} Hz / ${phase.modulation_hz} Hz AM`:`${phase.name}: ${phase.carrier_hz} Hz / no AM`)
    .join(' → ');
}

async function playBrainwavePreview(btn){
  const presetId=document.getElementById('brainwavePreset')?.value;
  if(!presetId){toast('กรุณาเลือก Brainwave preset','error');return;}
  const occupied=!!current.session?.active;
  if(occupied&&!await confirmAction({
    title:'มีผู้ใช้งานอยู่ใน ZEEP',
    message:'เสียงนี้เป็น Experimental Wellness Audio และจะเล่นออกลำโพงจริง กรุณายืนยันว่าได้รับอนุญาตจากผู้ใช้งานแล้ว',
    confirmText:'ได้รับอนุญาต · เล่นเสียง',tone:'warning',icon:'♫'
  }))return;
  const duration=Number(document.getElementById('brainwaveDuration')?.value||30);
  const volume=Number(document.getElementById('brainwaveVolume')?.value||35);
  const result=await debugSend(
    btn,'Pi Audio',`brainwave ${presetId} · ${duration}s · ${volume}%`,
    '/api/admin/brainwave/preview',
    {preset_id:presetId,duration_seconds:duration,volume,confirm_occupied:occupied}
  );
  if(result?.state)current.music={...(current.music||{}),...result.state};
}

function setDebugControllerState(id,status,label,detail=''){
  const node=document.getElementById(id);if(!node)return;
  node.dataset.status=status;
  node.textContent=detail?`${label} · ${detail}`:label;
}

function renderControlDebug(state={}){
  if(document.body.dataset.view!=='control_debug')return;
  const system=state.system||{},aircon=state.aircon||{},bed=state.bed_control||{},music=state.music||{};
  setDebugControllerState('debugPiState',system.gpio_available?'live':'offline',system.gpio_available?'ONLINE':'OFFLINE');
  setDebugControllerState('debugAirconState',aircon.connected?(aircon.stale?'stale':'live'):'offline',aircon.connected?(aircon.stale?'STALE':'ONLINE'):'OFFLINE',aircon.command_pending?'WAITING ACK':'READY');
  setDebugControllerState('debugBedState',bed.connected?(bed.stale?'stale':'live'):'offline',bed.connected?(bed.stale?'STALE':'ONLINE'):'OFFLINE',bed.command_pending?'MOVING / WAITING':'READY');
  setDebugControllerState('debugAudioState',music.error?'error':'live',music.error?'ERROR':music.playing?(music.paused?'PAUSED':'PLAYING'):'READY',music.track||'LOCAL PLAYER');
}

let doorBusy = false;
let doorVisualTimer = null;

// The ZEEP currently has no door-position sensor. Animate a slow slide in the
// same direction as the physical door and retain only "last command" wording;
// never present the drawing as a confirmed physical open/closed state.
function startUnifiedDoorMotion(action){
  const map=document.getElementById('podDoorMap');
  const state=document.getElementById('podDoorState');
  if(!map||!state)return;
  clearTimeout(doorVisualTimer);
  map.classList.remove('command-open','command-close');
  // Force a fresh animation when the same command is sent twice in a row.
  map.getBoundingClientRect();
  map.classList.add(action==='open'?'command-open':'command-close');
  state.textContent=action==='open'?'กำลังเปิดประตู':'กำลังปิดประตู';
  map.setAttribute('aria-label',action==='open'?'กำลังส่งคำสั่งเปิดประตู':'กำลังส่งคำสั่งปิดประตู');
}

function finishUnifiedDoorMotion(action,succeeded){
  const map=document.getElementById('podDoorMap');
  const state=document.getElementById('podDoorState');
  if(!map||!state)return;
  clearTimeout(doorVisualTimer);
  doorVisualTimer=setTimeout(()=>{
    map.classList.remove('command-open','command-close');
    if(succeeded){
      map.classList.toggle('last-open-command',action==='open');
      map.classList.toggle('last-close-command',action==='close');
      state.textContent=action==='open'?'คำสั่งล่าสุด · เปิด':'คำสั่งล่าสุด · ปิด';
      map.setAttribute('aria-label',`ส่งคำสั่ง${action==='open'?'เปิด':'ปิด'}ประตูแล้ว ตำแหน่งจริงยังไม่ได้รับการยืนยัน`);
    }else{
      const adminView=currentPrincipal?.role==='admin';
      state.textContent=adminView?'คำสั่งไม่สำเร็จ':'ยังไม่ตอบสนอง · ลองอีกครั้ง';
      map.setAttribute('aria-label',adminView
        ?'คำสั่งประตูไม่สำเร็จ ตำแหน่งจริงยังไม่ได้รับการยืนยัน'
        :'ประตูยังไม่ตอบสนอง กรุณาลองอีกครั้ง');
    }
  },1450);
}

async function doorAction(action, btn){
  if (doorBusy || !current.system?.gpio_available) return;
  doorBusy = true;
  startUnifiedDoorMotion(action);
  const doorButtons=['doorOpenBtn','doorCloseBtn','unifiedDoorOpenBtn','unifiedDoorCloseBtn']
    .map(id=>document.getElementById(id)).filter(Boolean);
  doorButtons.forEach(button=>{button.disabled=true;});
  btn.classList.add('busy');btn.setAttribute('aria-busy','true');
  const progress=commandProgressOverlay(btn);
  let succeeded=false;
  try {
    const res = await post(`/api/door/${action}`);
    succeeded=!!res;
    flashCommandResult(btn,succeeded);
    if (res) toast(action === 'open' ? 'ส่งคำสั่งเปิดประตูแล้ว' : 'ส่งคำสั่งปิดประตูแล้ว', 'ok', 2200);
  } finally {
    progress?.remove();
    btn.classList.remove('busy');btn.removeAttribute('aria-busy');
    finishUnifiedDoorMotion(action,succeeded);
    setTimeout(()=>{ doorBusy = false; }, 1550);
  }
}
async function musicCmd(btn,url){
  const stopping=url.endsWith('/stop');
  if(stopping){
    // Invalidate any older play response before sending Stop. The Pi returns
    // its authoritative stopped state so the toggle changes immediately.
    unifiedAudioRequestSequence+=1;
    unifiedAudioPendingTrack=null;
  }
  if(btn){
    const intent=url.endsWith('/stop')?'stop':url.endsWith('/pause')?'pause':'play';
    btn.dataset.interactionIntent=intent;
    btn.dataset.interactionLabel={stop:'หยุดเสียงบรรยากาศ',pause:'พักเสียงบรรยากาศ',play:'เล่นเสียงบรรยากาศ'}[intent];
  }
  const result=await withBusy(btn,()=>post(url));
  if(stopping&&result?.state){
    current.music={...(current.music||{}),...result.state};
    renderUnifiedAudioPlayer(current.music,current.safety||{});
    toast('หยุดเสียงใน ZEEP แล้ว','ok',1600);
  }
  flashCommandResult(btn,!!result);
  return result;
}
async function playSelected(btn){
  if (!selectedTrack){ toast('ยังไม่ได้เลือกเพลง', '', 1800); return; }
  const t = selectedTrack;
  const loop = unifiedAudioMode==='repeat_one';
  const requestSequence=++unifiedAudioRequestSequence;
  unifiedAudioPendingTrack=t;
  renderUnifiedAudioPlayer(current.music||{},current.safety||{});
  if(btn){
    btn.dataset.interactionIntent='play';
    btn.dataset.interactionLabel=`เล่น ${trackMeta(t).title}`;
  }
  const result=await withBusy(btn, async ()=>{
    const r = await post('/api/music/play', {
      track:t, loop, queue:unifiedAudioMode==='queue', user_initiated:!!btn,
    });
    if (r){
      toast(`กำลังเล่น: ${trackMeta(t).title}${loop ? ' · เล่นซ้ำ' : ' · คิวเพลง'}`, 'ok', 2200);
    }
    flashCommandResult(btn,!!r);
    return r;
  });
  if(requestSequence!==unifiedAudioRequestSequence)return result;
  unifiedAudioPendingTrack=null;
  if(result?.state){
    current.music=result.state;
    selectedTrack=result.state.track||t;
  }else if(current.music?.playing&&current.music.track){
    // A failed replacement must return the selector/title to the track that
    // the Pi still reports as playing; never leave a false visual state.
    selectedTrack=current.music.track;
  }
  const select=document.getElementById('unifiedTrackSelect');if(select&&selectedTrack)select.value=selectedTrack;
  Object.entries(trackEls).forEach(([name,entry])=>entry.row.classList.toggle('sel',name===selectedTrack));
  renderUnifiedAudioPlayer(current.music||{},current.safety||{});
  return result;
}
let volTimer;
function setVolume(v){
  document.getElementById('volText').textContent = v;
  const unifiedText=document.getElementById('unifiedVolumeText');if(unifiedText)unifiedText.textContent=`${v}%`;
  const unifiedRange=document.getElementById('unifiedVolume');if(unifiedRange){unifiedRange.setAttribute('aria-valuetext',`${v}%`);unifiedRange.style.setProperty('--range-value',`${v}%`);}
  clearTimeout(volTimer);
  volTimer = setTimeout(()=>post('/api/music/volume', {volume:Number(v)}), 120);
}
async function loadTracks(){
  const root = document.getElementById('trackList');
  if (!root.children.length){
    root.innerHTML = '<div class="mini" style="margin-top:2px">กำลังโหลดรายการเพลง…</div>';
  }
  try {
    const r = await fetch('/api/music'); const d = await r.json();
    root.innerHTML = '';
    Object.keys(trackEls).forEach(k=>delete trackEls[k]);
    if (!d.tracks.length){
      root.innerHTML = '<div class="mini" style="margin-top:2px">ไม่มีไฟล์เพลงในโฟลเดอร์ music/</div>';
      selectedTrack = null;
      const unified=document.getElementById('unifiedTrackSelect');if(unified){unified.innerHTML='<option value="">ไม่มีไฟล์เสียง</option>';unified.disabled=true;}
      const debug=document.getElementById('debugTrackSelect');if(debug){debug.innerHTML='<option value="">ไม่มีไฟล์เสียง</option>';debug.disabled=true;}
      return;
    }
    if(d.state&&typeof d.state==='object')current.music={...(current.music||{}),...d.state};
    if (d.state?.playing&&d.tracks.includes(d.state.track)) selectedTrack=d.state.track;
    else if (!d.tracks.includes(selectedTrack)) selectedTrack = d.tracks[0];
    const unified=document.getElementById('unifiedTrackSelect');
    if(unified){
      unified.replaceChildren();unified.disabled=false;
      d.tracks.forEach(track=>{const option=document.createElement('option');option.value=track;option.textContent=trackMeta(track).title;unified.appendChild(option);});
      unified.value=selectedTrack;
    }
    const debug=document.getElementById('debugTrackSelect');
    if(debug){
      debug.replaceChildren();debug.disabled=false;
      d.tracks.forEach(track=>{const option=document.createElement('option');option.value=track;option.textContent=trackMeta(track).title;debug.appendChild(option);});
      debug.value=selectedTrack;
    }
    d.tracks.forEach(t=>{
      const meta = trackMeta(t);
      const row = document.createElement('button'); row.className = 'track-row';
      const info = document.createElement('div');
      const title = document.createElement('b'); title.textContent = meta.title;
      const desc = document.createElement('div'); desc.className = 'desc'; desc.textContent = meta.desc;
      info.append(title, desc);
      row.appendChild(info);
      if (meta.badge){
        const badge = document.createElement('span');
        badge.className = 'badge' + (meta.head ? ' head' : '');
        badge.textContent = meta.badge;
        row.appendChild(badge);
      }
      row.onclick = ()=>unifiedSelectTrack(t,row);
      if (t === selectedTrack) row.classList.add('sel');
      root.appendChild(row);
      trackEls[t] = {row};
    });
    renderUnifiedAudioPlayer(current.music||{},current.safety||{});
  } catch {
    root.innerHTML = '<div class="mini" style="margin-top:2px">เชื่อมต่อ server ไม่ได้</div>';
  }
}
