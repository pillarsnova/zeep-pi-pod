# ZEEP Interface — Development Roadmap

สถานะ: **Internal Pilot · แยกสิ่งที่ทำแล้วจาก ROADMAP**  
ทบทวน: 19 กันยายน 2026 · Owner: Product / Frontend / Pi Backend

## สรุปสำหรับทีม

คง Javis โทนมืด แต่ลดแสงเรืองและกรอบซ้อน ใช้พื้นที่กับข้อมูลสำคัญและ
ภาพจากข้อมูลจริง ไม่เพิ่มกราฟเคลื่อนไหวที่ดูเหมือน Sensor ทั้งที่เป็นภาพตกแต่ง
เริ่มจากความน่าเชื่อถือของสถานะข้อมูล ก่อนปรับการเล่าเรื่องในแต่ละหน้า
ยังไม่เปลี่ยน framework, สูตรคะแนน, Sleep State, Raw หรือผลย้อนหลัง

## สิ่งที่ทำในรอบนี้

- แยก Header, identity, navigation, fullscreen และ page heading เป็น
  [`app/shell.html`](../static/partials/app/shell.html) ประกอบตอน build
- เพิ่ม component สถานะการเชื่อมต่อทุกหน้าหลักและ Focus/Fullscreen:
  รอข้อมูล / เชื่อมต่อ / ช่องทางสำรอง / ค่าล่าสุด / ขาดการเชื่อมต่อ
- เวลา WebSocket เปิดสำเร็จยังไม่แสดงว่าข้อมูลใหม่มาแล้ว ต้องรับ snapshot
  ที่มีโครงสร้างถูกต้องและ render สำเร็จก่อนปรับเวลาที่รับข้อมูล
- คุณภาพของ Sensor ยังเป็นรายอุปกรณ์ การเชื่อมต่อได้ไม่เท่ากับทุก Sensor พร้อม
  ข้อมูลหลัง restart ที่ backend ระบุ stale ต้องแสดงว่าเป็นค่าล่าสุด
- Sessions: network/HTTP/JSON/ข้อมูลผิดรูปแบบ/timeout ต้องจบสถานะโหลด
  มีปุ่มลองใหม่ และคำตอบเก่าห้ามทับตัวกรองใหม่
- เพิ่ม Node built-in behavioral tests บนเครื่องพัฒนา/CI เท่านั้น ไม่มี Node,
  npm dependency หรือ runtime ใหม่ที่ต้องเพิ่มใน Pi

## ทุกหน้ามีหน้าที่ชัดเจน

| หน้า | คำถามที่ต้องตอบ | รูปแบบแสดงผลที่เสนอ — ROADMAP |
| --- | --- | --- |
| `/login` | เริ่มพักอย่างไร | 3 ขั้น: เข้าบัญชี → เลือกรูปแบบ → พร้อมพัก; คำแนะนำย่อ ขยายได้ |
| `/login/qr` | เชื่อมโทรศัพท์อย่างไร | QR เด่น อายุ QR และสถานะเชื่อมต่อชัด; ไม่แสดงข้อมูลผู้ใช้ก่อนยืนยัน |
| `/admin/login` | ทีมเข้าใช้งานอย่างไร | ฟอร์มกระชับ แยกจากผู้พัก ข้อผิดพลาดสุภาพแต่ไม่เผยรายละเอียดบัญชี |
| `/dashboard` | ตอนนี้พักเป็นอย่างไร | สถานะพักหนึ่งจุด, HR/RR คู่กัน, บรรยากาศ, คำแนะนำสำคัญหนึ่งข้อ; แตะเปิดแนวโน้มและช่วงประจำ |
| `/control` | สั่งอะไรไปแล้ว อุปกรณ์ตอบหรือยัง | 6 การ์ด 2 คอลัมน์ × 3 แถว; สั่ง / กำลังส่ง / ACK / feedback จริงแยกกัน; เป้าสัมผัส ≥44px |
| `/monitor` | ทีมควรดูแลอะไรตอนนี้ | Version & Provenance บนสุด → System Health → ผู้ใช้/Reference → สิ่งแวดล้อม → Smart Ear; diagnostics พับ |
| `/sessions` | คนนี้เคยมาพักอย่างไร ได้ผลอะไร | รายชื่ออีเมล A–Z ขนาดย่อ → วันที่/โหมด → สรุป → รายการ → รายละเอียด; แนวโน้มแยก Sleep/Recovery |
| `/control-debug` | คำสั่งติดตรงไหน | Request/ACK/feedback timeline, เวลาและเหตุปฏิเสธ; Admin เท่านั้น ไม่ทำภาพตกแต่งเหมือนการยืนยันอุปกรณ์ |

