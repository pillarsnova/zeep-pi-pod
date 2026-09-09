# ZEEP firmware

- [Sensor Hub 1 · ESP32-S3](sensorhub1-esp32s3/README.md) — งานทดลอง Firmware
  ทดแทนที่เก็บเป็นประวัติ; Runtime ปัจจุบันเชื่อ `sound_dba` จาก ESP32 โดยตรง
  และไม่มีแผน Flash จากชุดนี้

Flash images และ full-Flash backups เป็น device artifacts ที่อาจมีข้อมูลลับ
จึงไม่เก็บใน Git ให้ใช้ checksum manifest และตำแหน่งสำรองที่ระบุในคู่มือของ
Firmware แต่ละชุดแทน
