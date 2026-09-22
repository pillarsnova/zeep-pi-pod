const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname,
  '../../static/partials/app/scripts/01-runtime-safety.js'), 'utf8');
const context = vm.createContext({
  location: {host: 'test.local'}, localStorage: {getItem: () => null},
  applyPageView() {},
});
vm.runInContext(source, context);

test('BMI is described as grouping context, not a Sleep State correction', () => {
  const session = {health_reference: {baseline_context: {
    bmi: {status: 'available', value: 22.86},
  }}};
  assert.equal(context.baselineBmiLabel(session),
    'BMI 22.86 · ใช้แบ่งกลุ่มเปรียบเทียบ ยังไม่ปรับสถานะการนอน');
});

test('missing, invalid and non-adult BMI does not become zero or a normal range', () => {
  for (const bmi of [null, {status: 'adult_reference_not_applicable', value: 22},
    ...[null, '', '22', NaN, Infinity].map(value => ({status: 'available', value}))]) {
    assert.equal(context.baselineBmiLabel({health_reference: {baseline_context: {bmi}}}),
      'BMI ยังไม่มีข้อมูลอ้างอิง');
  }
});