`/` เป็น redirect และ `/admin` เป็น alias ของ Control ไม่ใช่ feature page เพิ่ม
รายการ route/สิทธิ์อ้างอิง [Interface Map](zeep-interface-map-and-ui-standard-v1.md)
และ [`api/shell_routes.py`](../api/shell_routes.py)

## แนวทางที่ทำให้ดูล้ำสมัยโดยยังอ่านง่าย

1. **หนึ่งข้อเท็จจริง หนึ่งเจ้าของ:** live cards แสดงค่าปัจจุบัน; insight แสดง
   ความหมาย/สิ่งที่ต่างจากช่วงประจำ; reference แสดงเกณฑ์; diagnostics แสดงหลักฐาน
   ไม่คัดค่าชุดเดิมมาใส่ซ้ำทุกการ์ด
2. **ข้อมูลจริงเคลื่อนไหว:** sparkline ต้องมีช่วงเวลา หน่วย และช่องข้อมูลขาด
   ห้ามต่อเส้นผ่านช่องว่างโดยไม่บอก; Smart Ear ใช้ marker ตามเหตุการณ์ที่รับจริง
3. **เปรียบเทียบอย่างตรงเรื่อง:** คืนค้างคืนใช้ Sleep Score; Nap & Refresh ใช้
   Recovery Score ตาม API ปัจจุบัน ไม่เฉลี่ยสองคะแนนรวมเป็น trend เดียว
4. **เป็นมิตร:** สรุปสุขภาพสั้นหนึ่งประโยค + สิ่งที่ทำได้หนึ่งข้อ; technical copy
   และ confidence ไปอยู่รายละเอียด Admin ไม่กล่าวว่าเหตุการณ์ที่เกิดพร้อมกันเป็นสาเหตุ
5. **เคลื่อนไหวน้อยแต่มีความหมาย:** feedback เมื่อข้อมูล/คำสั่งเปลี่ยน ไม่ pulse
   ทั้งจอตลอดเวลา; เคารพ reduced-motion และหยุด canvas ที่ซ่อน/แท็บไม่ active
6. **Touch-first:** ตัวเลข tabular, line icon ชุดเดียว, spacing 8/12/16/24,
   minimum touch 44px, ไม่ใช้สีอย่างเดียวบอกสถานะ, keyboard/focus ใช้ได้ครบ

## แยกการพัฒนาให้ชัด

| ชั้น | รับผิดชอบ | ห้ามทำ |
| --- | --- | --- |
| Shell / navigation | route, role presentation, fullscreen, connection status | คำนวณคะแนนหรือสั่งอุปกรณ์เอง |
| Shared components | metric, section heading, empty/error/loading, trend, timeline | fetch หรือ policy ที่ซ่อนอยู่ใน component |
| Page controller | รับ event, โหลดข้อมูล, loading/error/race, เรียก presenter | ผสม SQL/serial/MQTT หรือคัดสูตรจาก Python |
| Presenter / view model | แปลง API เป็นข้อความ/หน่วย/กราฟ, pure function ทดสอบได้ | กลบ missing เป็นศูนย์ หรือเปลี่ยน derived result |
| API adapter | REST/WebSocket/auth/cancellation/error contract | ยืนยันอุปกรณ์สำเร็จแทน physical feedback |
| Backend domain | คะแนน, Baseline, Session, Safety, hardware adapter | ฝากสิทธิ์หรือ Safety ไว้เฉพาะ JavaScript |

