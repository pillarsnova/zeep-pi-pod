# ZEEP POD Knowledge Hub

หน้าอ่านคู่มือสำหรับทีม ใช้เอกสาร Markdown ที่มีอยู่เป็นต้นทาง
ไม่ใช่เอกสารอำนาจชุดใหม่ ไม่อ่านฐานข้อมูลผู้พัก และไม่เรียกคำสั่งอุปกรณ์

## เปิดอ่าน

- ในระบบ Pi หลัง Deploy งานนี้: `/handbook` ต้องเข้าสู่ระบบ Admin ก่อน
- บนเครื่องทีม: เปิด `docs/portal/index.html` ได้โดยไม่ต้องต่ออินเทอร์เน็ต
- ลิงก์เอกสารต้นฉบับและงานวิจัยต้องใช้อินเทอร์เน็ต

ประกอบด้วย 10 หมวด: เริ่มต้น, สถาปัตยกรรม, Smart Senses, การพักและคะแนน,
Adaptive, API/ข้อมูล, Interface, Operations, งานวิจัย และผลตรวจตามวันที่
ค้นหาได้ทั้งชื่อและเนื้อหา อ่านฉบับเต็ม มีสารบัญย่อย ลิงก์บท และพิมพ์ / Save as PDF
โดยคำสั่งพิมพ์ใช้เฉพาะหน้าหรือบทที่กำลังอ่าน ไม่พิมพ์เอกสารทั้งหมดพร้อมกัน

สถานะทบทวน 22 ก.ย. 2026: คู่มือปัจจุบัน 59 บท งานนี้ยังอยู่ใน Working tree
บน Mac และ Pod ที่ตรวจ 20:57 +07 ยังเป็น `78e90fc`; ไม่ใช่หลักฐานว่า `/handbook`
เปิดบน Pod แล้ว อ่าน [ผลทบทวนเนื้อหา](../docs/reviews/2026-09-22-documentation-refresh.md)

## โครงสร้างและการอัปเดต

| ไฟล์ | หน้าที่ |
|---|---|
| `catalog.json` | Allowlist เอกสาร หมวด ชื่อย่อ คำอธิบาย และประเภท |
| `rendering.py` | แปลง Markdown อย่างปลอดภัยและเชื่อมลิงก์ระหว่างบท |
| `builder.py` | รวมเนื้อหาและคำนวณ checksum เป็น HTML ไฟล์เดียว |
| `assets/` | Template, CSS และ JavaScript แยกกัน |
| `api/handbook_routes.py` | Route แบบอ่านอย่างเดียวสำหรับ Admin |
| `docs/portal/index.html` | ผล Build ที่ส่งไปพร้อมโค้ด ไม่แก้ด้วยมือ |

```sh
python -m pip install -r requirements-dev.txt
python -m documentation build
python -m documentation check
python -m unittest test_handbook -v
```

เมื่อแก้ต้นทางที่อยู่ใน catalog ต้อง Build ใหม่ก่อน Commit; CI ตรวจความตรงกัน
วันที่ใน catalog คือวันที่ตรวจการจัดชุด ไม่ใช่วันที่ Deploy หรือวันที่เอกสาร
ทุกบทผ่านการ Review ซ้ำ ดูวันที่/SHA ภายในแต่ละบทและ Current Status ประกอบ
digest คำนวณจาก catalog กับเนื้อหาจริง ไม่ผูกกับเวลาบนเครื่องหรือ HEAD ที่เปลี่ยนทุก Commit

## ขอบเขตและความปลอดภัย

- ไม่มี CDN, Analytics, external font หรือ API call ระหว่างอ่าน
- ไม่มี Raw session, ฐานข้อมูล, `.env`, token, flash backup หรือ private export
- Bundle อยู่นอก `/static`; `/handbook` ใช้ `require_admin` และ `no-store`
- HTML จาก Markdown ไม่ถูกประมวลผล; ปิด remote images และ URL scheme ที่ไม่อนุญาต
- ไฟล์นอก repository และ symlink ที่ออกนอกขอบเขตถูกปฏิเสธ
- ลิงก์ Markdown ที่อยู่ในชุดเปิดในหน้าเดิม ลิงก์ Source เปิด GitHub `develop`
  ซึ่งอาจใหม่กว่าฉบับ Bundle ให้เทียบ checksum และสถานะระบบก่อนอ้างผล
- ไฟล์อ้างอิงที่ไม่อยู่ในชุดเปิดได้จากต้นฉบับ หากหายหรืออยู่นอกขอบเขต
  จะแสดงเป็นข้อความอ้างอิงแทนลิงก์ที่ใช้งานไม่ได้
- Offline HTML เป็นสำเนาเอกสารภายใน ให้แชร์เฉพาะทีม ไม่ใช่หน้า Public Marketing

## Verification

รัน Test เฉพาะ Build, ความปลอดภัยลิงก์, ความครบของ Catalog, Route และ RBAC
พร้อมตรวจ Desktop/Mobile, Search, Chapter links และ Print stylesheet ก่อนส่งมอบ
ชุดนี้ไม่เปลี่ยนสูตร Sleep/Recovery Score และไม่ทำ Rerun หรือ Restart โดยอัตโนมัติ

ผลตรวจหน้าเว็บรอบสร้างเริ่มต้น 22 กันยายน 2026 บน Mac ก่อนทบทวนเนื้อหา
(58 บทในรอบนั้น; Source เท่านั้น ยังไม่ Deploy):

- รวมเอกสาร 58 บท / 10 หมวด; ลิงก์หัวข้อระหว่างบทตรงกับ Heading ทั้งหมด
- Focused regression 159 tests ผ่าน รวม Build, RBAC, Architecture และ Frontend
- Browser QA ทุกบทที่ 1440, 800 และ 390 px ไม่พบ Horizontal overflow หรือ JS error
- Search, No-results, Mobile menu/TOC, Heading links และ Skip link ทำงาน
- เปิดไฟล์แบบ Offline ได้; ไม่พบ External request อัตโนมัติระหว่างอ่าน
- Print stylesheet ซ่อน Navigation/ปุ่มและแสดงเนื้อหารายบทบนพื้นขาว
- `python -m documentation check`, `ui_composer.py check` และ Ruff ผ่าน

ผลนี้ไม่ใช่การรับรองว่าเครื่อง Pod ใช้โค้ดชุดนี้แล้ว และไม่ได้ทดสอบอุปกรณ์จริง
