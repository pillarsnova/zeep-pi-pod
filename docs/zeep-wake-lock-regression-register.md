# ZEEP Wake Lock-in Regression Register

> **Status:** Active engineering QA  
> **Scope:** Internal coded Pilot evidence  
> **Policy:** `zeep-wake-lock-shadow-audit-v1.0`  
> **Clinical claim:** None — this is not AASM/PSG validation

## TL;DR

Three independent Overnight Sessions exposed the same historical failure:
after an established sleep sequence, a processing gap lost the onset context,
the awake reference drifted toward sleeping HR and the path remained in Wake.
The current estimator preserves onset/reference continuity. These coded cases
remain permanent regression evidence so the failure class cannot silently
return.

## Coded fixtures

| Fixture | Historical false-Wake duration | Signature |
|---|---:|---|
| `WL-FIXTURE-01` | 24.5 min | On bed, quiet, HR below awake reference, onset context lost |
| `WL-FIXTURE-02` | 16.5 min | On bed, quiet, HR below awake reference, onset context lost |
| `WL-FIXTURE-03` | 61.0 min | On bed, quiet, HR below awake reference, onset context lost |

The fixtures contain no name, email, raw BCG or directly identifying value.
They encode only the minimum failure signature and duration needed for a
deterministic test.

## Required acceptance criteria

1. All three historical lock-in signatures must be detected by the Shadow
   Audit.
2. Current replay must not create a post-onset Wake bout of at least 10 minutes
   through loss of onset context.
3. A genuine Wake/Bed Exit with movement or autonomic rise must remain Wake and
   must not be flagged as lock-in.
4. Quiet wakefulness with a valid onset context must not be automatically
   relabelled.
5. Audit findings are Admin QA flags only. They never rewrite Sleep State,
   WASO, Sleep Score, Recovery Score or raw data.

## Detector boundary

A finding requires the conjunction of:

- a confirmed sleep State occurred earlier in the Session;
- a contiguous Wake bout is at least 10 minutes;
- at least 90% of the bout reports lost onset context;
- at least 90% remains on bed;
- at least 90% has low movement;
- at least 90% has mean HR below its frozen awake reference.

Duration alone is never sufficient. A person may remain still and awake for a
long period because of insomnia, meditation or quiet rest.

## Operation

Manual check:

```bash
.venv/bin/python audit_wake_lock_in.py --data-dir data --lookback-days 2
```

The field Pod installs `zeep-wake-lock-audit.timer`, which runs each morning at
10:00 Asia/Bangkok. Detailed output is owner-only at:

`data/maintenance/wake-lock-audit-latest.json`

Console output contains aggregate counts only.

## Verification

- `test_wake_lock_in_audit.py` covers all three coded signatures, a genuine
  movement-supported Wake, quiet wakefulness and replay deduplication.
- `test_sleep_baseline_policy.py` verifies transient signal gaps preserve the
  confirmed State, onset and frozen awake reference.
- `test_session_history.py` independently verifies that user-facing Session
  counts include only completed, data-backed records in the current cutover.