โครงสร้างเป้าหมายแบบ incremental:

```text
static/partials/app/
  shell.html                 # ทำแล้ว
  scripts/                   # legacy ordered fragments; ค่อยลดหน้าที่
  components/                # ROADMAP: shared markup/presenter
  pages/{dashboard,control,monitor,sessions}/  # ROADMAP
static/styles/
  connection-state.css       # ทำแล้ว: scoped component
  monitor.css, sessions.css  # มีแล้ว; ค่อยย้าย legacy overrides
tests/frontend/              # ทำแล้ว: synthetic behavioral tests
```

ไม่เพิ่ม ES module/import หรือ framework พร้อมการย้ายครั้งใหญ่ เพราะ classic
script เดิมยังพึ่ง globals/inline handler; ย้ายหนึ่ง feature พร้อม adapter
และ characterization test ก่อน แล้วจึงเปลี่ยน bootstrap เมื่อ dependency ชัด

## ลำดับพัฒนาถัดไปและเกณฑ์รับงาน

### 1. Monitor information architecture

ย้าย section heading ให้อยู่ข้าง content ใน DOM จริง ไม่พึ่ง CSS `order`:
ลำดับอ่าน/Tab/ภาพต้องตรงกัน ลดข้อมูลซ้ำ และปรับข้อความ 7.5–9.5px ที่ยังพบ
ใน Adaptive/Smart Ear ให้ใช้งานได้บนจอจริง ห้ามย้าย Safety ลงใต้ข้อมูลเชิงลึก

### 2. Dashboard และ Control feedback

Dashboard ลดพื้นที่ empty card เมื่อไม่มี Session; แสดงคู่ HR/RR กับ Reference
พร้อมจำนวนครั้งและโหมดที่เทียบ Control แยก requested/acknowledged/physical
เมื่อมีหลักฐานจริงเท่านั้น รักษาปุ่มประตูฉุกเฉินที่เข้าถึงได้ง่าย

### 3. Sessions visual summary

รายชื่อ compact, selected row ชัด, selected report หนึ่งจุด แยก trend ตามโหมด
รักษา denominator/coverage/provisional ตาม API ไม่คำนวณคะแนนซ้ำใน browser
ทดสอบ long email, ไม่มีรายการ, error, เปิดรายงานเก่าสลับเร็วและมือถือ

### 4. Accessibility / performance

Confirm dialog ต้องมี focus trap/คืน focus, SPA เปลี่ยนหน้าต้องย้าย focus
อย่างเหมาะสม, canvas หยุดเมื่อไม่แสดง, ค่อยแยก theme ใหญ่ตาม owner
วัดก่อน/หลังจริง ไม่ยกการลดจำนวนบรรทัดเป็นหลักฐานว่าระบบเร็วขึ้น

ทุกขั้นต้องผ่าน User/Admin, 1440×900, 1280×720, 800×1280, 390×844,
Focus Mode, keyboard, reduced-motion, no horizontal overflow และ failure states
ไม่ทดสอบด้วยการสั่งประตู/เตียง/แอร์บนตู้จริงโดยไม่มีแผนทดสอบอุปกรณ์

## การตรวจสอบและแหล่งอ้างอิง

- [UI source/build guide](../static/partials/app/README.md)
- [Testing policy](../TESTING.md), [Product language](zeep-product-language-guideline-v1.md)
- [Current result presentation](zeep-session-result-presentation-v1.md)
- [Official setup-node](https://github.com/actions/setup-node): ใช้ v7 และ Node 24
  สำหรับ CI behavioral tests; ไม่ใช่ runtime ของตู้
- Evidence รอบนี้: UI source audit + synthetic frontend tests + browser smoke
  บน Pod หลัง deploy; ผล test/restart บันทึกใน release review แยกจาก roadmap
