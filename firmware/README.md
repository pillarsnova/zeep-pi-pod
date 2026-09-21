# ZEEP firmware

- [Sensor Hub 1 · ESP32-S3](sensorhub1-esp32s3/README.md) — Source ที่พัฒนาต่ออยู่:
  SHT3x-DIS, OPT3001, SPH0645LM4H-B และ DSP shadow; Pi รับ `sound_dba` โดยตรง
- [สถานะและหลักฐานที่ตรวจล่าสุด](../docs/current-status.md) — มีหลักฐาน Firmware
  DSP บน Pod 1 แล้ว ไม่ได้หมายความว่าป้ายเสียงผ่านการรับรองความแม่นยำ

การ Flash เป็นส่วนหนึ่งของการทดลองบนอุปกรณ์เมื่อเจ้าของอนุมัติ ไม่ต้องมีผล CEM
ก่อน Flash ครั้งแรก แต่ต้องมี backup, board identity, Pod ว่างและทาง rollback
การรับรอง calibration/label accuracy เป็นขั้นตอนหลังเก็บผลจริง แยกจาก build pass

Flash images และ full-Flash backups เป็น device artifacts ที่อาจมีข้อมูลลับ
จึงไม่เก็บใน Git ให้ใช้ checksum manifest และตำแหน่งสำรองที่ระบุในคู่มือของ
Firmware แต่ละชุดแทน
