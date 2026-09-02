# SPH0645 ↔ CEM DT-8852 field comparison — 2026-08-26

> **Document status: historical evidence / superseded for runtime.** ตั้งแต่
> 2026-09-02 ระบบใช้ Field Trial display transform:
> `magnitude = round(abs(sound_dbfs), 1)` และ
> `dBA_est = magnitude × (1 - 3/100)`. ตัวอย่าง raw `-39.69 dBFS` แสดงเป็น
> `38.51 dBA est.` สูตร offset และค่าที่บันทึกด้านล่างเป็น
> ลำดับเหตุการณ์เดิมสำหรับ Audit เท่านั้น ไม่ใช่ Runtime configuration ปัจจุบัน
> และค่าปัจจุบันยังไม่ใช่ traceable SPL calibration.

## Decision

Do **not** derive a gain/slope or replace the current production offset from
these photographs alone. The reference meter was set to its `50–100 dBA`
range. Readings below 50 dBA show `UNDER` and are outside that selected range.
The seven in-range pairs cover only 2.9 dB on the reference meter and have no
useful linear relationship (`R² ≈ 0.001`).

The dashboard photographs were taken around 01:15–01:23 while the earlier
offset (`87.15`) was active. They must not receive any later field correction
a second time. The production offset was subsequently changed to `83.15`, then
to `82.65` after an additional `−0.5 dB` field request.

On 2026-08-27 the field team reported that the live ZEEP Sensor was reading
`5–8 dBA` above the CEM meter in the current Pod condition. Because only a
range—not synchronized five-second Leq pairs—was available, the midpoint
correction `−6.5 dB` was applied provisionally to the previous `82.65` offset.
The offset became `76.15`.

Later on 2026-08-27 a new simultaneous field observation reported CEM
`45 dBA` versus ZEEP `56 dBA`. Inspection found that `−11.0 dB` had been
written only as descriptive metadata and was never part of the runtime
formula. The effective offset was temporarily reduced from `76.15` to `65.15`.

The follow-up images `62912`, `62926`, and `62928` then showed that the CEM was
still set to its `50–100 dBA` range. The `45.9` and `47.0 dBA` readings display
`UNDER` and are invalid calibration points. The only in-range pair was ZEEP
`55.7` versus CEM `53.2 dBA`, a `+2.5 dB` difference that is not sufficient to
justify a write because the CEM was on FAST while ZEEP publishes a five-second
energy average. The `−11 dB` change was therefore rolled back. At that step the
runtime formula returned to `dBA_est = sound_dbfs + 76.15` pending a synchronized
`A/SLOW · LO 30–80 dBA` retest. Admin Packet Inspector must continue to show
both raw dBFS and the calibrated five-second estimate.

The later operational trim used the only in-range follow-up pair to reduce the
offset from `76.15` to `73.65`. On 2026-08-27 at 05:51 Asia/Bangkok, the
operator then explicitly requested another `-10.0 dB` display correction. The
active Pod offset is therefore `63.65`. This is recorded as a manual operational
trim, not a traceable calibration result: raw `dBFS` is unchanged and the
required synchronized `A/SLOW · LO 30–80 dBA` retest remains open.

After a further field check on 2026-08-27 at 07:47 Asia/Bangkok, the operator
confirmed that the displayed estimate needed `+1.0 dBA`. The production offset
was therefore increased from `63.65` to `64.65`. This correction applies once
in the canonical `dBA_est = sound_dbfs + offset` conversion and took effect for
new samples after the service resumed at 07:48:23. Earlier Session rows were
not changed by this adjustment.

At the operator's follow-up request, the same `−10.0 dB` delta was backfilled
only into the active Session `s-20260826T215053Z-849f26` for records before
05:51:53 Asia/Bangkok. The migration updated 725 timeline rows and 720 matching
sleep-stage acoustic-evidence events; no other Session was modified. The
database ledger key prevents the correction from being applied twice, and the
pre-migration database is retained as
`backup/sessions-pre-current-sound-recal-20260827-055830.db` on the Pod.

| Follow-up image | ZEEP (dBA) | CEM (dBA) | CEM state | Decision |
|---|---:|---:|---|---|
| 62912 | 55.7 | 53.2 | In selected range | Audit only; FAST vs 5-second Leq |
| 62926 | 56.3 | 45.9 | UNDER | Reject |
| 62928 | 55.9 | 47.0 | UNDER | Reject |

