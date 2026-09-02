#!/usr/bin/env bash
# ZEEP Pod dashboard — one-command bootstrap.
# ใช้ได้ทั้ง Raspberry Pi OS / macOS / Linux:  ./run.sh
# ตัวเลือกผ่าน env:  PORT=8080 ./run.sh · SKIP_MUSIC=1 · BRAINWAVE_MINUTES=30 · API_TOKEN=xxx
set -e
cd "$(dirname "$0")"

command -v python3 >/dev/null 2>&1 || { echo "[error] ต้องติดตั้ง python3 ก่อน"; exit 1; }

if [ ! -d .venv ]; then
  echo "[setup] สร้าง virtualenv ครั้งแรก…"
  # --system-site-packages ทำให้เห็น python3-lgpio ของระบบบน Raspberry Pi
  python3 -m venv --system-site-packages .venv
fi
# shellcheck disable=SC1091
. .venv/bin/activate
pip install -q --disable-pip-version-check -r requirements.txt

# สร้างเสียง brainwave ครั้งแรก (ข้ามด้วย SKIP_MUSIC=1)
if [ "${SKIP_MUSIC:-0}" != "1" ] && ! ls music/*.wav >/dev/null 2>&1; then
  echo "[setup] กำลังสร้างไฟล์เสียง brainwave (ครั้งเดียว ~1 นาที)…"
  python generate_brainwaves.py --minutes "${BRAINWAVE_MINUTES:-10}"
fi

if ! command -v mpv >/dev/null 2>&1 && ! command -v afplay >/dev/null 2>&1 \
   && ! command -v ffplay >/dev/null 2>&1; then
  echo "[warn] ไม่พบโปรแกรมเล่นเสียง (mpv/afplay/ffplay) — dashboard ใช้ได้แต่เล่นเสียงไม่ได้"
  echo "       Pi/Linux: sudo apt install -y mpv · macOS: brew install mpv"
fi

echo "[run] เปิดจากแท็บเล็ต/เบราว์เซอร์:  http://<ip-เครื่องนี้>:${PORT:-8000}"
exec python app.py
