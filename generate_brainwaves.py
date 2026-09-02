#!/usr/bin/env python3
"""Generate layered wellness audio for the ZEEP Pod local player.

ชุดเสียงออกแบบสำหรับ "ลำโพง" โดยเฉพาะ — ไม่มี binaural (ไม่ต้องใช้หูฟัง):
ทุกเพลงเป็นการผสมหลายย่านเสียง (multi-band mix) บนพื้น pink noise นุ่ม ๆ
โทนต่ำฝังอยู่ข้างในและแกว่งช้า ๆ ตามย่าน delta/theta/alpha → เสียงสม่ำเสมอ
ตลอดทั้งไฟล์ ไม่มีช่วงเงียบ-ดังสะดุด เหมาะกับการเปิดต่อเนื่องขณะนอน

  python3 generate_brainwaves.py            # 10-minute files (default)
  python3 generate_brainwaves.py --minutes 30

5 รูปแบบ: กลางดึก (delta) · ก่อนนอน (theta) · งีบสั้น (theta-alpha) ·
ผ่อนคลาย (alpha) · ฝนพรำ (noise ambience)

Claims boundary (ZEEP wellness-not-medical): เพลงตั้งชื่อตามบริบทการใช้และ
ความถี่ modulation — ไม่เคลมผลการนอนหรือผลทางสรีรวิทยา
(docs/brainwave-sound-lab-v1.md)
และระดับเสียงกลางคืนเป้าหมาย ≤ 35 dB(A) — Python stdlib ล้วน รันบน Pi ได้เลย
"""
import argparse
import array
import math
import random
import wave
from pathlib import Path

RATE = 22050
AMP = 0.30          # peak amplitude (~ -10 dBFS) — เบาโดยตั้งใจ
FADE_S = 8.0        # fade-in/out กันเสียงกระตุกตอนเริ่ม/จบ (และตอน loop)
TWO_PI = 2.0 * math.pi


def swell(freq_hz: float, t: float, floor: float = 0.0, phase: float = 0.0) -> float:
    """คลื่นแกว่ง 0..1 แบบ raised-cosine — นุ่ม ไม่มีคลิก; floor กันเงียบสนิท."""
    return floor + (1.0 - floor) * 0.5 * (1.0 - math.cos(TWO_PI * freq_hz * t + phase))


class PinkNoise:
    """Voss-McCartney pink noise (8 rows), ค่าประมาณ -1..1."""

    def __init__(self, rows: int = 8, seed: int = 20260803):
        self.rng = random.Random(seed)
        self.rows = [self.rng.uniform(-1, 1) for _ in range(rows)]
        self.counter = 0

    def next(self) -> float:
        self.counter += 1
        c = self.counter
        for i in range(len(self.rows)):
            if c % (1 << i) == 0:
                self.rows[i] = self.rng.uniform(-1, 1)
        return sum(self.rows) / len(self.rows)


