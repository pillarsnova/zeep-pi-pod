"""Pure command validation for ZEEP device-control transports."""

from __future__ import annotations

AIRCON_TEMPERATURE_MIN_C = 15
AIRCON_TEMPERATURE_MAX_C = 28
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
        if AIRCON_TEMPERATURE_MIN_C <= temperature_c <= AIRCON_TEMPERATURE_MAX_C:
            return f"temp {temperature_c}"
    raise ValueError(
        "คำสั่ง Air Con ไม่ถูกต้อง: ใช้ on, off, temp 15-28, fan, "
        "swing_on/off, light_on/off หรือ status"
    )


def resolve_aircon_temperature_command(
    command: str,
) -> tuple[str, int | None, int | None]:
    """Map the selected temperature to the same physical IR setpoint."""
    if not command.startswith("temp "):
        return command, None, None
    temperature_c = int(command.split(" ", 1)[1])
    if not AIRCON_TEMPERATURE_MIN_C <= temperature_c <= AIRCON_TEMPERATURE_MAX_C:
        raise ValueError(
            f"อุณหภูมิที่ผู้ใช้เลือกต้องอยู่ระหว่าง "
            f"{AIRCON_TEMPERATURE_MIN_C}-{AIRCON_TEMPERATURE_MAX_C} °C"
        )
    return f"temp {temperature_c}", temperature_c, temperature_c


def normalize_bed_command(raw: str) -> str:
    command = (raw or "").strip().lower()
    if command not in BED_COMMANDS:
        raise ValueError(
            "คำสั่ง Bed ไม่ถูกต้อง: ใช้ head_up, head_down, foot_up, "
            "foot_down, bed_stop, flat, center_all หรือ status"
        )
    return command
