/* Adaptive journey: observation first, never sends an equipment command. */
let journeySelectedSession = '';
let journeyData = null;
let journeyRequest = 0;
let journeyIdentity = '';
let journeyLoading = false;

function resetJourneyContext() {
  journeySelectedSession = ''; journeyData = null; journeyRequest += 1;
  if (document.getElementById('journeyCard')) renderJourney(null);
}

function selectJourneySession(sessionId) {
  journeyRequest += 1;
  journeySelectedSession = sessionId || '';
  journeyData = null;
  renderJourney(null);
  refreshJourney();
}

function journeySessionId() {
  return document.body.dataset.view === 'sessions'
    ? journeySelectedSession : current?.session?.session_id || '';
}

async function refreshJourney() {
  const root = document.getElementById('journeyCard');
  if (!root) return;
  const identity = `${currentPrincipal?.subject || ''}:${currentPrincipal?.account_key || ''}`;
  if (journeyIdentity && identity !== journeyIdentity) {
    journeySelectedSession = ''; journeyData = null; journeyRequest += 1;
  }
  journeyIdentity = identity;
  const sid = journeySessionId();
  if (!sid || !currentPrincipal) { renderJourney(null); return; }
  if (journeyLoading) return;
  const request = ++journeyRequest;
  journeyLoading = true;
  try {
    const response = await fetch(`/api/v1/adaptive/sessions/${encodeURIComponent(sid)}`, {
      cache: 'no-store', headers: authenticatedHeaders(),
    });
    if (!response.ok) throw new Error('load_failed');
    const payload = await response.json();
    if (request !== journeyRequest || sid !== journeySessionId()) return;
    journeyData = payload.data;
    renderJourney(journeyData);
  } catch {
    if (request === journeyRequest) {
      journeyData = null; renderJourney(null);
      document.getElementById('journeyStatus').textContent = 'ยังโหลดข้อมูลไม่ได้ กรุณาลองอีกครั้ง';
    }
  } finally {
    journeyLoading = false;
    if (request !== journeyRequest && currentPrincipal && journeySessionId()) refreshJourney();
  }
}

