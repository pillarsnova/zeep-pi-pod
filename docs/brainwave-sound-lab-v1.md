# ZEEP Brainwave Sound Lab v1.0

สถานะ: **Experimental Wellness Audio — ไม่ใช่อุปกรณ์วินิจฉัยหรือรักษาโรค**
Software version: `zeep-speaker-sound-lab-v1.0`

## 1. วัตถุประสงค์

ระบบนี้นำแนวคิดจากต้นแบบ `zeep-brainwave.html` มาทำเป็นการทดลองที่เล่นผ่าน
ลำโพงจริงของ ZEEP โดยตรงจาก Raspberry Pi 5 และทำงานได้โดยไม่พึ่ง Internet
สิ่งที่นำมาใช้คือ carrier tone, rhythmic modulation, pink ambience, fade
เข้า/ออก และเสียงหลายช่วง ส่วนการเล่นแบบ Web Audio จาก Tablet และการโหลด
CDN ภายนอกไม่ถูกนำมาใช้ในระบบจริง

ต้นแบบใช้ binaural beat ที่แยกความถี่ซ้าย/ขวา แต่ลำโพงในพื้นที่ปิดมี acoustic
cross-talk และไม่รับประกันว่าหูแต่ละข้างจะได้รับคนละ channel ระบบรุ่นนี้จึงใช้
**speaker-compatible amplitude modulation (AM)** แทน และไม่อ้างว่าเสียงจะ
บังคับสมองให้เข้าสู่ความถี่หรือ Sleep Stage ใด

## 2. สถาปัตยกรรม

1. Admin เลือก Preset, เวลา 10–90 วินาที และ Digital Volume 0–60% ที่
   `/control-debug`
2. `GET /api/admin/brainwave/presets` คืน catalog และ version
3. `POST /api/admin/brainwave/preview` สร้าง Stereo PCM WAV บน Pi ด้วย
   `brainwave_audio.py`
4. `AudioPlayer` เล่นไฟล์ผ่าน MPV และ ALSA ไปยังลำโพง ZEEP จริง
5. Event log บันทึก operator, preset, version, duration และ volume เพื่อทำซ้ำได้

ไฟล์ Preview อยู่ใน `data/brainwave_audio/` ซึ่งเป็น Runtime Data และไม่ถูก
นำเข้า Git ส่วนเพลงทั่วไปใน `music/` ไม่ถูกแก้ไข

## 3. Preset สำหรับทดสอบ

| ID | รูปแบบ | จุดประสงค์การประเมิน |
|---|---|---|
| `control-pink` | Pink ambience ไม่มี AM | Control condition สำหรับ A/B test |
| `relax-alpha` | 10 Hz AM แบบตื้น | ความไพเราะ/การรบกวนในโหมดผ่อนคลาย |
| `winddown-theta` | 6 Hz AM แบบตื้น | ความรู้สึกสงบในช่วงเตรียมพัก |
| `nap-theta-alpha` | 6 → 9 Hz AM | ความต่อเนื่องของเสียงสองช่วงในโหมดงีบ |
| `night-delta` | 2 Hz AM แบบตื้น | ความไพเราะและการรบกวนก่อนนอน |

ชื่อย่านความถี่เป็น **พารามิเตอร์การออกแบบเสียง** ไม่ใช่ผลตรวจ EEG และไม่ใช่
คำรับรองผลการนอน

## 4. Safety และ Human-subject Guard

- Sound Lab แสดงเฉพาะ Admin และ Backend ตรวจสิทธิ์ซ้ำ
- หากมี Active Session ต้องยืนยันว่าได้รับอนุญาตจากผู้ใช้งานก่อนเล่น
- Safety emergency latch จะปฏิเสธการเริ่ม Preview
- Digital Volume ถูกจำกัดไม่เกิน 60% แต่เปอร์เซ็นต์นี้ **ไม่ใช่ dB(A)**
- ก่อนทดสอบกับอาสาสมัคร ให้ใช้ CEM DT-8852 โหมด SLOW วัด ณ ตำแหน่งศีรษะ
  และยึดเกณฑ์เสียงของโครงการที่อนุมัติแล้ว
