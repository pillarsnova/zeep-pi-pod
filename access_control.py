"""Browser authentication and role-based access control for a ZEEP pod.

The physical sleep session and the browser login session are deliberately
separate.  A pod has at most one physical occupant, while an administrator may
monitor that pod from another browser without becoming the occupant.

Only opaque random session IDs are stored in cookies.  ZEEP access/refresh
tokens remain in ``app.py`` for logout revocation and are never written here.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


COOKIE_NAME = "zeep_auth"
CSRF_COOKIE_NAME = "zeep_csrf"
DEFAULT_SESSION_TTL_SECONDS = 12 * 60 * 60
OFFLINE_TICKET_TTL_SECONDS = 5 * 60


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Principal:
    """Authenticated browser identity returned to FastAPI dependencies."""

    session_id: str
    subject: str
    username: str
    display_name: str
    account_key: str
    email: Optional[str]
    role: str
    auth_source: str
    csrf_token: str
    expires_at: float

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    def public_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "username": self.username,
            "display_name": self.display_name,
            "account_key": self.account_key,
            "email": self.email,
            "role": self.role,
            "auth_source": self.auth_source,
            "expires_at": self.expires_at,
        }


class AuthSessionManager:
    """Small SQLite-backed auth-session store shared by all HTTP workers.

    The cookie token is hashed before persistence.  Restarting the Pi therefore
    does not log an administrator out, but stealing ``auth.db`` alone is not
    enough to reuse a browser cookie.
    """

    def __init__(self, data_dir: Path) -> None:
        self.path = data_dir / "auth.db"
        self.ttl_seconds = max(
            300, int(os.getenv("AUTH_SESSION_TTL_SECONDS", DEFAULT_SESSION_TTL_SECONDS))
        )
        self.secure_cookie = _env_bool("AUTH_SECURE_COOKIE", False)
        self.local_admin_username = os.getenv("LOCAL_ADMIN_USERNAME", "admin").strip()
        self.local_admin_password_hash = os.getenv("LOCAL_ADMIN_PASSWORD_HASH", "").strip()
        self.local_admin_accounts_file = Path(os.getenv(
            "LOCAL_ADMIN_ACCOUNTS_FILE", str(data_dir / "local_admins.json")
        )).expanduser()
        self._local_admin_accounts = self._load_local_admin_accounts()
        self._lock = threading.RLock()
        self._offline_tickets: dict[str, tuple[str, float]] = {}
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    def _initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection, connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS auth_sessions (
                    token_hash TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL UNIQUE,
                    subject TEXT NOT NULL,
                    username TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    account_key TEXT NOT NULL,
                    email TEXT,
                    role TEXT NOT NULL CHECK(role IN ('user','admin')),
                    auth_source TEXT NOT NULL,
                    csrf_token TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_auth_subject
                    ON auth_sessions(subject, expires_at);
                """
            )
            # Existing Pods predate account_key/email.  Keep browser sessions
            # usable across upgrades, then let the app re-key known ZEEP users
            # from their legacy username to normalized email at startup.
            existing = {
                row[1] for row in connection.execute("PRAGMA table_info(auth_sessions)")
            }
            if "account_key" not in existing:
                connection.execute("ALTER TABLE auth_sessions ADD COLUMN account_key TEXT")
            if "email" not in existing:
                connection.execute("ALTER TABLE auth_sessions ADD COLUMN email TEXT")
            connection.execute(
                "UPDATE auth_sessions SET account_key=lower(username) "
                "WHERE account_key IS NULL OR account_key=''"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_auth_account_key "
                "ON auth_sessions(account_key, expires_at)"
            )

    def create(
        self,
        *,
        subject: str,
        username: str,
        display_name: str,
        account_key: str,
        email: Optional[str],
        role: str,
        auth_source: str,
    ) -> tuple[str, Principal]:
        if role not in {"user", "admin"}:
            raise ValueError(f"unsupported role: {role}")
        now = time.time()
        cookie_token = secrets.token_urlsafe(32)
        principal = Principal(
            session_id=f"auth-{secrets.token_hex(12)}",
            subject=subject,
            username=username,
            display_name=display_name or username,
            account_key=account_key.strip().casefold(),
            email=(email or "").strip().casefold() or None,
            role=role,
            auth_source=auth_source,
            csrf_token=secrets.token_urlsafe(24),
            expires_at=now + self.ttl_seconds,
        )
        with self._lock, closing(self._connect()) as connection, connection:
            connection.execute("DELETE FROM auth_sessions WHERE expires_at<=?", (now,))
            connection.execute(
                """INSERT INTO auth_sessions
                   (token_hash,session_id,subject,username,display_name,account_key,email,
                    role,auth_source,csrf_token,created_at,expires_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    _token_hash(cookie_token),
                    principal.session_id,
                    principal.subject,
                    principal.username,
                    principal.display_name,
                    principal.account_key,
                    principal.email,
                    principal.role,
                    principal.auth_source,
                    principal.csrf_token,
                    now,
                    principal.expires_at,
                ),
            )
        return cookie_token, principal

    def resolve(self, cookie_token: Optional[str]) -> Optional[Principal]:
        if not cookie_token:
            return None
        now = time.time()
        with self._lock, closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT * FROM auth_sessions WHERE token_hash=?",
                (_token_hash(cookie_token),),
            ).fetchone()
            if row is None:
                return None
            if float(row["expires_at"]) <= now:
                connection.execute(
                    "DELETE FROM auth_sessions WHERE token_hash=?",
                    (_token_hash(cookie_token),),
                )
                return None
        return Principal(
            session_id=row["session_id"],
            subject=row["subject"],
            username=row["username"],
            display_name=row["display_name"],
            account_key=(row["account_key"] or row["username"]).strip().casefold(),
            email=(row["email"] or "").strip().casefold() or None,
            role=row["role"],
            auth_source=row["auth_source"],
            csrf_token=row["csrf_token"],
            expires_at=float(row["expires_at"]),
        )

    def rekey_account_keys(self, mapping: dict[str, str]) -> int:
        """Move persisted ZEEP browser identities from username to email keys."""
        changed = 0
        with self._lock, closing(self._connect()) as connection, connection:
            for old_key, new_key in mapping.items():
                old = str(old_key or "").strip().casefold()
                new = str(new_key or "").strip().casefold()
                if not old or not new or old == new:
                    continue
                cursor = connection.execute(
                    """UPDATE auth_sessions SET account_key=?,email=?
                       WHERE role='user' AND lower(account_key)=?""",
                    (new, new, old),
                )
                changed += max(0, int(cursor.rowcount or 0))
        return changed

    def update_user_display_name(self, account_key: str, display_name: str) -> int:
        """Update the presentation name for every live User browser session.

        The immutable account key remains unchanged.  This is used when an
        administrator corrects a participant alias on the Pod while keeping
        Session ownership, history and duplicate-login protection attached to
        the verified email identity.
        """
        key = str(account_key or "").strip().casefold()
        name = str(display_name or "").strip()
        if not key or not name:
            return 0
        now = time.time()
        with self._lock, closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                """UPDATE auth_sessions SET display_name=?
                   WHERE role='user' AND lower(account_key)=? AND expires_at>?""",
                (name, key, now),
            )
        return max(0, int(cursor.rowcount or 0))

    def revoke(self, cookie_token: Optional[str]) -> None:
        if not cookie_token:
            return
        with self._lock, closing(self._connect()) as connection, connection:
            connection.execute(
                "DELETE FROM auth_sessions WHERE token_hash=?",
                (_token_hash(cookie_token),),
            )

    def revoke_user_identity(
        self,
        *,
        session_id: Optional[str] = None,
        subject: Optional[str] = None,
        all_for_subject: bool = False,
    ) -> int:
        """Revoke an occupant's browser login without touching Admin sessions.

        A normal administrative Session end targets the exact browser session
        that acquired this Pod.  A force-kick additionally removes every local
        ``user`` login for the same immutable identity.  The role predicate is
        intentional: an Admin account is never signed out by an occupant action.
        """
        session_id = (session_id or "").strip() or None
        subject = (subject or "").strip() or None
        if not session_id and not subject:
            return 0
        if all_for_subject and subject:
            where = "role='user' AND subject=?"
            params = (subject,)
        elif session_id:
            where = "role='user' AND session_id=?"
            params = (session_id,)
        else:
            # Restored Sessions created before owner_auth_session_id was
            # persisted can still be ended safely by immutable subject.
            where = "role='user' AND subject=?"
            params = (subject,)
        with self._lock, closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                f"DELETE FROM auth_sessions WHERE {where}",
                params,
            )
            return max(0, int(cursor.rowcount or 0))

    def issue_offline_ticket(self, identifier: str) -> str:
        """Allow local fallback only after this Pi observed ZEEP being offline."""
        ticket = secrets.token_urlsafe(24)
        key = hashlib.sha256(identifier.strip().casefold().encode("utf-8")).hexdigest()
        with self._lock:
            self._offline_tickets[_token_hash(ticket)] = (
                key,
                time.time() + OFFLINE_TICKET_TTL_SECONDS,
            )
        return ticket

    def consume_offline_ticket(self, ticket: str, identifier: str) -> bool:
        key = hashlib.sha256(identifier.strip().casefold().encode("utf-8")).hexdigest()
        with self._lock:
            item = self._offline_tickets.pop(_token_hash(ticket or ""), None)
        return bool(item and item[0] == key and item[1] > time.time())

    @property
    def local_admin_enabled(self) -> bool:
        return bool(self._local_admin_accounts)

    def _load_local_admin_accounts(self) -> dict[str, tuple[str, str]]:
        """Load legacy env credentials plus an optional hashed account file.

        The account file never contains plaintext passwords. Supported format::

            {"version": 1, "accounts": [
              {"username": "operator", "password_hash": "scrypt$...", "enabled": true}
            ]}

        Keys are case-insensitive for login, while the configured spelling is
        retained in the audit principal. Duplicate usernames fail startup so a
        file cannot silently replace the break-glass environment account.
        """
        accounts: dict[str, tuple[str, str]] = {}

        def add(username: Any, password_hash: Any, *, enabled: bool = True) -> None:
            name = str(username or "").strip()
            encoded = str(password_hash or "").strip()
            if not enabled or not name or not encoded:
                return
            if len(encoded.split("$", 5)) != 6 or not encoded.startswith("scrypt$"):
                raise ValueError(f"invalid local admin password hash for {name!r}")
            key = name.casefold()
            if key in accounts:
                raise ValueError(f"duplicate local admin username: {name!r}")
            accounts[key] = (name, encoded)

        add(self.local_admin_username, self.local_admin_password_hash)
        if not self.local_admin_accounts_file.exists():
            return accounts
        try:
            payload = json.loads(self.local_admin_accounts_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(
                f"cannot read LOCAL_ADMIN_ACCOUNTS_FILE: {self.local_admin_accounts_file}"
            ) from exc
        entries = payload.get("accounts") if isinstance(payload, dict) else None
        if not isinstance(entries, list):
            raise ValueError("LOCAL_ADMIN_ACCOUNTS_FILE must contain an accounts list")
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError("each local admin account must be an object")
            add(
                entry.get("username"),
                entry.get("password_hash"),
                enabled=entry.get("enabled", True) is not False,
            )
        return accounts

    def authenticate_local_admin(self, username: str, password: str) -> Optional[str]:
        """Return the configured username after constant-work password checks."""
        candidate = username.strip().casefold()
        matched: Optional[str] = None
        # Verify every configured hash. Besides keeping the code simple for a
        # small operator list, this avoids an obvious fast path for unknown IDs.
        for key, (configured_name, encoded) in self._local_admin_accounts.items():
            name_matches = hmac.compare_digest(candidate, key)
            password_matches = verify_password(password, encoded)
            if name_matches and password_matches:
                matched = configured_name
        return matched

    def verify_local_admin(self, username: str, password: str) -> bool:
        return self.authenticate_local_admin(username, password) is not None

    def health(self) -> dict[str, Any]:
        now = time.time()
        with closing(self._connect()) as connection:
            active = connection.execute(
                "SELECT COUNT(*) FROM auth_sessions WHERE expires_at>?", (now,)
            ).fetchone()[0]
        return {
            "active_browser_sessions": active,
            "local_admin_enabled": self.local_admin_enabled,
            "local_admin_account_count": len(self._local_admin_accounts),
            "secure_cookie": self.secure_cookie,
        }


def hash_password(password: str) -> str:
    """Create a portable scrypt hash for ``LOCAL_ADMIN_PASSWORD_HASH``."""
    salt = secrets.token_bytes(16)
    n, r, p = 16384, 8, 1
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p)
    return "scrypt${}${}${}${}${}".format(
        n,
        r,
        p,
        base64.urlsafe_b64encode(salt).decode("ascii"),
        base64.urlsafe_b64encode(digest).decode("ascii"),
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt_text, digest_text = encoded.split("$", 5)
        if algorithm != "scrypt":
            return False
        salt = base64.urlsafe_b64decode(salt_text.encode("ascii"))
        expected = base64.urlsafe_b64decode(digest_text.encode("ascii"))
        actual = hashlib.scrypt(
            password.encode("utf-8"), salt=salt, n=int(n), r=int(r), p=int(p)
        )
        return hmac.compare_digest(actual, expected)
    except (TypeError, ValueError):
        return False
