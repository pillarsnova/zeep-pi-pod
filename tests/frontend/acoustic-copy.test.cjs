const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname,
  '../../static/partials/app/scripts/08-sensors-monitor.js'), 'utf8');
const context = vm.createContext({ setInterval() {} });
vm.runInContext(source, context);

const descriptions = {
  quiet: 'เสียงเบาในช่วงที่วัด ไม่ได้หมายถึงไม่มีเสียง',
  steady_equipment_like: 'เสียงต่อเนื่อง เช่น พัดลมหรือแอร์',
  speech_like: 'จังหวะเสียงคล้ายคำพูด ไม่ถอดคำหรือระบุผู้พูด',
  snore_like: 'จังหวะเสียงคล้ายการกรน ไม่ใช่ผลวินิจฉัย',
  impact_like: 'เสียงฉับพลัน เช่น ประตูหรือวัตถุกระทบ',
};

for (const [key, description] of Object.entries(descriptions)) {
  test(`Smart Ear explains ${key} consistently without changing measurements`, () => {
    const text = context.acousticClassificationDetail(key, 0.82);
    assert.equal(text, `${description} · ความมั่นใจของระบบ 82%`);
    const event = { key, category: 'dsp_label', confidence: 0.82, window_count: 2 };
    assert.equal(context.acousticEventDetail(event), `${text} · 2 ช่วงวัด`);
    assert.deepEqual(event, {
      key, category: 'dsp_label', confidence: 0.82, window_count: 2,
    });
  });
}

test('unknown labels and missing confidence do not become a source or zero', () => {
  assert.equal(context.acousticClassificationDetail('unknown', null),
    'ยังจำแนกลักษณะเสียงไม่ได้ · ไม่ระบุความมั่นใจ');
});

test('sound level event details still report measured values', () => {
  assert.equal(context.acousticEventDetail({
    key: 'rapid_change', from_dba: 40, to_dba: 48, delta_db: 8,
  }), '40.0 → 48.0 dBA · +8.0 dB');
});

test('live card uses the same description as a recorded event', () => {
  const elements = new Map();
  context.document = { getElementById(id) {
    if (id === 'acousticLiveConsole' || id === 'acousticLiveBars') return null;
    if (!elements.has(id)) elements.set(id, { textContent: '' });
    return elements.get(id);
  } };
  context.renderAcousticLiveObservation({
    status: 'dsp_shadow', level: { sound_dba: 43.2 },
    results: { shapes: [{ key: 'impact_like', label: 'คล้ายเสียงกระแทก', confidence: 0.82 }] },
  });
  assert.equal(elements.get('acousticLatestLabel').textContent, 'คล้ายเสียงกระแทก');
  assert.equal(elements.get('acousticLatestLabelMeta').textContent,
    context.acousticClassificationDetail('impact_like', 0.82));
  assert.equal(elements.get('acousticAverage').textContent, '43.2 dBA');
  assert.equal(elements.get('acousticCoverage').textContent, 'สด · ไม่บันทึก');
});
