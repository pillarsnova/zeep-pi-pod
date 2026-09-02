# ZEEP Sleep Platform V2 Migration

## Before upgrading

1. Stop the existing service and copy the entire `data/` directory somewhere safe.
2. Install the updated source without deleting `data/sessions.jsonl`.
3. Ensure the service user can write to `data/` and `backup/`.

## First start

At startup the application creates `data/sessions.db` and `data/bcg.db`. If
`data/sessions.jsonl` exists, every legacy session and timeline sample is
imported in one SQLite transaction. Only after a successful import is the file
renamed to `sessions.jsonl.bak`; it is never deleted. A malformed source is left
untouched and the error is printed to the service log.

Legacy recordings contain HR/RR and environmental samples only. Raw BCG data
cannot be reconstructed and is available only for sessions recorded on V2.

## Verification

Check `GET /api/state` and confirm `database.running` is true and
`database.last_error` is null. Compare the History session count with the old
dashboard, open a migrated detail report, then record and export a short new
session before starting an overnight recording.

## systemd

Copy `zeep-pod.service` to `/etc/systemd/system/`, adjust `User`,
`WorkingDirectory`, and `ExecStart` if needed, then run:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now zeep-pod.service
sudo systemctl status zeep-pod.service
```

Daily consistent backups are written to `backup/YYYYMMDD.zip`. Override the
location with `BACKUP_DIR`. Each archive contains both SQLite databases,
current profiles, personal baselines and a manifest. Date-named archives use
bounded retention (`BACKUP_RETENTION_COUNT`, default `3`) so a field unit does
not accumulate stale test data indefinitely.

## BCG transaction windows

The Pi stores approximately one LSM-800-T packet per second. New recordings
group 60 consecutive packets into a one-minute transaction window named
`tx1`, `tx2`, and so on. The exact first/last packet timestamps remain in
`bcg_epochs`; a transaction label is an acquisition window, not an AASM sleep
stage or a guaranteed wall-clock average. A window flushed before 60 packets
(for example during maintenance) is labelled `txN_partial`.

For an operator-authorized fresh-data reset, stop `zeep-pod.service`, back up
the complete `data/` directory, and run `reset_sleep_dataset.py` with the
selected open session, local tx1 interval, and the exact confirmation phrase
printed by `--help`. The utility keeps authentication, occupancy, calibration,
and hardware labels intact so resetting sleep history does not change the
occupant or actuator configuration.

Set `ENABLE_SYSTEM_POWEROFF=1` in the Pi environment to enable the protected
`POST /api/system/shutdown` endpoint. It finalizes the session, flushes partial
BCG epochs and writer queues, closes storage, calls filesystem sync, and only
then invokes `systemctl poweroff`.
