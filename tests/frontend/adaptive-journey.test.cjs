/* Synthetic owner-switch and recommendation checks. No real device calls. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname,
  '../../static/partials/app/scripts/08-adaptive-journey.js'), 'utf8');

function node() {
  let text = '';
  return {
    children: [], hidden: false, disabled: false, value: '',
    get textContent() {return text + this.children.map(child => child.textContent).join('');},
    set textContent(value) {text = value; this.children = [];},
    append(...children) {this.children.push(...children);},
    replaceChildren(...children) {text = ''; this.children = children;},
  };
}

function fixture(fetch, realRender = false) {
  const rendered = [], sent = [], navigated = [], elements = new Map();
  const context = vm.createContext({
    fetch, currentPrincipal: {subject: 'owner', account_key: 'owner'},
    current: {session: {session_id: 's1'}},
    authenticatedHeaders: () => ({}), toast() {}, setInterval() {},
    crypto: {randomUUID: () => 'synthetic-uuid'},
    window: {location: {assign: url => navigated.push(url)}},
    document: {body: {dataset: {view: 'monitor'}}, createElement: () => node(), getElementById(id) {
      if (!elements.has(id)) elements.set(id, node());
      return elements.get(id);
    }},
    async post(url, body) {sent.push({url, body}); return {data: {saved: true}};},
  });
  vm.runInContext(source, context);
  if (!realRender) context.renderJourney = data => rendered.push(data);
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

function journeyPayload() {
  return {
    journey: {samples_used: 90, channels: [{key:'temperature',label:'อุณหภูมิ',unit:'°C',available:true}], events:[]},
    comfort_reference: {message:'จากการพักที่คุณระบุว่าสบาย 3 ครั้ง', ranges:{temperature:{low:22,high:24,sessions:3}}},
    recommendation: {item:{id:'r1',title:'แนะนำให้ลดอุณหภูมิ',reason:'เปรียบเทียบกับช่วงอ้างอิง',confirmation_label:'ไปหน้าควบคุม'}},
    outcomes: [],
  };
}

test('shared renderer separates reference, advice and staff notes by role', () => {
  const app = fixture(async () => {}, true);
  app.context.currentPrincipal.role = 'user';
  app.context.document.body.dataset.view = 'sessions';
  app.context.renderJourney(journeyPayload());
  assert.equal(app.elements.get('journeyStaffNote').hidden, true);
  assert.match(app.elements.get('journeyFeedbackHelp').textContent, /ท้ายของการพัก/);
  assert.doesNotMatch(app.elements.get('journeyStatus').textContent, /90|เซนเซอร์/);
  assert.match(app.elements.get('journeyRanges').textContent, /22–24 °C/);
  assert.equal(app.elements.get('journeyCoach').children.length, 2);
  assert.equal(app.elements.get('journeyDecisions').children[0].className, 'btn primary');
  assert.equal(app.elements.get('journeyAdvicePanel').hidden, false);
  app.context.renderJourney({...journeyPayload(), recommendation: {item: null}});
  assert.equal(app.elements.get('journeyAdvicePanel').hidden, true);
  app.context.currentPrincipal.role = 'admin';
  app.context.renderJourney(journeyPayload());
  assert.equal(app.elements.get('journeyStaffNote').hidden, false);
  assert.match(app.elements.get('journeyStatus').textContent, /90/);
});

test('empty context clears old ranges and disables feedback until data exists', () => {
  const app = fixture(async () => {}, true);
  app.context.renderJourney(journeyPayload());
  app.elements.get('journeyFeedback').value = 'comfortable';
  app.context.resetJourneyContext();
  assert.equal(app.elements.get('journeyRanges').children.length, 0);
  assert.equal(app.elements.get('journeyFeedback').value, '');
  assert.equal(app.elements.get('journeySave').disabled, true);
  assert.equal(app.elements.get('journeyFeedback').disabled, true);
});

test('evidence copy is inserted as text, never interpreted as markup', () => {
  const app = fixture(async () => {}, true), data = journeyPayload();
  const hostile = '<img src=x onerror=alert(1)>';
  data.recommendation.item.title = hostile;
  app.context.renderJourney(data);
  assert.equal(app.elements.get('journeyCoach').children[0].textContent, hostile);
  assert.equal(app.elements.get('journeyCoach').children[0].innerHTML, undefined);
});
