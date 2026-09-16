"""Static device metadata and canonical environment field ownership."""

from __future__ import annotations

from typing import Any

from sensors.constants import (
    SOUND_DBA_DISPLAY_MAX,
    SOUND_DBA_DISPLAY_MIN,
    SOUND_SENSOR_MODEL,
)

SENSOR_CATALOG: dict[str, dict[str, Any]] = {
    "sht3x_dis": {
        "model": "SHT3x-DIS",
        "hub": "sensorhub1",
        "transport": "usb_serial_jsonl",
        "manufacturer": {
            "supply_v": [2.15, 5.5],
            "interface": "I2C",
            "addresses_hex": ["0x44", "0x45"],
            "temperature_range_c": [-40, 125],
            "humidity_range_rh": [0, 100],
            "note": "Accuracy depends on exact SHT30/SHT31/SHT35 ordering code; inspect package/BOM before freezing accuracy.",
        },
        "datasheet": "https://sensirion.com/media/documents/213E6A3B/63A5A569/Datasheet_SHT3x_DIS.pdf",
        "fields": ["temperature_c", "humidity_rh"],
        "health_use": "environment_context_and_safety",
    },
    "opt3001": {
        "model": "OPT3001",
        "hub": "sensorhub1",
        "transport": "usb_serial_jsonl",
        "manufacturer": {
            "supply_v": [1.6, 3.6],
            "interface": "I2C/SMBus",
            "addresses_hex": ["0x44", "0x45", "0x46", "0x47"],
            "measurement_range_lux": [0.01, 83865.6],
            "typical_ir_rejection_pct": 99,
        },
        "datasheet": "https://www.ti.com/lit/ds/symlink/opt3001.pdf",
        "fields": ["lux"],
        "health_use": "environment_context_and_safety",
    },
    "sph0645": {
        "model": SOUND_SENSOR_MODEL,
        "hub": "sensorhub1",
        "transport": "usb_serial_jsonl",
        "manufacturer": {
            "interface": "I2S PCM",
            "nominal_snr_dba": 65,
            "bandwidth_hz": 18000,
            "typical_current_ua": 600,
            "note": "The microphone outputs digital PCM. Sensor Hub 1 owns its processing and publishes the operational sound_dba value consumed by the Pi.",
        },
        "datasheet": "https://www.knowles.com/docs/default-source/model-downloads/sph0645lm4h-b-datasheet-rev-c.pdf",
        "fields": ["sound_dba", "sound_dbfs"],
        "zeep_processing": {
            "owner": "sensorhub1_firmware",
            "source_field": "sound_dba",
            "pi_transform": "none",
            "accepted_display_range_dba": [
                SOUND_DBA_DISPLAY_MIN,
                SOUND_DBA_DISPLAY_MAX,
            ],
            "legacy_dbfs_policy": "invalid",
            "pi_abs_transform_allowed": False,
        },
        "health_use": "environment_context_and_corroborated_arousal_only",
    },
    "mhz19c": {
        "model": "MH-Z19C",
        "hub": "sensorhub2",
        "transport": "mqtt_json",
        "manufacturer": {
            "supply_v": [4.9, 5.1],
            "interface": "UART 3.3V TTL / PWM",
            "selectable_ranges_ppm": [[400, 2000], [400, 5000], [400, 10000]],
            "resolution_ppm": 1,
            "accuracy": "±(50 ppm + 5% of reading)",
            "preheat_s": 60,
            "response_t90_s_max": 120,
            "average_current_ma_max": 40,
            "peak_current_ma": 125,
        },
        "datasheet": "https://www.winsen-sensor.com/d/files/manual/mh-z19c.pdf",
        "fields": ["co2_ppm"],
        "health_use": "environment_context_and_safety",
    },
    "pms7003": {
        "model": "PMS7003",
        "hub": "sensorhub2",
        "transport": "mqtt_json",
        "manufacturer": {
            "supply_v": [4.5, 5.5],
            "interface_level_v": 3.3,
            "effective_pm25_range_ug_m3": [0, 500],
            "maximum_pm25_range_ug_m3": 1000,
            "resolution_ug_m3": 1,
            "single_response_s_max": 1,
            "total_response_s_max": 10,
            "active_current_ma_max": 100,
            "note": "Freeze the internal UART baud/frame/checksum only against the vendor data manual shipped with the purchased lot.",
        },
        "datasheet": "https://plantower.com/en/products_33/76.html",
        "fields": ["pm1_0_ug_m3", "pm2_5_ug_m3", "pm10_ug_m3"],
        "health_use": "environment_context_and_safety",
    },
    "sgp40": {
        "model": "SGP40",
        "hub": "sensorhub2",
        "transport": "mqtt_json",
        "manufacturer": {
            "supply_v": [1.7, 3.6],
            "interface": "I2C",
            "average_current_ma": 2.6,
            "voc_index_range": [1, 500],
            "algorithm_sample_period_s": 1,
            "baseline_reference": "VOC Index 100 represents average indoor gas composition over the preceding 24 h",
        },
        "datasheet": "https://sensirion.com/media/documents/296373BB/6203C5DF/Sensirion_Gas_Sensors_Datasheet_SGP40.pdf",
        "fields": ["sgp40_raw", "voc_index"],
        "health_use": "environment_context_and_safety",
    },
    "lsm800t": {
        "model": "LSM-800-T",
        "hub": "pi5",
        "transport": "usb_serial_binary",
        "manufacturer": {
            "principle": "piezoresistive presence + piezoelectric vital signal",
            "output": "UART",
            "public_product_page": "https://film-sensor.com/smart-sleep-monitoring/",
        },
        "zeep_transport": {
            "status": "verified_on_deployed_hardware_and_published_protocol_description",
            "baud": 115200,
            "frame_bytes": 66,
            "waveform_header_ascii": "Odata",
            "waveform_samples": 25,
            "sample_encoding": "signed int16 little-endian",
            "waveform_sample_rate_hz": 25,
            "result_header_ascii": "Bdata",
            "packet_id_offset": 62,
            "status_offset": 63,
            "heart_rate_offset": 64,
            "respiration_raw_offset": 65,
            "respiration_scale": 0.1,
            "note": "This byte map is the ZEEP as-built interface contract, not a claim of a publicly released manufacturer datasheet.",
        },
        "datasheet": "https://film-sensor.com/smart-sleep-monitoring/",
        "fields": ["bcg_samples", "bed_status", "heart_rate_bpm", "respiration_rate"],
        "health_use": "primary_wellness_sleep_evidence_not_psg",
    },
}


