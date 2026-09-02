# แผนเปิดใช้งานผ่าน URL — ZEEP Pod Dashboard

> **สถานะ:** แผนสำหรับทีม · ตอนนี้ทีมรัน local บน Pi/เครื่องตัวเอง
> **หลักการ:** ตัวแอปต้องรันบน **Pi ในตู้** เสมอ (ต่อ GPIO/serial/ลำโพงจริง) —
> สิ่งที่ "ขึ้น server" คือ**ทางเข้าแบบปลอดภัย (tunnel + URL)** ไม่ใช่การย้ายแอปขึ้น cloud

## ภาพรวมสถาปัตยกรรม

```
[ทีม/แท็บเล็ต ที่ไหนก็ได้] ──HTTPS──▶ [URL เช่น pod.zeep.world]
                                          │  (Cloudflare Tunnel / Tailscale)
                                          ▼
                                   [Pi 5 ในตู้ ZEEP]
                                   app.py :8000 ── GPIO / ESP32 / BCG / ลำโพง
```

- เบราว์เซอร์เห็นหน้าเดิมทุกอย่าง (WebSocket ทำงานผ่าน tunnel ได้)
- ทีมที่อยู่หน้าตู้ยังใช้ hotspot/LAN แบบเดิมได้พร้อมกัน — tunnel เป็นทางเข้าเพิ่ม ไม่แทนของเดิม

## เลือกเส้นทาง (แนะนำทำ Phase 1 → 2 ตามลำดับ)

| ทางเลือก | ได้อะไร | เหมาะกับ | เวลาติดตั้ง |
|---|---|---|---|
| **1. Tailscale** (แนะนำเริ่มก่อน) | URL ภายในทีม `http://zeep-pod:8000` — เครือข่ายส่วนตัว ไม่มีอะไรเปิดสู่อินเทอร์เน็ตสาธารณะ | ใช้งานภายในทีมทันที ปลอดภัยสุด | ~30 นาที |
| **2. Cloudflare Tunnel** | URL จริง `https://pod.zeep.world` + หน้า login อีเมลทีม (Cloudflare Access) ก่อนถึง dashboard | สั่งการผ่าน URL website ตามโจทย์ · demo ให้คนนอกทีมดูแบบคุมสิทธิ์ | ~1 ชั่วโมง |
| 3. VPS + WireGuard + nginx | ควบคุมเองทั้งหมด ไม่พึ่ง Cloudflare | ภายหลัง ถ้ามีนโยบายห้ามใช้บริการภายนอก | ครึ่งวัน+ |

ห้ามทำ: เปิด port forward ตรงจาก router สู่ Pi (`:8000` เปลือย ๆ) — ระบบนี้สั่งประตู/อุปกรณ์จริงและมีข้อมูลส่วนบุคคล

---

## Phase 1 — Tailscale (ทีมใช้ได้วันนี้)

บน Pi:
```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up --hostname=zeep-pod
```
ทุกคนในทีมติดตั้งแอป Tailscale + login บัญชีเดียวกัน (หรือ invite เข้า tailnet)
→ เปิด `http://zeep-pod:8000` ได้จากทุกที่ (เปิด MagicDNS ใน admin console)

## Phase 2 — Cloudflare Tunnel + URL จริง

เงื่อนไข: โดเมน `zeep.world` ต้องย้าย DNS ไปอยู่กับ Cloudflare (ฟรี)

บน Pi:
```bash
# 1) ติดตั้ง cloudflared
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64.deb -o cloudflared.deb
sudo dpkg -i cloudflared.deb

# 2) login + สร้าง tunnel
cloudflared tunnel login
cloudflared tunnel create zeep-pod
cloudflared tunnel route dns zeep-pod pod.zeep.world
```

`~/.cloudflared/config.yml`:
```yaml
tunnel: zeep-pod
credentials-file: /home/pi/.cloudflared/<tunnel-id>.json
ingress:
  - hostname: pod.zeep.world
    service: http://localhost:8000
  - service: http_status:404
```

จากนั้นใน **Cloudflare Zero Trust → Access** สร้าง Application ครอบ `pod.zeep.world`
policy = อนุญาตเฉพาะอีเมลทีม (OTP ทางอีเมล ไม่ต้องมีระบบ login เพิ่มในแอป)

## Phase 3 — ทำให้อยู่ถาวร (systemd)

`/etc/systemd/system/zeep-pod.service`:
```ini
[Unit]
Description=ZEEP Pod Dashboard
After=network-online.target

[Service]
User=pi
WorkingDirectory=/home/pi/pi5
Environment=API_TOKEN=ตั้งรหัสยาวที่นี่
ExecStart=/home/pi/pi5/.venv/bin/python app.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl enable --now zeep-pod
sudo cloudflared service install   # tunnel เป็น service ด้วย
```
→ Pi เปิดปุ๊บ ระบบ + URL ขึ้นเองทุกครั้ง ไฟดับ-ไฟมาก็ฟื้นเอง

---

## Guardrails บังคับเมื่อเข้าถึงจากนอกตู้ได้

1. **`API_TOKEN` ต้องตั้งเสมอ** (ระบบรองรับอยู่แล้ว — ทุกคำสั่งควบคุมต้องมี token, เปิดหน้าเว็บครั้งแรกด้วย `?token=...`)
2. **HTTPS เท่านั้น** — Cloudflare จัดการให้อัตโนมัติ (ข้อมูล session มีชื่อผู้ใช้ + HR/RR = ข้อมูลส่วนบุคคลตาม PDPA ห้ามวิ่ง plain HTTP ผ่านอินเทอร์เน็ต)
3. **นโยบายสั่งประตูจากระยะไกล:** ให้สั่ง OPEN/CLOSE เฉพาะเมื่อมีคนอยู่หน้าตู้ยืนยันว่ารางว่าง (นัดกันทางแชต/โทร) — pre-G1 ยังห้ามมีคนในตู้อยู่แล้ว แต่ของ/มือ/สัตว์เลี้ยงขวางรางคือความเสี่ยงจริง · อนาคตค่อยเพิ่มโหมด remote-readonly แยกปุ่มอันตราย
4. **จำกัดคนเข้า** ด้วย Cloudflare Access (รายชื่ออีเมล) — token อย่างเดียวกันคนนอกไม่ได้ถ้า URL หลุด
5. ข้อมูล profile/session ยังเก็บ**บน Pi เท่านั้น**เหมือนเดิม — ไม่มีอะไรขึ้น cloud

## ตัวเลือกเสริม — Demo server แบบไม่มีฮาร์ดแวร์

อยากมี URL ให้คนดู UI โดยไม่แตะตู้จริง: รันแอปบน VPS/เครื่องไหนก็ได้ (GPIO เป็น mock อัตโนมัติ, ไม่มี sensor = ขึ้น Disconnected ตามจริง) แล้วต่อ tunnel แบบเดียวกัน เช่น `demo.zeep.world` — ใช้โชว์ flow login/รายงาน/เสียงได้โดยไม่มีความเสี่ยงใด ๆ
