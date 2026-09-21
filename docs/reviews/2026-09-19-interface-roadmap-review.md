# ZEEP Interface — บันทึกการทบทวนร่วม

สถานะ: **ตรวจโค้ดและจัดทำแผน · ยังไม่ได้แก้ Runtime ตามข้อค้นพบ**

สถานะข้างต้นเป็นของรอบ `9516413` เท่านั้น งานที่ทำต่อ เช่นคำแนะนำหลังพัก v1.2
และ Rerun ให้ดู [Current Status](../current-status.md) ผล tests ในบันทึกนี้ไม่รับรอง SHA ใหม่

วันที่: 19 กันยายน 2026 · Git ฐานตรวจ: `9516413`

ขอบเขต: เทคนิค การออกแบบ ข้อมูล และศิลปะร่วมสมัย

## สรุป

ระบบมีฐานที่เหมาะสมแล้ว: Shell ร่วม, สถานะข้อมูลสด, ประวัติแยกโหมด และหน้าสรุป
ผลแบบ component สิ่งที่ควรทำก่อนเพิ่มความสวยงามคือความเป็นส่วนตัวหลังจบการพัก
ความหมายค่าที่ตรงกันทุกช่องทาง และวงจรโหลดข้อมูลที่ไม่สับสนข้ามผู้ใช้

แผนที่ใช้งานต่ออยู่ใน [Interface Roadmap](../zeep-interface-development-roadmap.md)
บันทึกฉบับนี้เป็นหลักฐาน ณ SHA ที่ระบุ ไม่ใช่คู่มือ Runtime ฉบับใหม่

## วิธีทบทวนและบทบาท

- ผู้ช่วย AI ด้านเทคนิค: module boundary, request lifecycle, control feedback,
  performance และขอบเขต tests
- ผู้ช่วย AI ด้านการออกแบบ: โครงเรื่องทุกหน้า touch, keyboard, focus และการเข้าถึง
  พร้อมรอบทบทวน Art Direction แยกอีกครั้ง
- ผู้ช่วย AI ด้านข้อมูล: โหมดคะแนน ค่าหาย Baseline กราฟ การเผยแพร่ผล และ Privacy
- ผู้พัฒนา: ตรวจ source ซ้ำ รวมข้อคิดเห็นด้านภาพ/ภาษา และตรวจเอกสาร W3C

เป็นการช่วยตรวจโค้ดและออกแบบโดย AI ไม่ใช่การรับรองจากผู้ประกอบวิชาชีพหรือ
ผลทดสอบ usability กับผู้ใช้จริง ไม่ได้ล็อกอินหรือตรวจ Production ซ้ำในรอบนี้

## ข้อค้นพบที่ยืนยันจาก Source

