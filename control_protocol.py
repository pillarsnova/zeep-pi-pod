"""Pure command validation for ZEEP device-control transports."""

from __future__ import annotations

from typing import Optional


AIRCON_FIXED_COMMANDS = frozenset({
    "on", "off", "fan", "swing_on", "swing_off",
    "light_on", "light_off", "status",
})
BED_COMMANDS = frozenset({
    "head_up", "head_down", "foot_up", "foot_down",
    "bed_stop", "flat", "center_all", "status",
})


def normalize_aircon_command(raw: str) -> str:
    command = " ".join((raw or "").strip().lower().split())
    if command in AIRCON_FIXED_COMMANDS:
        return command
    parts = command.split(" ")
    if len(parts) == 2 and parts[0] == "temp":
        try:
            temperature_c = int(parts[1])
        except ValueError:
            temperature_c = -1
        if 5 <= temperature_c <= 32:
            return f"temp {temperature_c}"
    raise ValueError(
        "คำสั่ง Air Con ไม่ถูกต้อง: ใช้ on, off, temp 5-32, fan, "
        "swing_on/off, light_on/off หรือ status"
    )


def apply_aircon_temperature_bias(
    command: str,
    *,
    desired_min_c: int,
    desired_max_c: int,
    bias_c: int,
) -> tuple[str, Optional[int], Optional[int]]:
    """Translate a user preference into the colder ESP32 IR setpoint."""
    if not command.startswith("temp "):
        return command, None, None
    desired = int(command.split(" ", 1)[1])
    if not desired_min_c <= desired <= desired_max_c:
        raise ValueError(
            f"อุณหภูมิที่ผู้ใช้เลือกต้องอยู่ระหว่าง "
            f"{desired_min_c}-{desired_max_c} °C"
        )
    commanded = desired + bias_c
    if not 5 <= commanded <= 32:
        raise RuntimeError("ค่า Air Con bias อยู่นอกช่วงคำสั่ง 5-32 °C")
    return f"temp {commanded}", desired, commanded


def normalize_bed_command(raw: str) -> str:
    command = (raw or "").strip().lower()
    if command not in BED_COMMANDS:
        raise ValueError(
            "คำสั่ง Bed ไม่ถูกต้อง: ใช้ head_up, head_down, foot_up, "
            "foot_down, bed_stop, flat, center_all หรือ status"
        )
    return command
