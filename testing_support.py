"""Shared isolation helpers for tests that import the app singleton.

Importing :mod:`app` initializes storage objects. Standalone test execution
must therefore point those objects at temporary paths before the import, or a
developer's mirrored production data can be polluted by test accounts.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from access_control import hash_password


_APP_TEST_ROOT = tempfile.TemporaryDirectory(prefix="zeep-app-tests-")


def configure_app_test_environment() -> Path:
    """Return a process-lifetime temp root and configure app paths once."""
    root = Path(_APP_TEST_ROOT.name)
    if "app" in sys.modules:
        return root
    os.environ["DATA_DIR"] = str(root / "data")
    os.environ["BACKUP_DIR"] = str(root / "backup")
    os.environ["MUSIC_DIR"] = str(root / "music")
    os.environ["POD_ID"] = "test-pod-01"
    os.environ["AIRCON_POWER_ON_DEFAULT_TEMP_C"] = "18"
    os.environ["CONTROLHUB1_MIN_IR_GAP_SECONDS"] = "0"
    os.environ["CONTROLHUB1_POWER_ON_SETTLE_SECONDS"] = "0"
    os.environ["CONTROLHUB1_FAN_WAKE_SETTLE_SECONDS"] = "0"
    os.environ["LOCAL_ADMIN_USERNAME"] = "test-admin"
    os.environ["LOCAL_ADMIN_PASSWORD_HASH"] = hash_password("test-admin-password")
    return root
