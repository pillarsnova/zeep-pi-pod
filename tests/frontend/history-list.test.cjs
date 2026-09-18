/* Synthetic DOM/fetch checks for the Sessions list; no Pod or user data. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(
  __dirname, '../../static/partials/app/scripts/11-history-list.js',
), 'utf8');

function element() {
  return {
    innerHTML: '', attributes: {}, children: [],
    setAttribute(name, value) { this.attributes[name] = value; },
    appendChild(child) { this.children.push(child); },
    querySelector() { return this.retry ||= element(); },
  };
}

function fixture(fetch) {
  const elements = new Map();
  const timers = new Map();
  const rendered = [];
  const notices = [];
  let nextTimer = 0;
  const context = vm.createContext({
    AbortController, fetch, console, URLSearchParams,
    currentPrincipal: {role: 'user', account_key: 'synthetic-user'},
    document: {
      getElementById(id) {
        if (!elements.has(id)) elements.set(id, element());
        return elements.get(id);
      },
      createElement: element,
    },
    setTimeout(callback) { timers.set(++nextTimer, callback); return nextTimer; },
    clearTimeout(id) { timers.delete(id); },
    toast(message) { notices.push(message); },
    withBusy(_button, action) { return action(); },
  });
  vm.runInContext(source, context);
  context.ensureHistoryFilterDefaults = () => {};
  context.historyFilterParams = () => 'date=2026-09-19';
  context.refreshUserJourney = () => {};
  context.renderSessionList = (data) => {
    rendered.push(data);
    elements.get('sessionList').innerHTML = 'loaded';
    elements.get('historySummary').innerHTML = 'summary';
  };
  return {context, elements, timers, rendered, notices};
}

function response(data = {sessions: []}) {
  return {ok: true, status: 200, json: async () => data};
}

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return {promise, resolve, reject};
}

function assertErrorState(app) {
  const list = app.elements.get('sessionList');
  const summary = app.elements.get('historySummary');
  assert.match(list.innerHTML, /ยังโหลดประวัติ/);
  assert.match(list.innerHTML, /ลองอีกครั้ง/);
  assert.doesNotMatch(list.innerHTML, /loading/);
  assert.doesNotMatch(summary.innerHTML, /กำลังสรุป/);
  assert.equal(list.attributes['aria-busy'], 'false');
  assert.equal(summary.attributes['aria-busy'], 'false');
  assert.equal(app.timers.size, 0);
}

test('network error settles list/summary and offers an operational retry', async () => {
  const app = fixture(async () => { throw new Error('offline'); });
  assert.equal(await app.context.refreshHistory(), null);
  assertErrorState(app);
  app.context.fetch = async () => response();
  await app.elements.get('sessionList').querySelector('button').onclick();
  assert.equal(app.rendered.length, 1);
});

test('HTTP failure never injects backend detail into the page or toast', async () => {
  const app = fixture(async () => ({
    ok: false, status: 500,
    json: async () => ({detail: '<img src=x onerror=alert(1)> secret'}),
  }));
  app.context.currentPrincipal.role = 'admin';
  await app.context.refreshHistory();
  assertErrorState(app);
  assert.doesNotMatch(app.notices.join(' '), /<img|secret/);
});

test('invalid JSON settles loading state without an unhandled rejection', async () => {
  const app = fixture(async () => ({
    ok: true, status: 200,
    json: async () => { throw new SyntaxError('Unexpected token'); },
  }));
  await app.context.refreshHistory();
  assertErrorState(app);
});

for (const data of [null, {}, {sessions: null}]) {
  test(`invalid list contract ${JSON.stringify(data)} offers retry`, async () => {
    const app = fixture(async () => response(data));
    await app.context.refreshHistory();
    assertErrorState(app);
    assert.equal(app.rendered.length, 0);
  });
}

test('successful empty list is data, not a connection error', async () => {
  const app = fixture(async () => response());
  await app.context.refreshHistory();
  assert.equal(app.rendered.length, 1);
  assert.equal(app.elements.get('sessionList').attributes['aria-busy'], 'false');
  assert.equal(app.notices.length, 0);
  assert.equal(app.timers.size, 0);
});

test('older request failure cannot overwrite a newer successful result', async () => {
  const old = deferred();
  const app = fixture(() => old.promise);
  const first = app.context.refreshHistory();
  app.context.fetch = async () => response();
  await app.context.refreshHistory();
  old.reject(new Error('old offline request'));
  await first;
  assert.equal(app.elements.get('sessionList').innerHTML, 'loaded');
  assert.equal(app.notices.length, 0);
});

test('old completion cannot clear busy state or error for a newer request', async () => {
  const old = deferred();
  const newer = deferred();
  const app = fixture(() => old.promise);
  const first = app.context.refreshHistory();
  app.context.fetch = () => newer.promise;
  const second = app.context.refreshHistory();
  old.resolve(response());
  await first;
  assert.equal(app.elements.get('sessionList').attributes['aria-busy'], 'true');
  newer.reject(new Error('new failure'));
  await second;
  assertErrorState(app);
  assert.equal(app.rendered.length, 0);
});

test('late body parse cannot replace a newer list', async () => {
  const body = deferred();
  const app = fixture(async () => ({ok: true, json: () => body.promise}));
  const first = app.context.refreshHistory();
  await Promise.resolve();
  app.context.fetch = async () => response();
  await app.context.refreshHistory();
  body.resolve({sessions: [{session_id: 'obsolete'}]});
  await first;
  assert.equal(app.rendered.length, 1);
  assert.equal(app.elements.get('sessionList').innerHTML, 'loaded');
});

test('request timeout aborts fetch and ends loading with retry', async () => {
  const app = fixture((_url, options) => new Promise((_resolve, reject) => {
    options.signal.addEventListener('abort', () => reject(new Error('aborted')));
  }));
  const loading = app.context.refreshHistory();
  assert.equal(app.elements.get('sessionList').attributes['aria-busy'], 'true');
  assert.equal(app.timers.size, 1);
  [...app.timers.values()][0]();
  await loading;
  assertErrorState(app);
});
