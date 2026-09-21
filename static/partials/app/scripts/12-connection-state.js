/* ---------- shared live status: transport is not sensor quality ---------- */
function connectionPresentation({mode, receivedAt, frame, now, authenticated}) {
  const age = Number.isFinite(receivedAt) && receivedAt > 0
    ? Math.max(0, Math.floor((now - receivedAt) / 1000)) : null;
  const last = age == null ? 'ยังไม่ได้รับข้อมูล' : `รับข้อมูลล่าสุด ${age} วินาทีที่แล้ว`;
  if (!authenticated) return {hidden: true, tone: 'waiting', title: '', detail: ''};
  if (mode === 'offline' || (age != null && age > 12)) {
    return {
      tone: 'offline', title: age == null ? 'กำลังเชื่อมต่อข้อมูล' : 'ขาดการเชื่อมต่อ · แสดงค่าล่าสุด',
      detail: `${last} · ระบบกำลังเชื่อมต่อใหม่`,
    };
  }
  if (mode === 'connecting') {
    return {tone: 'waiting', title: 'เชื่อมต่อแล้ว · รอข้อมูลใหม่', detail: last};
  }
  if (age == null || !frame || frame.sequence == null || frame.data_age_s == null) {
    return {
      tone: 'waiting', title: 'กำลังรอข้อมูลรอบแรก',
      detail: 'เชื่อมต่อกับระบบแล้ว · รอข้อมูลจากเซนเซอร์',
    };
  }
  const frameAge = frame.data_age_s;
  const sensorAge = Number.isFinite(frameAge) && frameAge >= 0
    ? `${Math.floor(frameAge + age)} วินาทีที่แล้ว` : 'ไม่ทราบเวลา';
  // Mirror the server frame-expiry window for display only; never a control gate.
  const expiry = Number.isFinite(frame.refresh_s) ? Math.max(15, frame.refresh_s * 3) : 30;
  if (frame.stale !== false || !Number.isInteger(frame.sequence) || frame.sequence < 0
      || !Number.isFinite(frameAge) || frameAge < 0 || frameAge + age > expiry) {
    return {
      tone: 'stale', title: 'ข้อมูลเซนเซอร์ยังไม่อัปเดต · แสดงค่าล่าสุด',
      detail: `ข้อมูลรอบล่าสุด ${sensorAge} · รอข้อมูลรอบใหม่`,
    };
  }
  return {
    tone: mode === 'rest' ? 'fallback' : 'connected',
    title: mode === 'rest' ? 'เชื่อมต่อผ่านช่องทางสำรอง' : 'เชื่อมต่อแล้ว',
    detail: `ข้อมูลรอบล่าสุด ${sensorAge} · ตรวจคุณภาพแยกแต่ละเซนเซอร์`,
  };
}

function isLiveStateSnapshot(value) {
  return !!value && typeof value === 'object' && !Array.isArray(value)
    && !!value.sensor && typeof value.sensor === 'object' && !Array.isArray(value.sensor)
    && !!value.session && typeof value.session === 'object' && !Array.isArray(value.session);
}

let connectionTransport = 'offline';
function renderConnectionState(mode = connectionTransport) {
  connectionTransport = mode;
  const banner = document.getElementById('connectionState');
  if (!banner) return;
  const state = connectionPresentation({
    mode, receivedAt: lastServerUpdateAt, frame: current.sensor_frame,
    now: Date.now(), authenticated: !!currentPrincipal && !sessionEndShown,
  });
  banner.hidden = !!state.hidden;
  banner.dataset.tone = state.tone;
  document.body.dataset.connection = state.hidden ? 'hidden' : state.tone;
  const title = document.getElementById('connectionStateTitle');
  const detail = document.getElementById('connectionStateDetail');
  // Announce transitions only; the one-second age ticker is not a live region.
  if (title.textContent !== state.title) title.textContent = state.title;
  if (detail.textContent !== state.detail) detail.textContent = state.detail;
}
