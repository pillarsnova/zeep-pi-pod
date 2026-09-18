# ZEEP UI build-time partials

โฟลเดอร์นี้แยก source ของหน้าเว็บหลักออกจาก
`static/index.template.html` เพื่อให้ค้นหา รีวิว และแก้ไขได้ง่ายขึ้น โดย
`ui_composer.py` จะประกอบทุกส่วนกลับเป็น `static/index.html` ไฟล์เดียวก่อนใช้งาน

## กติกาสำคัญ

- แก้ source ในโฟลเดอร์นี้หรือ `index.template.html` และห้ามแก้
  `index.html` เพียงไฟล์เดียว เพราะไฟล์นั้นเป็น generated runtime bundle
- ไฟล์ JavaScript เหล่านี้เป็น **ordered classic-script fragments** ไม่ใช่ ES
  modules และไม่ควรเพิ่ม `<script src>` แยกในเบราว์เซอร์
- ลำดับใน `ui_composer.SCRIPT_PARTIALS` เป็น contract เพราะโค้ดเดิมใช้ global
  functions, shared state และ inline event handlers ร่วมกัน
- `styles.css` ต้องถูกประกอบก่อน `theme-modern.css` เพื่อรักษาลำดับ CSS cascade
- ทุก partial ต้องลงท้ายด้วย newline และทุก marker ต้องมีเพียงหนึ่งตำแหน่ง

## แผนผังไฟล์

| Source | หน้าที่หลัก |
| --- | --- |
| `shell.html` | Header, identity, navigation, fullscreen, page heading และสถานะข้อมูลร่วม |
| `styles.css` | Base layout และ component styles ก่อน theme overrides |
| `scripts/00-product-copy-alerts.js` | Product copy, icon helpers และ alert presentation |
| `scripts/01-runtime-safety.js` | Runtime state, safety, profile และ sleep presentation |
| `scripts/02-device-controls.js` | Track metadata, outputs และ control-center helpers |
| `scripts/03-dashboard.js` | Dashboard metrics และ atmosphere presentation |
| `scripts/04-unified-controls.js` | Unified Control Deck ทั้งหกส่วน |
| `scripts/05-hardware-actions.js` | Light, aroma, door, bed และ hardware actions |
| `scripts/06-client-api.js` | Browser auth token, API helpers และ debug commands |
| `scripts/07-debug-brainwave.js` | Brainwave lab, door/audio commands และ track loading |
| `scripts/08-sensors-monitor.js` | Sensor, BCG, calibration และ packet inspector |
| `scripts/09-auth-login.js` | User identity, login, logout และ history-user loading |
| `scripts/10-session-end-report.js` | End-of-session report, PNG/QR และ auth bootstrap |
| `scripts/11-result-summary.js` | Shared result presenter: score, emotion, component bars, drivers และ next step; ใช้ร่วมใน History/Session End |
| `scripts/11-history-list.js` | Usage history list และ Restore Summary helpers |
| `scripts/12-history-report.js` | Detailed Overnight/Nap report rendering |
| `scripts/12-connection-state.js` | Pure connection/freshness presenter และ shared status renderer |
| `scripts/13-runtime-websocket.js` | Audio visualizer, WebSocket rendering และ app bootstrap |

## ขั้นตอนแก้ไขและตรวจสอบ

```bash
python ui_composer.py build
python ui_composer.py check
python -m unittest -q test_ui_composer
node --test tests/frontend/*.test.cjs
python tests/frontend/preview_results.py
```

คำสั่ง preview แสดงเฉพาะข้อมูลจำลองจาก `tests/frontend/result-fixtures.json`
บน localhost ไม่เชื่อมต่อ Pod และไม่สร้าง Session จริง ใช้ตรวจ Nap/Overnight
ที่ขนาดมือถือและจอใหญ่ CSS ของ component นี้อยู่ใน
`static/styles/result-summary.css` และต้องไม่ย้ายสูตรคะแนนมาคำนวณใน browser

`build` เขียน bundle แบบ atomic และ `check` จะหยุดงานหาก source กับ
`static/index.html` ไม่ตรงกัน

HTML partials เพิ่มผ่าน `ui_composer.HTML_PARTIALS`; CSS component ที่แยกใหม่
ต้อง scope ด้วย class ของตัวเอง ไม่เพิ่ม override ต่อท้าย theme โดยไม่มี owner
อ่าน [Interface development roadmap](../../../docs/zeep-interface-development-roadmap.md)
ก่อนย้าย feature ระหว่างชั้น โครงสร้างเป้าหมายยังไม่ใช่การย้ายเสร็จทั้งระบบ