- ผู้ใช้ต้องหยุดเสียง/ออกจากการทดลองได้ทุกเมื่อ

WHO แนะนำให้ลดระดับเสียงและเวลาสัมผัส รวมทั้งพักหูเป็นระยะ หลักการดังกล่าวใช้
เป็น safety ceiling ทั่วไป แต่การทดลอง ZEEP ควรใช้ระดับต่ำกว่านั้นมากตามบริบท
การพักและการนอน: [WHO Safe Listening](https://www.who.int/news-room/questions-and-answers/item/deafness-and-hearing-loss-safe-listening)

## 5. วิธีประเมินที่แนะนำ

ใช้ randomized A/B ภายในคนเดียวกันเมื่อทำได้ โดยสลับ `control-pink` กับ Preset
ที่มี AM และคง duration, Digital Volume, ตำแหน่งลำโพง และสภาพแวดล้อมเท่ากัน

ข้อมูลขั้นต่ำต่อรอบ:

- Preset ID + version + เวลา + Digital Volume + dB(A) จาก Meter
- Pleasantness, harshness/annoyance และ relaxation แบบ 0–10
- ต้องการหยุดเสียงหรือไม่ และเหตุผลสั้น ๆ
- HR/RR ก่อน–ระหว่าง–หลัง ใช้เป็น exploratory response เท่านั้น
- Sleep latency/continuity ใช้ประกอบเมื่อเป็น Sleep Mode แต่ไม่ใช้ยืนยันว่า AM
  เป็นสาเหตุ และไม่ใช้ Preset เป็นตัวกำหนด Sleep State

เกณฑ์เลือก “เสียงไพเราะ” ควรอิง Median pleasantness สูง, annoyance ต่ำ และไม่มี
คำขอหยุดก่อนเวลา ไม่เลือกจากความถี่ที่ตั้งไว้เพียงอย่างเดียว

## 6. ขอบเขตหลักฐาน

ผลการศึกษายังไม่สม่ำเสมอ จึงต้องมี control และหลีกเลี่ยง causal/medical claim:

- RCT ในผู้มี subclinical insomnia พบว่า theta binaural beat ร่วมกับเพลงไม่ได้
  ทำให้ผลด้านการนอนดีกว่าเพลงเพียงอย่างเดียวอย่างมีนัยสำคัญ:
  [Bang et al., 2019](https://pubmed.ncbi.nlm.nih.gov/31433343/)
- RCT ในห้องฉุกเฉินพบว่าทั้งเสียงดนตรี/ธรรมชาติและเสียงที่มี binaural beat
  ลดความกังวลได้ แต่การออกแบบไม่แยกผลของ binaural beat ออกจากองค์ประกอบอื่น:
  [Weiland et al., 2011](https://pubmed.ncbi.nlm.nih.gov/22171868/)
- งาน EEG หนึ่งชิ้นพบผลต่างกันตามความถี่ โดย 18 Hz มีผลที่ตรวจพบ ขณะที่ 40 Hz
  ไม่แสดง pattern เดียวกัน จึงไม่ควรเหมารวมทุก preset:
  [Trost et al., 2023](https://pubmed.ncbi.nlm.nih.gov/38044462/)

## 7. Definition of Done ก่อนเลื่อนเป็น User feature

1. ผ่าน Regression test และเล่นออกอุปกรณ์ ALSA จริง
2. ไม่มี clipping/click ที่ต้นทางและรอยต่อ phase
3. วัด dB(A) ณ หมอนผ่านเกณฑ์โครงการในทุกระดับที่อนุญาต
4. ผ่าน Pilot A/B และทีมอนุมัติ preset/version เป็นลายลักษณ์อักษร
5. ระบุ consent, stop rule, adverse-event log และ retention ของผลทดลอง
6. หากแก้พารามิเตอร์ใด ต้องเพิ่ม version ห้ามแก้ความหมายของ version เดิม