The field-photo result is retained as a provisional high-level observation:
within the valid 50–100 dBA meter range, `Meter − Dashboard` has median
`+3.7 dB` and mean `+3.9 dB`. It conflicts with the later sleep-level field trim
near 31–32 dBA, which is evidence that the test timing/range must be fixed
before another production calibration is written.

## Extracted pairs

| Image suffix | Dashboard SPH0645 (dBA) | CEM DT-8852 (dBA) | Meter state | Use |
|---|---:|---:|---|---|
| 84265 | 43.8 | 52.1 | in range | yes |
| 84266 | 50.1 | 51.9 | in range | yes |
| 84267 | 49.2 | 52.9 | in range | yes |
| 84268 | 47.4 | 52.2 | in range | yes |
| 84269 | 48.8 | 50.0 | boundary | yes |
| 84270 | 48.5 | 52.0 | in range | yes |
| 84276 | 4.0 | 46.3 | UNDER | no — sensor transient/dropout |
| 84277 | 49.6 | 46.4 | UNDER | no |
| 84278 | 45.1 | 46.3 | UNDER | no |
| 84279 | 48.0 | 46.5 | UNDER | no |
| 84282 | 48.0 | 47.1 | UNDER | no |
| 84283 | 47.1 | 46.9 | UNDER | no |
| 84285 | 49.1 | 49.9 | UNDER | no |
| 84286 | 46.5 | 50.5 | in range | yes |

Images 84275 and 84284 show the air conditioner only. Images 84295–84308
either overexpose or crop the Dashboard sound value and are not transcribed.

### Statistics for the seven in-range pairs

- Dashboard range: 43.8–50.1 dBA
- Meter range: 50.0–52.9 dBA
- Median paired correction (`Meter − Dashboard`): +3.7 dB
- Mean paired correction: +3.9 dB
- MAE after a +3.7 dB offset: 1.51 dB
- RMSE after a +3.7 dB offset: 2.15 dB
- Linear-fit `R²`: 0.00094 — insufficient for gain calibration

The snapshots compare a five-second Dashboard analysis frame against the
meter's FAST (125 ms) display, so even an otherwise valid pair is not a
synchronized average.

## Required retest protocol

1. Set the CEM to **A weighting**, **SLOW**, and `LO 30–80 dBA` (or AUTO).
   Never record a row while `UNDER` or `OVER` is visible.
2. Place the CEM microphone and the SPH0645 acoustic port within 2–5 cm of
   each other, with the same orientation. Keep both away from the tablet,
   wall, air outlet, fabric, and operator.
3. Use stable broadband/pink noise at approximately 35, 40, 50, 60, and
   70 dBA. Hold every level for at least 30 seconds.
4. Record six consecutive five-second blocks per level. Compare the Pod's
   five-second energy average with a matching logged meter average, not a
   photograph of a FAST instantaneous value.
5. Fit gain only when the valid reference span is at least 20 dB and the
   relationship is monotonic with `R² ≥ 0.95`. Otherwise use a one-point
   offset in the operational sleep band (35–45 dBA).
6. Recheck the zero/quiet condition and confirm that a single low transient
   does not become an automation input. Values below 0 remain invalid; valid
   non-negative values may still be displayed as required.

## Reference specifications

- CEM DT-8851/8852: IEC 61672-1 Class 2, accuracy ±1.4 dB, ranges
  LO 30–80 / MED 50–100 / HI 80–130 / AUTO 30–130 dB, FAST 125 ms and
  SLOW 1 s: <https://www.cem-instruments.com/en/product-id-1294>
- Knowles SPH0645LM4H-B: typical sensitivity −26 dBFS at 94 dB SPL, ±3 dB
  sensitivity spread, 65 dBA SNR and 120 dB SPL acoustic overload point:
  <https://www.knowles.com/docs/default-source/model-downloads/sph0645lm4h-b-datasheet-rev-c.pdf>

The SPH0645 is a MEMS microphone, not a complete IEC sound-level meter. A
traceable dBA result also depends on the firmware's RMS calculation, frequency
weighting, time weighting, enclosure/port response, and per-unit calibration.
