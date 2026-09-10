# ZEEP Pi 5 Code Architecture

Status: active migration guide  
Owner: Pi 5 application team  
Last updated: 2026-09-11

## Purpose

The Pi process controls safety-relevant hardware and records wellness data.
Refactoring therefore uses small, test-backed steps instead of a one-time
rewrite. `app.py` is temporarily retained as the process composition root so
the systemd entry point and existing API remain stable.

## Package layout

```text
zeep_pod/
├── hardware/
│   ├── audio.py          # MPV/afplay/ffplay playback adapter
│   └── gpio.py           # fail-closed physical GPIO outputs
├── identity/
│   ├── profile_fields.py # account/profile/health field normalization
│   └── zeep_account.py   # bind a ZEEP {tokens, user} payload to local identity
└── sessions/
    ├── cadence.py        # mixed 5/10-second timeline normalization
    ├── lifecycle.py      # checkpoint, bed occupancy and HR/RR start gate
    ├── report_share.py   # end-of-Session QR share: ticket, upload, QR code
    ├── history_service.py # filtered completed-Session read model
    ├── restore_summary*.py # non-scoring explanation + Personal Baseline
    ├── result_contract.py # versioned, raw-free result DTO
    ├── usage_service.py  # app-facing result orchestration
    └── usage_api.py      # authenticated `/api/v1/usage-sessions` routes
```

`sessions/report_share.py` follows the same secret discipline as `qr_login.py`.
The tablet cannot reach the ZEEP API from the pod hotspot, so it renders the
finished night as a PNG and the Pi uploads it to the account backend with the
occupant's own access token; that token stays in process memory and never
reaches the browser, the database or the log. The browser authorizes the
upload with a single-use ticket because its cookie is already revoked by then.
The whole feature is behind `SESSION_REPORT_SHARE_ENABLED`, off by default, and
no registry method raises — finalizing a Session must never fail because of a
share.

Existing domain modules at the repository root remain supported while they
are migrated. Their current responsibilities are:

- `sleep_signal_features.py`: BCG, movement, arousal and occupancy features.
- `sleep_stage_scoring.py`: W/N1/N2/N3/REM evidence scores.
- `sleep_system_policy.py`: versioned thresholds and transition policy.
- `sleep_session_report.py`: final Sleep/Recovery reports.
- `sensor_contracts.py`: wire formats and device contracts.
- `sensor_runtime.py`: environment normalization; copies a finite, in-range
  ESP32 `sound_dba` directly and never converts dBFS to dBA.
- `access_control.py` and `pod_occupancy.py`: browser identity and Pod lease.
- `qr_login.py`: QR login handshake. The tablet cannot reach the ZEEP API
  from the pod hotspot, so the Pi proxies it and keeps `pollSecret` in
  process memory — it never reaches the browser, the QR image or the log.
- `database.py` and `bcg_storage.py`: persistence boundaries.

## Dependency rule

`app.py` may import domain packages. Domain packages must never import
`app.py`. Hardware objects receive shared state explicitly rather than reaching
back into global application state. Pure helpers do not open files, sockets,
serial ports, GPIO or databases at import time.

## Coding standard

- Python 3.11 syntax and PEP 8 conventions.
- Ruff is the canonical formatter and static checker for `zeep_pod/`.
- New package files are limited to 500 lines.
- Functions and methods are limited to 90 lines.
- Public functions, classes and non-obvious safety decisions require docstrings.
- Type hints are required at module boundaries.
- Wildcard imports and imports from `app.py` are prohibited.
- Hardware operations fail closed; tests may inject fakes explicitly.
- Raw health/Sensor data is not mutated by presentation code.
- A behavior move retains a compatibility facade until callers and historical
  tools have migrated.

These limits are enforced by `test_modular_architecture.py` and the Python
quality workflow. The legacy root has a no-growth ceiling of 8,800 lines and
must shrink at each extraction phase.

## Migration sequence

1. **Completed in Phase 1:** Session cadence, profile normalization, GPIO and
   audio runtime extracted with API compatibility.
2. **Phase 2 — in progress:** checkpoint persistence, Bed Status and the fresh
   HR/RR recording gate live in `sessions/lifecycle.py`; Usage History,
   Restore Summary และ API result contract แยกออกจาก composition root แล้ว
   ขั้นถัดไปคือย้าย start/finalize/restore orchestration และ account ingest
   หลัง database, occupancy และ logging ports ที่ inject ได้
3. **Phase 3:** move ESP32, MQTT and BCG readers into `sensors/` services.
4. **Phase 4:** move air-conditioner, bed and accessory commands into
   `controls/` services.
5. **Phase 5:** split FastAPI endpoints into `api/` routers and reduce `app.py`
   to construction, dependency wiring and lifecycle startup/shutdown.

Every phase must pass the full regression suite on a workstation and a Pi
smoke test before the service is restarted.
