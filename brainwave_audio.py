"""Versioned, speaker-compatible audio previews for the ZEEP Sound Lab.

The original browser prototype used binaural left/right carriers.  Binaural
beats depend on channel separation at the listener's ears, which the Pod's
loudspeaker cannot guarantee.  This module therefore renders subtle amplitude
modulation (AM), a warm harmonic pad, and decorrelated pink ambience to a
normal stereo WAV.  It is an experimental wellness stimulus, not a medical or
sleep-stage intervention.

Only Python's standard library is used so previews can be rendered locally on
the Raspberry Pi when the Internet is unavailable.
"""
from __future__ import annotations

import hashlib
import math
import random
import wave
from array import array
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Tuple


BRAINWAVE_AUDIO_VERSION = "zeep-speaker-sound-lab-v1.0"
SAMPLE_RATE = 24_000
CHANNELS = 2
SAMPLE_WIDTH_BYTES = 2
PEAK_LIMIT = 0.32
MIN_PREVIEW_SECONDS = 10
MAX_PREVIEW_SECONDS = 90


@dataclass(frozen=True)
class Phase:
    name: str
    weight: float
    carrier_hz: float
    modulation_hz: float
    modulation_depth: float
    noise_mix: float


@dataclass(frozen=True)
class Preset:
    preset_id: str
    name_th: str
    purpose_th: str
    evidence_label_th: str
    phases: Tuple[Phase, ...]


# Frequencies are design parameters, not claims that the loudspeaker forces
# brain activity to the same frequency.  The unmodulated control is essential
# for comparing the musical bed with and without rhythmic modulation.
PRESETS: Dict[str, Preset] = {
    "control-pink": Preset(
        "control-pink", "Control · Pink Ambience",
        "เสียงควบคุมสำหรับ A/B test · ไม่มี rhythmic modulation",
        "CONTROL",
        (Phase("control", 1.0, 174.0, 0.0, 0.0, 0.58),),
    ),
    "relax-alpha": Preset(
        "relax-alpha", "Relax · Alpha",
        "โทนอุ่นสำหรับทดสอบช่วงผ่อนคลายหรือสมาธิ",
        "EXPERIMENTAL",
        (Phase("alpha", 1.0, 196.0, 10.0, 0.16, 0.38),),
    ),
    "winddown-theta": Preset(
        "winddown-theta", "Wind-down · Theta",
        "บรรยากาศช้าสำหรับทดสอบช่วงเตรียมพัก",
        "EXPERIMENTAL",
        (Phase("theta", 1.0, 185.0, 6.0, 0.14, 0.44),),
    ),
    "nap-theta-alpha": Preset(
        "nap-theta-alpha", "Nap · Theta → Alpha",
        "สองช่วงสำหรับทดสอบพักสั้นและค่อย ๆ กลับมาตื่นตัว",
        "EXPERIMENTAL",
        (
            Phase("settle", 0.55, 185.0, 6.0, 0.14, 0.44),
            Phase("return", 0.45, 196.0, 9.0, 0.12, 0.38),
        ),
    ),
    "night-delta": Preset(
        "night-delta", "Night · Slow Pulse",
        "พัลส์ช้ามากสำหรับประเมินความไพเราะและการรบกวนก่อนนอน",
        "EXPERIMENTAL",
        (Phase("slow", 1.0, 164.0, 2.0, 0.10, 0.50),),
    ),
}


class PinkNoise:
    """Small deterministic Voss-McCartney pink-noise generator."""

    def __init__(self, seed: int, rows: int = 12) -> None:
        self.random = random.Random(seed)
        self.rows = [self.random.uniform(-1.0, 1.0) for _ in range(rows)]
        self.counter = 0

    def sample(self) -> float:
        self.counter += 1
        changed = (self.counter & -self.counter).bit_length() - 1
        if changed < len(self.rows):
            self.rows[changed] = self.random.uniform(-1.0, 1.0)
        return sum(self.rows) / len(self.rows)


def public_presets() -> Dict[str, Any]:
    """Return a stable, JSON-safe catalog without exposing implementation."""
    return {
        "version": BRAINWAVE_AUDIO_VERSION,
        "output": {
            "route": "Raspberry Pi local audio player",
            "format": f"stereo PCM WAV · {SAMPLE_RATE} Hz · 16-bit",
            "method": "speaker-compatible amplitude modulation",
            "peak_limit": PEAK_LIMIT,
        },
        "limits": {
            "duration_seconds": [MIN_PREVIEW_SECONDS, MAX_PREVIEW_SECONDS],
            "recommended_preview_volume_percent": 35,
            "physical_spl_requires_meter": True,
        },
        "presets": [
            {
                "id": preset.preset_id,
                "name": preset.name_th,
                "purpose": preset.purpose_th,
                "evidence": preset.evidence_label_th,
                "phases": [
                    {
                        "name": phase.name,
                        "weight": phase.weight,
                        "carrier_hz": phase.carrier_hz,
                        "modulation_hz": phase.modulation_hz,
                    }
                    for phase in preset.phases
                ],
            }
            for preset in PRESETS.values()
        ],
    }


def _phase_at(preset: Preset, progress: float) -> Tuple[Phase, Phase, float]:
    """Return current/next phase and a smooth interpolation at a boundary."""
    progress = max(0.0, min(1.0, progress))
    cumulative = 0.0
    for index, phase in enumerate(preset.phases):
        start = cumulative
        cumulative += phase.weight
        if progress <= cumulative or index == len(preset.phases) - 1:
            if index == len(preset.phases) - 1:
                return phase, phase, 0.0
            # Blend only over the final 12% of this phase.  Oscillator phases
            # themselves remain continuous in ``render_preview``.
            local = (progress - start) / max(phase.weight, 1e-9)
            blend = max(0.0, min(1.0, (local - 0.88) / 0.12))
            blend = blend * blend * (3.0 - 2.0 * blend)
            return phase, preset.phases[index + 1], blend
    return preset.phases[-1], preset.phases[-1], 0.0