function renderJourney(data) {
  const put = (id, text) => { document.getElementById(id).textContent = text; };
  for (const id of ['journeyDecisions', 'journeyEvents', 'journeyOutcomes', 'journeyChannels']) {
    document.getElementById(id).replaceChildren();
  }
  put('journeyStatus', data ? `ข้อมูลเซนเซอร์ ${data.journey.samples_used} จุด · แสดงเหตุการณ์ล่าสุดไม่เกิน 100 รายการ${data.data_truncated ? ' · ข้อมูลถูกจำกัดตามขนาด' : ''} · ไม่เปลี่ยนคะแนน` : 'เลือกรายการการพักเพื่อดูข้อมูล');
  put('journeyComfort', data?.comfort_reference?.message || 'ยังไม่มีข้อมูลอ้างอิง');
  put('journeyCoach', data?.recommendation?.message || 'ยังไม่มีข้อเสนอให้ปรับอุปกรณ์');
  if (!data) return;
  const labels = Object.fromEntries(data.journey.channels.map(item => [item.key, item]));
  for (const [key, range] of Object.entries(data.comfort_reference.ranges)) {
    const line = document.createElement('small');
    line.textContent = `${labels[key]?.label || key}: ${range.low}–${range.high} ${labels[key]?.unit || ''} · ${range.sessions} ครั้ง`;
    document.getElementById('journeyComfort').append(line);
  }
  const item = data.recommendation.item;
  if (item) {
    put('journeyCoach', `${item.title} — ${item.reason}`);
    for (const [value, label] of [['accept', item.confirmation_label], ['snooze', 'ไว้ภายหลัง'], ['reject', 'คงเดิม']]) {
      const button = document.createElement('button'); button.className = 'btn'; button.type = 'button'; button.textContent = label;
      button.onclick = () => decideJourney(value, button);
      document.getElementById('journeyDecisions').append(button);
    }
  }
  for (const channel of data.journey.channels) {
    const chip = document.createElement('span');
    chip.textContent = `${channel.label} · ${channel.available ? 'มีข้อมูล' : 'ไม่มีข้อมูล'}`;
    document.getElementById('journeyChannels').append(chip);
  }
  for (const event of data.journey.events.slice(-100)) {
    const row = document.createElement('li'), time = document.createElement('time'), body = document.createElement('div');
    time.textContent = new Date(event.t * 1000).toLocaleTimeString('th-TH', { hour12: false });
    body.textContent = event.label;
    const detail = document.createElement('small');
    detail.textContent = event.kind === 'sensor_change' ? `${event.before} → ${event.after} ${event.unit}`
      : event.kind === 'command' ? 'บันทึกคำสั่งแล้ว · ยังไม่ทราบผลจากอุปกรณ์จริง'
      : event.kind === 'acoustic' ? 'จำแนกเบื้องต้นจากลักษณะเสียง' : '';
    body.append(detail); row.append(time, body); document.getElementById('journeyEvents').append(row);
  }
  if (!data.journey.events.length) put('journeyEvents', 'ยังไม่พบเหตุการณ์ที่เด่นชัด');
  for (const outcome of data.outcomes.slice(-10)) {
    const article = document.createElement('article'); article.className = 'journey-outcome';
    const title = document.createElement('b'); title.textContent = `${outcome.label} · ${new Date(outcome.t * 1000).toLocaleTimeString('th-TH')}`;
    const note = document.createElement('p'); note.textContent = outcome.message;
    const list = document.createElement('ul');
    for (const metric of outcome.metrics) {
      const row = document.createElement('li');
      const direction = {toward_reference: ' · ใกล้ช่วงที่เคยสบายขึ้น', away_from_reference: ' · ห่างจากช่วงที่เคยสบาย', within_reference: ' · อยู่ในช่วงที่เคยสบาย'}[metric.comfort_direction] || '';
      row.textContent = metric.delta == null ? `${metric.label}: ข้อมูลยังไม่พอเปรียบเทียบ`
        : `${metric.label}: ${metric.before.value} → ${metric.after.value} ${metric.unit}${direction}`;
      list.append(row);
    }
    article.append(title, note, list); document.getElementById('journeyOutcomes').append(article);
  }
  if (!data.outcomes.length) put('journeyOutcomes', 'ยังไม่มีคำสั่งอุปกรณ์ในช่วงที่บันทึก');
}

async function saveJourneyComfort(button) {
  const response = document.getElementById('journeyFeedback').value;
  const sid = journeySessionId();
  if (!response || !sid || !journeyData) { toast('กรุณาเลือกการพักและคำตอบก่อน'); return; }
  button.disabled = true;
  try {
    const result = await post(`/api/v1/adaptive/sessions/${encodeURIComponent(sid)}/comfort`, {
      response, use_for_personalization: true, request_id: crypto.randomUUID(),
    });
    if (result) toast('บันทึกความเห็นแล้ว ขอบคุณครับ');
  } finally { button.disabled = false; }
}

async function decideJourney(decision, button) {
  const item = journeyData?.recommendation?.item, sid = journeySessionId();
  if (!item || !sid) return;
  button.disabled = true;
  try {
    const result = await post(`/api/v1/adaptive/sessions/${encodeURIComponent(sid)}/decisions`, {
      recommendation_id: item.id, decision, request_id: crypto.randomUUID(),
    });
    if (!result) return;
    toast(decision === 'accept' ? 'รับคำแนะนำแล้ว กรุณาเลือกปรับอุปกรณ์ในหน้าควบคุม' : 'บันทึกแล้ว ระบบจะพักคำแนะนำไว้ก่อน');
    if (decision === 'accept') window.location.assign('/control');
    else refreshJourney();
  } finally { button.disabled = false; }
}

setInterval(() => {
  if (document.body.dataset.view === 'monitor') refreshJourney();
}, 15000);