| รหัส | ข้อค้นพบและขอบเขต | หลักฐาน | งานใน Roadmap |
| --- | --- | --- | --- |
| UI-01 | มี timeout/cancel/retry/race guard ในรายการประวัติ แต่ยังไม่ครบใน detail/directory/journey จึงไม่ควรเขียนว่า Sessions ทั้งหน้าทำแล้ว | [History](../../static/partials/app/scripts/11-history-list.js) `refreshHistory:148`, `refreshUserJourney:429`, `loadDetail:496`; [Directory](../../static/partials/app/scripts/11-usage-users.js) `:91` | P1-01 |
| UI-02 | Heading ของ Monitor อยู่ติดกันใน DOM แล้วกระจายเนื้อหาด้วย CSS order; โครงเรื่องที่อ่านไม่ตรงกับการจัดภาพ | [Template](../../static/index.template.html) `:292`; [Monitor CSS](../../static/styles/monitor.css) `:54` | P1-02 |
| UI-03 | Confirm dialog มี initial focus/Escape แต่ไม่มี trap/restore; SPA เปลี่ยน title/scroll แต่ไม่ย้าย focus | [Client API](../../static/partials/app/scripts/06-client-api.js) `:51`; [Shell](../../static/app-shell.js) `:146` | P1-02 |
| UI-04 | Audio visualizer ใช้ random/sine และ RAF ต่อเนื่อง ไม่ใช่ waveform จาก Sensor; ไม่มี visibility/reduced-motion guard ในฟังก์ชัน | [Runtime](../../static/partials/app/scripts/13-runtime-websocket.js) `:1–35` | P1-05 |
| UI-05 | PNG แปลงค่าผิดรูปแบบเป็น 0 ได้ ต่างจาก HTML ที่ปฏิเสธค่าผิดชนิด; Admin evidence ยังแปลง null เป็น 0 ได้ | [Canvas](../../static/partials/app/scripts/10-session-end-report.js) `:190`; [Result](../../static/partials/app/scripts/11-result-summary.js) `:2`; [Admin evidence](../../static/partials/app/scripts/11-history-list.js) `:332` | P0-02 |
| UI-06 | เมื่อเปิด report share หน้าจบแสดงตัวตน/ผล และยืดเวลาค้างหน้าจอตามอายุ QR link | [Session End](../../static/partials/app/scripts/10-session-end-report.js) `:34`, `:54`, `:106` | P0-01 |
| UI-07 | Baseline/Trend ฝั่ง Server มีขอบเขตโหมด เป้าหมาย สูตร และหน้าต่างตามจำนวนครั้ง แต่ shared summary ยังแสดงหลัก ๆ เพียง maturity/count | [Baseline](../../sessions/restore_summary_baseline.py) `:71`, `:181`; [Result](../../static/partials/app/scripts/11-result-summary.js) `:157` | P1-04 |
| UI-08 | Control มี feedback คำสั่งแล้ว แต่ตำแหน่งเตียงบางค่าเป็นการสะสมคำสั่ง/local state และ AC บางสถานะไม่มี physical feedback | [Client API](../../static/partials/app/scripts/06-client-api.js) `:98`; [Hardware actions](../../static/partials/app/scripts/05-hardware-actions.js) `:228`; [Controls](../../static/partials/app/scripts/04-unified-controls.js) `:631` | P0-03 |

หมายเลขบรรทัดอ้างอิง SHA ฐานตรวจ อาจเปลี่ยนหลัง Refactor
UI-05 ยืนยันด้วยข้อมูลจำลองในหน่วยความจำ ไม่ได้พิสูจน์ว่าข้อมูลผิดชนิดดังกล่าว
ผ่านมาจาก Backend จริง ส่วน UI-06 เป็นความเสี่ยงจากการออกแบบ ไม่ใช่หลักฐานข้อมูลรั่ว
UI-04 ยังไม่ใช่ผลวัดว่าระบบช้าหรือใช้ CPU เท่าใด ต้องวัดก่อน–หลังบนเครื่องเป้าหมาย

## ทิศทางภาพที่เห็นร่วมกัน

1. คงพื้นมืดและลดแสงเรือง ให้ข้อมูลสำคัญเด่นด้วยลำดับและช่องว่าง
2. สี mint/ม่วงบอกโหมด ไม่ใช่ระดับสุขภาพ; คำเตือนมีสีและข้อความของตนเอง
3. ใช้ SVG ชุดเดียวแทน `☺`/`🌿` ที่รูปร่างต่างกันตามระบบปฏิบัติการ
4. ขยายคำประกอบที่จำเป็นก่อนเพิ่มกราฟ ไม่ย่อฟอนต์เพื่อยัดข้อความไทยบรรทัดเดียว
5. ลดกรอบซ้อน สงวนพื้นเน้นให้คำแนะนำหลักและคำเตือน
6. วงคะแนนมีเพียงหนึ่งวง; แถบคะแนนมีตัวหาร; กราฟแนวโน้มมีเวลาและช่องข้อมูลขาด
7. ไม่มี score count-up หรือ waveform ตกแต่งที่ดูเหมือนข้อมูลวัดจริง
8. หน้าผู้ใช้ใช้คำสั้นและรายละเอียดแบบเปิดเพิ่ม หน้าผู้ดูแลคงหลักฐานทางเทคนิค

