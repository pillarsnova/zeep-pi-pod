#!/usr/bin/env bash
# Canonical entry point for an approved ZEEP development workstation.
set -euo pipefail
cd "$(dirname "$0")"

echo "[start-work] ตรวจสิทธิ์เครื่องและ disk encryption"
python3 sync_pod_data.py --check-approval "$@"

echo "[start-work] ดึง code ล่าสุดจาก origin/develop"
code_is_current=true
current_branch="$(git branch --show-current)"
if [[ "$current_branch" != "develop" ]]; then
  echo "[start-work] ต้องเริ่มจาก branch develop · พบ $current_branch"
  exit 1
fi
if git fetch origin develop; then
  git merge --ff-only origin/develop
else
  code_is_current=false
  echo "[start-work] ติดต่อ origin/develop ไม่สำเร็จ · จะลองดึงข้อมูลจาก POD ต่อ"
fi

echo "[start-work] สร้าง snapshot ข้อมูลล่าสุดจาก POD"
if ! python3 sync_pod_data.py "$@"; then
  if python3 sync_pod_data.py --check-latest "$@"; then
    echo "[start-work] ใช้ snapshot ที่ตรวจผ่านล่าสุดชั่วคราว · ข้อมูลอาจไม่ใช่ปัจจุบัน"
  else
    echo "[start-work] ยังไม่มี snapshot ที่ตรวจผ่าน จึงไม่พร้อมวิเคราะห์ข้อมูล POD"
    exit 1
  fi
fi

if [[ "$code_is_current" != true ]]; then
  echo "[start-work] พร้อมทำงานแบบ Offline · code อาจไม่ใช่รุ่นล่าสุด"
fi

echo "[start-work] พร้อมทำงาน · ใช้ตำแหน่ง snapshot ที่รายงานในผล JSON ด้านบน"