def write_wav(path: Path, seconds: float, sample_lr):
    """sample_lr(t, i) -> (left, right) floats in -1..1."""
    n = int(seconds * RATE)
    fade_n = int(FADE_S * RATE)
    data = array.array("h")
    for i in range(n):
        t = i / RATE
        left, right = sample_lr(t, i)
        env = 1.0
        if i < fade_n:
            env = i / fade_n
        elif i > n - fade_n:
            env = (n - i) / fade_n
        scale = 32767 * AMP * env
        data.append(int(max(-1.0, min(1.0, left)) * scale))
        data.append(int(max(-1.0, min(1.0, right)) * scale))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(data.tobytes())
    print(f"  wrote {path.name} ({path.stat().st_size / 1e6:.1f} MB)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--minutes", type=float, default=10.0)
    parser.add_argument("--outdir", default=str(Path(__file__).parent / "music"))
    args = parser.parse_args()
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    seconds = args.minutes * 60.0

    print(f"Generating {args.minutes:g}-minute layered sleep-audio set at {RATE} Hz …")
    # เสียงซ้าย/ขวาใช้ noise คนละชุด (decorrelated) → กว้างและเป็นธรรมชาติผ่านลำโพง
    # ส่วน "โทน" เหมือนกันสองข้างเสมอ — ไม่มี binaural beat จึงไม่ต้องใช้หูฟัง

    # 1) กลางดึก · Night — delta band 2 Hz
    #    pink noise + โทนต่ำ 100 Hz แกว่งช้า + ความอุ่น 55 Hz จาง ๆ
    pnL, pnR = PinkNoise(seed=11), PinkNoise(seed=12)
    def night(t, i):
        gate = swell(2.0, t, floor=0.35)          # ไม่มีช่วงเงียบสนิท = สม่ำเสมอ
        drift = swell(0.05, t, floor=0.75)        # ลมหายใจช้า ๆ ของพื้นเสียง
        tone = 0.30 * math.sin(TWO_PI * 100 * t) * gate \
             + 0.14 * math.sin(TWO_PI * 55 * t) * gate
        return (0.55 * pnL.next() * drift + tone,
                0.55 * pnR.next() * drift + tone)
    write_wav(outdir / "Sleep-01-Night-Delta-Mix.wav", seconds, night)

    # 2) ก่อนนอน · Wind-down — theta band 6 Hz + คลื่นทะเลช้า
    pnL, pnR = PinkNoise(seed=21), PinkNoise(seed=22)
    def winddown(t, i):
        gate = swell(6.0, t, floor=0.40)
        sea = swell(0.08, t, floor=0.60)          # swell ยาว ~12 วิ คล้ายคลื่น
        tone = 0.26 * math.sin(TWO_PI * 150 * t) * gate \
             + 0.12 * math.sin(TWO_PI * 90 * t) * sea
        return (0.50 * pnL.next() * sea + tone,
                0.50 * pnR.next() * sea + tone)
    write_wav(outdir / "Sleep-02-WindDown-Theta-Mix.wav", seconds, winddown)

    # 3) งีบสั้น · Nap — theta-alpha 8 Hz โทนสว่างขึ้นเล็กน้อย
    pnL, pnR = PinkNoise(seed=31), PinkNoise(seed=32)
    def nap(t, i):
        gate = swell(8.0, t, floor=0.45)
        drift = swell(0.06, t, floor=0.80)
        tone = 0.28 * math.sin(TWO_PI * 170 * t) * gate \
             + 0.10 * math.sin(TWO_PI * 255 * t) * swell(8.0, t, floor=0.45, phase=math.pi)
        return (0.45 * pnL.next() * drift + tone,
                0.45 * pnR.next() * drift + tone)
    write_wav(outdir / "Sleep-03-Nap-ThetaAlpha-Mix.wav", seconds, nap)

    # 4) ผ่อนคลาย · Relax — alpha 10 Hz คู่เสียง perfect fifth (132+198 Hz)
    pnL, pnR = PinkNoise(seed=41), PinkNoise(seed=42)
    def relax(t, i):
        gate = swell(10.0, t, floor=0.45)
        tone = 0.24 * math.sin(TWO_PI * 132 * t) * gate \
             + 0.16 * math.sin(TWO_PI * 198 * t) * gate
        return (0.42 * pnL.next() + tone,
                0.42 * pnR.next() + tone)
    write_wav(outdir / "Sleep-04-Relax-Alpha-Mix.wav", seconds, relax)

    # 5) ฝนพรำ · Rain — noise ambience ล้วน แกว่งช้าสองชั้น (ไม่มีโทน)
    pnL, pnR = PinkNoise(seed=51), PinkNoise(seed=52)
    def rain(t, i):
        wash = swell(0.07, t, floor=0.70) * swell(0.031, t, floor=0.85)
        return (0.95 * pnL.next() * wash,
                0.95 * pnR.next() * wash)
    write_wav(outdir / "Sleep-05-Rain-Pink-Mix.wav", seconds, rain)

    print("Done. ทุกไฟล์เล่นผ่านลำโพงได้ — ไม่ต้องใช้หูฟัง · แสดงในหน้าจออัตโนมัติ")


if __name__ == "__main__":
    main()
