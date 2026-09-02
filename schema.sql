PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL UNIQUE,
    user TEXT NOT NULL,
    username_key TEXT NOT NULL,
    identity_subject TEXT,
    pod_id TEXT,
    zeep_public_id TEXT,
    gender TEXT,
    start_time TEXT NOT NULL,
    end_time TEXT,
    duration REAL,
    note TEXT,
    end_reason TEXT,
    created_at TEXT NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 2
);

CREATE TABLE IF NOT EXISTS timeline (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    temperature REAL,
    humidity REAL,
    co2 REAL,
    pm2_5 REAL,
    voc_index REAL,
    lux REAL,
    sound REAL,
    heart_rate REAL,
    respiration_rate REAL,
    bed_status TEXT,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    type TEXT NOT NULL,
    value TEXT,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_sessions_user_start ON sessions(username_key, start_time DESC);
CREATE INDEX IF NOT EXISTS idx_timeline_session_timestamp ON timeline(session_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_events_session_timestamp ON events(session_id, timestamp);

INSERT OR REPLACE INTO schema_meta(key, value) VALUES ('schema_version', '4');
