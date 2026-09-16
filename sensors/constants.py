"""Versioned constants shared by ZEEP sensor contracts and catalogs."""

SENSOR_CONTRACT_VERSION = "zeep-sensor-contract-v1.2"
TELEMETRY_SCHEMA = "zeep.sensor.telemetry"
TELEMETRY_SCHEMA_VERSION = "1.0"

# Only this event may replace live Sensor Hub state. Boot, command and
# calibration replies share the transport but are not measurements.
ENVIRONMENT_EVENT = "environment"
LEGACY_HUB1_MEASUREMENT_FIELDS = frozenset(
    {
        "temperature_c",
        "temperature",
        "temp",
        "temp_c",
        "humidity_rh",
        "humidity",
        "hum",
        "rh",
        "lux",
        "light",
        "illuminance",
    }
)

# ESP32 ``sound_dba`` values outside this interval are unavailable rather than
# clamped. One definition prevents API, Dashboard and Session drift.
SOUND_DBA_DISPLAY_MIN = 30.0
SOUND_DBA_DISPLAY_MAX = 130.0
SOUND_SENSOR_MODEL = "SPH0645LM4H-B"


__all__ = (
    "ENVIRONMENT_EVENT",
    "LEGACY_HUB1_MEASUREMENT_FIELDS",
    "SENSOR_CONTRACT_VERSION",
    "SOUND_DBA_DISPLAY_MAX",
    "SOUND_DBA_DISPLAY_MIN",
    "SOUND_SENSOR_MODEL",
    "TELEMETRY_SCHEMA",
    "TELEMETRY_SCHEMA_VERSION",
)