ENVIRONMENT_DEVICE_SPECS: dict[str, dict[str, Any]] = {
    "sht3x_dis": {
        "model": "SHT3x-DIS",
        "sources": ("hub1",),
        "status": ("sht3x_dis", "sht31", "sht3x"),
        "fields": {
            "temperature_c": (
                ("temperature", "temperature_c", "temp", "temp_c"),
                -40,
                125,
            ),
            "humidity_rh": (("humidity", "humidity_rh", "hum", "rh"), 0, 100),
        },
    },
    "opt3001": {
        "model": "OPT3001",
        "sources": ("hub1",),
        "status": ("opt3001",),
        "fields": {"lux": (("lux", "illuminance", "light"), 0, 83865.6)},
    },
    "sph0645": {
        "model": SOUND_SENSOR_MODEL,
        "sources": ("hub1",),
        "status": ("sph0645",),
        "fields": {
            "sound_dba_est": (
                ("sound_dba_est",),
                SOUND_DBA_DISPLAY_MIN,
                SOUND_DBA_DISPLAY_MAX,
            ),
        },
    },
    "mhz19c": {
        "model": "MH-Z19C",
        "sources": ("hub2", "hub1"),
        "status": ("mhz19c", "mh_z19c"),
        # The installed Hub 2 is configured for the 400–5000 ppm option.
        "fields": {"co2_ppm": (("co2_ppm", "co2", "carbon_dioxide"), 400, 5000)},
    },
    "pms7003": {
        "model": "PMS7003",
        "sources": ("hub2", "hub1"),
        "status": ("pms7003", "pms5003"),
        "fields": {
            "pm1_0_ug_m3": (
                ("pm1_0_ug_m3", "pm1_0_atm", "pm1_atm", "pm1_0", "pm1"),
                0,
                1000,
            ),
            "pm2_5_ug_m3": (
                ("pm2_5_ug_m3", "pm2_5_atm", "pm25_atm", "pm2_5", "pm25"),
                0,
                1000,
            ),
            "pm10_ug_m3": (("pm10_ug_m3", "pm10_atm", "pm10"), 0, 1000),
        },
    },
    "sgp40": {
        "model": "SGP40",
        "sources": ("hub2", "hub1"),
        "status": ("sgp40",),
        "fields": {
            "voc_index": (("voc_index", "vocIndex", "sgp40_voc_index"), 1, 500),
            "sgp40_raw": (
                ("sgp40_raw", "sraw_voc", "voc_raw", "sgp40_sraw_voc"),
                0,
                65535,
            ),
        },
    },
}


__all__ = ("ENVIRONMENT_DEVICE_SPECS", "SENSOR_CATALOG")
