/* Result UI only: synthetic payloads, no score recalculation or Pod access. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const scripts = path.join(__dirname, '../../static/partials/app/scripts');
const fixtures = JSON.parse(fs.readFileSync(
  path.join(__dirname, 'result-fixtures.json'), 'utf8',
));

function runtime(principal = {role: 'user'}) {
  const context = vm.createContext({
    localStorage: {getItem: () => null}, currentPrincipal: principal,
  });
  for (const filename of [
    '00-product-copy-alerts.js', '11-result-summary.js',
    '11-history-list.js', '12-history-report.js',
  ]) {
    vm.runInContext(fs.readFileSync(path.join(scripts, filename), 'utf8'), context);
  }
  return context;
}

function fixture(name = 'nap') {
  return structuredClone(fixtures[name]);
}

function render(context, payload, ended = true) {
  return context.renderRestoreSummary(
    payload, context.reportPresentationMode(payload), ended,
  );
}

test('two modes retain their existing score and exactly one primary score', () => {
  const context = runtime();
  for (const [name, title] of [['nap', 'Recovery Score'], ['sleep', 'Sleep Score']]) {
    const payload = fixture(name);
    const before = structuredClone(payload);
    const html = render(context, payload);
    assert.match(html, new RegExp(`<strong>${payload.sleep_quality.score}</strong>`));
    assert.match(html, new RegExp(title));
    assert.equal((html.match(/class="sleep-quality-value"/g) || []).length, 1);
    assert.doesNotMatch(html, /Restore Score/);
    assert.deepEqual(payload, before, 'rendering must not mutate saved results');
  }
});

test('zero is a released score and zero component is a measured value', () => {
  const context = runtime();
  const payload = fixture();
  payload.sleep_quality.score = 0;
  payload.sleep_quality.level_key = 'low';
  payload.restore_summary.status.key = 'rest_more';
  payload.sleep_quality.component_points.goal_duration = 0;
  const html = render(context, payload);
  assert.match(html, /<strong>0<\/strong>/);
  assert.doesNotMatch(html, /ครั้งนี้ยังไม่มีคะแนน/);
  assert.match(html, /<meter[^>]*value="0"/);
});

test('invalid scores are unavailable rather than clamped or coerced', () => {
  const context = runtime();
  for (const value of [null, undefined, '', ' ', false, true, [], [90], {}, NaN, Infinity, -1, 101]) {
    const payload = fixture();
    payload.sleep_quality.score = value;
    const html = render(context, payload);
    assert.match(html, /<strong>—<\/strong>/, `value ${String(value)}`);
    assert.match(html, /ครั้งนี้ยังไม่มีคะแนน/);
    assert.doesNotMatch(html, /result-emotion positive|<meter/);
  }
});

test('legacy nonblank numeric score string is displayed without recalculation', () => {
  const context = runtime();
  const payload = fixture();
  payload.sleep_quality.score = '76.5';
  assert.match(render(context, payload), /<strong>76.5<\/strong>/);
});

test('ongoing session never receives a released score or positive face', () => {
  const context = runtime();
  const html = render(context, fixture(), false);
  assert.match(html, /กำลังบันทึกการพัก/);
  assert.match(html, /<strong>—<\/strong>/);
  assert.doesNotMatch(html, /result-emotion positive|<meter/);
});

test('explicit unavailable result suppresses charts even if an old score remains', () => {
  const context = runtime();
  const payload = fixture();
  payload.sleep_quality.available = false;
  const html = render(context, payload);
  assert.match(html, /ครั้งนี้ยังไม่มีคะแนน/);
  assert.doesNotMatch(html, /result-emotion positive|<meter/);
});

test('unknown mode stays neutral and does not borrow an Overnight interpretation', () => {
  const context = runtime();
  const payload = fixture();
  payload.rest_mode = 'unknown';
  const html = render(context, payload);
  assert.match(html, /mode-unknown/);
  assert.match(html, /ข้อมูลที่บันทึกได้ในครั้งนี้/);
  assert.doesNotMatch(html, /ภาพรวมจากการนอนครั้งนี้|result-emotion positive|<meter/);
});

test('canonical Nap mode wins over stale Sleep labels in a historical quality object', () => {
  const context = runtime();
  const payload = fixture('sleep');
  payload.mode = {key: 'nap_recovery', group: 'nap_recovery', requested: 'auto'};
  payload.sleep_quality.rest_mode = 'sleep';
  assert.equal(context.reportPresentationMode(payload), 'recovery');
  const html = render(context, payload);
  assert.match(html, /Recovery Score/);
  assert.doesNotMatch(html, /Sleep Score|<span>หลับต่อเนื่อง<\/span>/);
});

test('unmeasured feedback cannot display stale or sensor-inferred improvement', () => {
  const context = runtime();
  const payload = fixture();
  payload.restore_summary.subjective_outcome = {
    status: 'not_measured', freshness_delta: 2, activity_readiness: 8,
  };
  const html = render(context, payload);
  assert.doesNotMatch(html, /restore-subjective-outcome|สดชื่นขึ้น 2|ความพร้อมทำกิจกรรม 8/);
});

test('measured zero feedback is retained and explicitly identified as self-report', () => {
  const context = runtime();
  const payload = fixture();
  payload.restore_summary.subjective_outcome = {
    status: 'measured', freshness_delta: 0, activity_readiness: 0,
    source: 'pre_post_questionnaire', sensor_inferred: false,
  };
  const html = render(context, payload);
  assert.match(html, /ความสดชื่นใกล้เคียงก่อนพัก/);
  assert.match(html, /ความพร้อมทำกิจกรรม 0\/10/);
  assert.match(html, /จากแบบประเมินของผู้ใช้ · ไม่ได้อนุมานจาก Sensor/);
});

test('measured positive and negative freshness keep their direction', () => {
  const context = runtime();
  const payload = fixture('sleep');
  assert.match(render(context, payload), /สดชื่นขึ้น 2 ระดับ/);
  payload.restore_summary.subjective_outcome.freshness_delta = -2;
  assert.match(render(context, payload), /ความสดชื่นลดลง 2 ระดับ/);
});

test('malformed or out-of-range feedback never becomes a fabricated zero', () => {
  const context = runtime();
  for (const value of [null, undefined, '', ' ', false, true, [], ['2'], {}, NaN, Infinity, -11, 11]) {
    const payload = fixture();
    payload.restore_summary.subjective_outcome = {
      status: 'measured', freshness_delta: value, activity_readiness: value,
    };
    assert.doesNotMatch(render(context, payload), /restore-subjective-outcome/, String(value));
  }
});

test('component bars use payload maxima rather than frontend formula weights', () => {
  const context = runtime();
  const payload = fixture();
  payload.sleep_quality.component_points.goal_duration = 4;
  payload.sleep_quality.component_max_points.goal_duration = 8;
  const row = context.resultComponentRows(payload.sleep_quality, 'recovery')
    .find(item => item.key === 'goal_duration');
  assert.equal(row.earned, 4);
  assert.equal(row.maximum, 8);
  assert.equal(row.percent, 50);
  assert.match(render(context, payload), /max="8" value="4"/);
});

test('imputed physiology is never shown as a measured recovery bar', () => {
  const context = runtime();
  const payload = fixture();
  payload.sleep_quality.imputed_component_points = {physiological_response: 20};
  const rows = context.resultComponentRows(payload.sleep_quality, 'recovery');
  assert.equal(rows.some(item => item.key === 'physiological_response'), false);
  assert.equal(rows.some(item => item.key === 'goal_duration'), true);
});

test('component rows reject unknown/prototype keys, missing values and invalid maxima', () => {
  const context = runtime();
  const quality = {
    component_order: ['__proto__', 'constructor', 'unknown', 'goal_duration', 'goal_duration'],
    component_points: {goal_duration: null}, component_max_points: {goal_duration: 25},
  };
  assert.equal(context.resultComponentRows(quality, 'recovery').length, 0);
  quality.component_points.goal_duration = 5;
  for (const maximum of [null, 0, -1, false, '', Infinity]) {
    quality.component_max_points.goal_duration = maximum;
    assert.equal(context.resultComponentRows(quality, 'recovery').length, 0);
  }
  quality.component_max_points.goal_duration = 25;
  assert.equal(context.resultComponentRows(quality, 'recovery').length, 1);
});

test('safety review precedes a high score and cannot become a celebratory face', () => {
  const context = runtime();
  const payload = fixture('sleep');
  payload.sleep_quality.safety_review_required = true;
  const html = render(context, payload);
  assert.match(html, /<strong>90<\/strong>/);
  assert.match(html, /result-emotion attention/);
  assert.doesNotMatch(html, /result-emotion positive/);
  assert.ok(html.indexOf('class="result-safety-review"') < html.indexOf('class="result-app-overview"'));
});

test('safety review remains visible when no score can be shown', () => {
  const context = runtime();
  const payload = fixture();
  payload.sleep_quality.available = false;
  payload.sleep_quality.safety_review_required = true;
  const html = render(context, payload);
  assert.match(html, /class="result-safety-review"/);
  assert.match(html, /result-emotion attention/);
  assert.doesNotMatch(html, /คะแนนยังแสดงได้/);
});

test('limited-evidence neutral score cannot get a positive recovery face', () => {
  const context = runtime();
  const payload = fixture();
  payload.sleep_quality.limited_evidence_neutral_score = true;
  const html = render(context, payload);
  assert.match(html, /result-emotion neutral/);
  assert.match(html, /ข้อมูลประกอบมีจำกัด/);
  assert.doesNotMatch(html, /result-emotion positive/);
});

test('untrusted copy is escaped and component labels come from an allowlist', () => {
  const context = runtime({role: 'admin'});
  const payload = fixture();
  const attack = '<img src=x onerror="globalThis.pwned=true">';
  payload.restore_summary.status = {key: 'rest_good', label: attack, meaning: attack};
  payload.restore_summary.recommendation = {primary: attack};
  payload.restore_summary.session_scope = {label: attack};
  payload.restore_summary.drivers = {
    positive: [{key: 'rest_continuity', message: attack}], attention: [],
  };
  payload.sleep_quality.component_labels = {goal_duration: attack};
  const html = render(context, payload);
  assert.doesNotMatch(html, /<img|<script|<svg[^>]*onload=/i);
  assert.match(html, /&lt;img/);
  assert.equal(context.pwned, undefined);
});

test('Session End renders user copy after principal is cleared', () => {
  const context = runtime(null);
  const payload = fixture();
  const html = render(context, payload);
  assert.match(html, /Recovery Score/);
  assert.match(html, /ผล Wellness เฉพาะการพักครั้งนี้/);
  assert.doesNotMatch(html, /result-evidence-details|Confidence H \/ M \/ L/);
});

test('missing baseline and trends do not generate a fictional history chart', () => {
  const context = runtime();
  const payload = fixture();
  delete payload.restore_summary.personal_baseline;
  delete payload.restore_summary.trend;
  const html = render(context, payload);
  assert.match(html, /กำลังเรียนรู้รูปแบบของคุณ/);
  assert.doesNotMatch(html, /จากการพัก \d+ ครั้ง|<canvas|<polyline/);
});

test('canonical next-session recommendation appears once', () => {
  const context = runtime();
  const payload = fixture();
  const advice = payload.restore_summary.recommendation.primary;
  const html = render(context, payload);
  assert.equal(html.split(advice).length - 1, 1);
});
