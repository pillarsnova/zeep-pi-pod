/* Copy reflects acknowledged commands, never unverified physical feedback. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

function runtime(role = 'user') {
  const nodes = new Map();
  for (const id of [
    'airconComfortMap', 'airconComfortCaption', 'podRoomLightMap',
    'podSceneCaption', 'unifiedAudioModeToggle', 'unifiedAudioModeLabel',
    'unifiedAudioModeIcon', 'loopChk',
  ]) {
    nodes.set(id, {
      dataset: {}, attributes: {}, textContent: '',
      classList: {toggle() {}},
      setAttribute(name, value) { this.attributes[name] = value; },
    });
  }
  const context = vm.createContext({
    document: {getElementById: id => nodes.get(id)},
    currentPrincipal: {role},
    AIRCON_DESIRED_TEMPERATURE_MIN_C: 15,
    AIRCON_DESIRED_TEMPERATURE_MAX_C: 28,
    unifiedAudioMode: 'repeat_one',
    setUiIconReference() {},
  });
  const source = path.join(
    __dirname, '../../static/partials/app/scripts/04-unified-controls.js',
  );
  vm.runInContext(fs.readFileSync(source, 'utf8'), context);
  return {context, nodes};
}

test('air conditioning copy reports command intent, not confirmed cooling', () => {
  for (const role of ['user', 'admin']) {
    const {context, nodes} = runtime(role);
    context.syncUnifiedAirconComfort(true, true, 18, 23.4);
    assert.equal(nodes.get('airconComfortCaption').textContent, '18°C · คำสั่งเปิดแอร์');
    const label = nodes.get('airconComfortMap').attributes['aria-label'];
    assert.match(label, /ไม่ใช่การยืนยันจากตัวแอร์/);
    assert.doesNotMatch(label, /กำลังทำความเย็น|อุณหภูมิแอร์/);
    if (role === 'admin') assert.match(label, /อุณหภูมิภายในตู้ 23.4°C/);
    context.syncUnifiedAirconComfort(false, true, 18, 23.4);
    assert.equal(nodes.get('airconComfortCaption').textContent, 'คำสั่งล่าสุด · ปิดแอร์');
  }
});

test('unknown and offline command states are not presented as powered off', () => {
  const {context, nodes} = runtime();
  for (const value of [null, undefined]) {
    context.syncUnifiedAirconComfort(value, true, 18, null);
    assert.equal(nodes.get('airconComfortCaption').textContent, 'ยังไม่ทราบคำสั่งล่าสุด');
    assert.equal(nodes.get('podRoomLightMap').dataset.aircon, 'unknown');
    assert.doesNotMatch(nodes.get('podRoomLightMap').attributes['aria-label'], /เครื่องปรับอากาศคำสั่งปิด/);
  }
  context.syncUnifiedAirconComfort(true, false, 18, null);
  assert.equal(nodes.get('airconComfortCaption').textContent, 'กำลังเชื่อมต่อแอร์');
  assert.equal(nodes.get('podRoomLightMap').dataset.aircon, 'offline');
});

test('audio labels retain repeat/queue enums and accessible toggle states', () => {
  const {context, nodes} = runtime();
  for (const [mode, caption, next] of [
    ['repeat_one', 'เล่นซ้ำ', 'เล่นตามคิว'],
    ['queue', 'เล่นตามคิว', 'เล่นซ้ำ'],
  ]) {
    context.unifiedAudioMode = mode;
    context.renderUnifiedAudioModeControls();
    const toggle = nodes.get('unifiedAudioModeToggle');
    assert.equal(toggle.dataset.mode, mode);
    assert.equal(toggle.title, caption);
    assert.equal(toggle.attributes['aria-label'], `${caption}อยู่ กดเพื่อ${next}`);
    assert.equal(toggle.attributes['aria-pressed'], String(mode === 'repeat_one'));
    assert.equal(nodes.get('loopChk').checked, mode === 'repeat_one');
  }
});