สี ขนาด และ motion tokens ใน Roadmap เป็นข้อเสนอ ยังต้องตรวจ contrast,
computed layout และฟอนต์ไทยบนเครื่องจริง ไม่ใช่ชุดที่รับรองแล้ว
ตัวอย่าง source ที่ต้องทบทวนคือ [Result CSS](../../static/styles/result-summary.css)
ซึ่งมีคำประกอบ 10 px และ [Theme](../../static/theme-modern.css) ซึ่งมี override หลายชั้น

## ประเด็นที่ไม่เลือกทำ

- ไม่ย้าย framework หรือแยกทุกไฟล์เป็น module ในครั้งเดียว
- ไม่สร้างคะแนนใหม่หรือเพิ่มคะแนนเพื่อให้ภาพดูดี
- ไม่ถือ ACK เป็นการยืนยันสถานะจริง และไม่ส่งคำสั่งอุปกรณ์ซ้ำเองเมื่อ timeout
- ไม่ใช้ self-report ที่ไม่มีอยู่จริงเติมข้อความ “สดชื่นขึ้น”
- ไม่รวม Sleep Score/Recovery Score เป็นค่าเฉลี่ยเดียว หรือเรียกจำนวนครั้งว่า “วัน”
- ไม่ทำให้คำเตือน Safety อ่อนลงเพื่อความสวยงาม

## เอกสารที่ปรับในรอบนี้

| เอกสาร | สิ่งที่แก้ |
| --- | --- |
| [Interface Roadmap](../zeep-interface-development-roadmap.md) | แยกทำแล้ว/ยังไม่ครบ; จัดงาน P0–P2 พร้อม owner และเกณฑ์รับงาน; เพิ่มแนวภาพและความหมายกราฟ |
| [Product Language](../zeep-product-language-guideline-v1.md) | เพิ่มชุดคำไทยสั้นทางการและเงื่อนไขการใช้; ไม่เปลี่ยน runtime language version |
| [Interface Map](../zeep-interface-map-and-ui-standard-v1.md) | วาง selected report ก่อน trend; ระบุขอบเขตหลักฐาน audit เก่าและมาตรฐานเป้าหมาย |
| [UI Source Guide](../../static/partials/app/README.md) | เพิ่ม inventory ของ `11-usage-users.js` ที่มีอยู่แล้ว |
| [Documentation Index](../README.md) | เชื่อมแผนและบันทึกทบทวนนี้เข้าจุดเริ่มของทีม |

## Verification

- ดึง `origin/develop` แล้ว ไม่มีโค้ดใหม่กว่าฐาน `9516413` ก่อนเริ่มตรวจ
- ผู้ตรวจเทคนิครัน composer check, UI/product/frontend wrapper: 56 tests ผ่าน
  และ Node behavioral tests: 46/46 ผ่าน บนฐานโค้ดเดิม
- ชุดทดสอบข้างต้นเป็น synthetic/VM ไม่ใช่ browser, screen reader, hardware,
  live Admin หรือ performance certification
- งานเขียนเอกสารตรวจด้วย `test_documentation_alignment` และ `test_product_language`
  รวม 14 tests ผ่าน; `git diff --check` ผ่าน ไม่รัน Full ซ้ำเพื่องานเอกสาร
- ผู้ตรวจด้านข้อมูลอ่านฉบับรวมซ้ำ ไม่พบ blocker ด้านข้อมูล คำกล่าว หรือสถานะงาน
- ไม่มีการแก้ Application, API, Firmware, ข้อมูลผู้ใช้, Raw หรือคะแนนย้อนหลัง
  และไม่มี Push, Deploy, Restart หรือ Rerun ในรอบนี้

เกณฑ์อ้างอิงภายนอก: [W3C Contrast](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html),
[W3C Target Size](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum)
และ [W3C Modal Dialog](https://www.w3.org/WAI/ARIA/apg/patterns/dialog-modal/)
ใช้กำหนดเกณฑ์ตรวจ ไม่ใช่ประกาศว่า ZEEP ผ่าน WCAG ทั้งระบบแล้ว
