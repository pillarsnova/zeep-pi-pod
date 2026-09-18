'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname,
  '../../static/partials/app/scripts/12-connection-state.js'), 'utf8');
const input = {
  mode: 'ws', receivedAt: 100000, now: 102000, authenticated: true,
  frame: {sequence: 4, data_age_s: 3, stale: false},
};
function presentation(overrides = {}) {
  const context = vm.createContext({});
  vm.runInContext(source, context);
  return context.connectionPresentation({...input, ...overrides});
}

test('connected transport does not claim all sensors healthy', () => {
  const result = presentation();
  assert.equal(result.tone, 'connected');
  assert.match(result.detail, /5 วินาที/);
  assert.match(result.detail, /ตรวจคุณภาพแยก/);
});
test('socket open without a snapshot waits for the first frame', () => {
  assert.equal(presentation({receivedAt: 0}).tone, 'waiting');
  assert.equal(presentation({frame: null}).tone, 'waiting');
  assert.equal(presentation({frame: {sequence: null}}).tone, 'waiting');
});
test('backend stale frame remains stale even with a fresh websocket message', () => {
  assert.equal(presentation({frame: {...input.frame, stale: true}}).tone, 'stale');
});
test('invalid sensor age never becomes a live value', () => {
  for (const age of [NaN, Infinity, -1, 'bad', '', true]) {
    assert.equal(presentation({frame: {...input.frame, data_age_s: age}}).tone, 'stale');
  }
  assert.equal(presentation({frame: {...input.frame, data_age_s: null}}).tone, 'waiting');
});
test('a reconnect must receive a new snapshot before becoming connected', () => {
  assert.equal(presentation({mode: 'connecting'}).tone, 'waiting');
});
test('malformed sequence and stale flag cannot be live', () => {
  for (const patch of [{sequence: '4'}, {sequence: -1}, {stale: 'false'}, {stale: null}]) {
    assert.equal(presentation({frame: {...input.frame, ...patch}}).tone, 'stale');
  }
});
test('a cached frame can expire even before the transport timeout', () => {
  assert.equal(presentation({frame: {...input.frame, data_age_s: 29, refresh_s: 10}}).tone, 'stale');
});
test('invalid websocket payloads cannot renew the accepted snapshot clock', () => {
  const context = vm.createContext({});
  vm.runInContext(source, context);
  for (const payload of [null, [], {}, {sensor: [], session: {}}, {sensor: {}, session: null}]) {
    assert.equal(context.isLiveStateSnapshot(payload), false);
  }
  assert.equal(context.isLiveStateSnapshot({sensor: {}, session: {}}), true);
});
test('fresh REST updates are labelled as fallback rather than websocket', () => {
  assert.equal(presentation({mode: 'rest'}).tone, 'fallback');
});
test('silent transport ages out independently of backend stale flag', () => {
  assert.equal(presentation({now: 113000}).tone, 'offline');
  assert.equal(presentation({mode: 'rest', now: 113000}).tone, 'offline');
});
test('offline without a cached snapshot does not claim there are old readings', () => {
  const result = presentation({mode: 'offline', receivedAt: 0});
  assert.match(result.detail, /ยังไม่ได้รับข้อมูล/);
});
test('logout hides all telemetry status', () => {
  const result = presentation({authenticated: false});
  assert.equal(result.hidden, true);
  assert.equal(result.detail, '');
});
test('render updates fullscreen-independent component and hides it at session end', () => {
  const nodes = {};
  for (const id of ['connectionState', 'connectionStateTitle', 'connectionStateDetail']) {
    nodes[id] = {textContent: '', dataset: {}};
  }
  const context = vm.createContext({
    document: {body: {dataset: {}}, getElementById: id => nodes[id]},
    lastServerUpdateAt: input.receivedAt, current: {sensor_frame: input.frame},
    currentPrincipal: {role: 'admin'}, sessionEndShown: false,
    Date: {now: () => input.now},
  });
  vm.runInContext(source, context);
  context.renderConnectionState('offline');
  assert.equal(nodes.connectionState.hidden, false);
  assert.equal(context.document.body.dataset.connection, 'offline');
  context.renderConnectionState('ws');
  assert.equal(context.document.body.dataset.connection, 'connected');
  context.sessionEndShown = true;
  context.renderConnectionState();
  assert.equal(nodes.connectionState.hidden, true);
});