def _lerp(a: float, b: float, amount: float) -> float:
    return a + ((b - a) * amount)


def _smooth_fade(frame_index: int, total_frames: int, fade_frames: int) -> float:
    edge = min(frame_index, max(0, total_frames - frame_index - 1))
    amount = max(0.0, min(1.0, edge / max(1, fade_frames)))
    return amount * amount * (3.0 - 2.0 * amount)


def _pcm_chunks(preset: Preset, duration_seconds: int) -> Iterable[array]:
    total_frames = duration_seconds * SAMPLE_RATE
    fade_frames = min(int(4.0 * SAMPLE_RATE), max(1, total_frames // 5))
    left_noise = PinkNoise(0x5A454550)
    right_noise = PinkNoise(0x504F4431)
    carrier_phase = 0.0
    modulation_phase = 0.0
    slow_phase = 0.0
    chunk = array("h")

    for frame in range(total_frames):
        progress = frame / max(1, total_frames - 1)
        phase, next_phase, blend = _phase_at(preset, progress)
        carrier_hz = _lerp(phase.carrier_hz, next_phase.carrier_hz, blend)
        modulation_hz = _lerp(
            phase.modulation_hz, next_phase.modulation_hz, blend
        )
        depth = _lerp(phase.modulation_depth, next_phase.modulation_depth, blend)
        noise_mix = _lerp(phase.noise_mix, next_phase.noise_mix, blend)

        # Keep this phase unwrapped: the 1.5× harmonic below would jump if a
        # wrapped fundamental phase reset at 2π.
        carrier_phase += math.tau * carrier_hz / SAMPLE_RATE
        if modulation_hz > 0.0:
            modulation_phase = (
                modulation_phase + (math.tau * modulation_hz / SAMPLE_RATE)
            ) % math.tau
            modulation = 1.0 - depth + depth * (0.5 + 0.5 * math.sin(modulation_phase))
        else:
            modulation = 1.0
        slow_phase = (slow_phase + (math.tau * 0.055 / SAMPLE_RATE)) % math.tau
        slow_drift = 0.94 + 0.06 * math.sin(slow_phase)

        # Warm, low-mid pad.  Small channel phase differences create width
        # without making headphone-only binaural separation a requirement.
        left_pad = (
            0.58 * math.sin(carrier_phase)
            + 0.18 * math.sin(carrier_phase * 1.5 + 0.35)
            + 0.09 * math.sin(carrier_phase * 2.0 + 0.12)
        )
        right_pad = (
            0.58 * math.sin(carrier_phase + 0.025)
            + 0.18 * math.sin(carrier_phase * 1.5 + 0.58)
            + 0.09 * math.sin(carrier_phase * 2.0 + 0.27)
        )
        tonal_mix = 1.0 - (noise_mix * 0.72)
        fade = _smooth_fade(frame, total_frames, fade_frames)
        left = (
            tonal_mix * left_pad * modulation * slow_drift
            + noise_mix * left_noise.sample()
        ) * PEAK_LIMIT * fade
        right = (
            tonal_mix * right_pad * modulation * slow_drift
            + noise_mix * right_noise.sample()
        ) * PEAK_LIMIT * fade
        chunk.extend((
            int(max(-1.0, min(1.0, left)) * 32767),
            int(max(-1.0, min(1.0, right)) * 32767),
        ))
        if len(chunk) >= 8192:
            yield chunk
            chunk = array("h")
    if chunk:
        yield chunk


def render_preview(
    preset_id: str, duration_seconds: int, output_dir: Path
) -> Dict[str, Any]:
    """Render one deterministic preview atomically and return audit metadata."""
    if preset_id not in PRESETS:
        raise ValueError("unknown_preset")
    duration_seconds = int(duration_seconds)
    if not MIN_PREVIEW_SECONDS <= duration_seconds <= MAX_PREVIEW_SECONDS:
        raise ValueError("duration_out_of_range")

    output_dir.mkdir(parents=True, exist_ok=True)
    safe_version = BRAINWAVE_AUDIO_VERSION.replace(".", "-")
    target = output_dir / f"{safe_version}-{preset_id}-{duration_seconds}s.wav"
    temporary = target.with_suffix(".tmp.wav")
    digest = hashlib.sha256()
    peak = 0
    sum_squares = 0
    sample_count = 0

    try:
        with wave.open(str(temporary), "wb") as output:
            output.setnchannels(CHANNELS)
            output.setsampwidth(SAMPLE_WIDTH_BYTES)
            output.setframerate(SAMPLE_RATE)
            for samples in _pcm_chunks(PRESETS[preset_id], duration_seconds):
                if samples.itemsize != SAMPLE_WIDTH_BYTES:
                    samples = array("h", samples)
                data = samples.tobytes()
                output.writeframesraw(data)
                digest.update(data)
                peak = max(peak, max(abs(value) for value in samples))
                sum_squares += sum(value * value for value in samples)
                sample_count += len(samples)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)

    rms = math.sqrt(sum_squares / max(1, sample_count)) / 32767.0
    return {
        "path": target,
        "file": target.name,
        "preset_id": preset_id,
        "version": BRAINWAVE_AUDIO_VERSION,
        "duration_seconds": duration_seconds,
        "sample_rate_hz": SAMPLE_RATE,
        "channels": CHANNELS,
        "peak": round(peak / 32767.0, 6),
        "rms": round(rms, 6),
        "pcm_sha256": digest.hexdigest(),
    }
