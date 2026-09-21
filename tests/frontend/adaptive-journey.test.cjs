/* Synthetic owner-switch and recommendation checks. No real device calls. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname,
  '../../static/partials/app/scripts/08-adaptive-journey.js'), 'utf8');

function fixture(fetch) {
  const rendered = [], sent = [], navigated = [], elements = new Map();
  const context = vm.createContext({
    fetch, currentPrincipal: {subject: 'owner', account_key: 'owner'},
    current: {session: {session_id: 's1'}},
    authenticatedHeaders: () => ({}), toast() {}, setInterval() {},
    crypto: {randomUUID: () => 'synthetic-uuid'},
    window: {location: {assign: url => navigated.push(url)}},
    document: {body: {dataset: {view: 'monitor'}}, getElementById(id) {
      if (!elements.has(id)) elements.set(id, {textContent: ''});
      return elements.get(id);
    }},
    async post(url, body) {sent.push({url, body}); return {data: {saved: true}};},
  });
  vm.runInContext(source, context);
  context.renderJourney = data => rendered.push(data);
  return {context, rendered, sent, navigated, elements};
}

test('late response after logout cannot reveal the previous account', async () => {
  let resolve;
  const app = fixture(() => new Promise(yes => {resolve = yes}));
  const pending = app.context.refreshJourney();
  app.context.currentPrincipal = null;
  app.context.resetJourneyContext();
  resolve({ok: true, json: async () => ({data: {private: true}})});
  await pending;
  assert.deepEqual(app.rendered, [null]);
});

test('empty session never fetches another account or previous session', async () => {
  let count = 0;
  const app = fixture(async () => {count += 1});
  app.context.current.session = null;
  await app.context.refreshJourney();
  assert.equal(count, 0);
  assert.deepEqual(app.rendered, [null]);
});

test('accept records a decision then opens manual Control, not an actuator API', async () => {
  const app = fixture(async () => ({ok: true, json: async () => ({data: {
    recommendation: {item: {id: 'advice-1'}},
  }})}));
  await app.context.refreshJourney();
  const button = {disabled: false};
  await app.context.decideJourney('accept', button);
  assert.equal(app.sent.length, 1);
  assert.equal(app.sent[0].url, '/api/v1/adaptive/sessions/s1/decisions');
  assert.equal(app.sent[0].body.decision, 'accept');
  assert.deepEqual(app.navigated, ['/control']);
  assert.equal(button.disabled, false);
});
