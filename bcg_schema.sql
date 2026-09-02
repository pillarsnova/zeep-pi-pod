PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bcg_epochs (
    epoch_id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    epoch_index INTEGER NOT NULL,
    tx_label TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    packet_count INTEGER NOT NULL,
    sample_count INTEGER NOT NULL,
    average_hr REAL,
    average_rr REAL,
    UNIQUE(session_id, epoch_index)
);

CREATE TABLE IF NOT EXISTS bcg_packets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    epoch_id INTEGER NOT NULL,
    packet_index INTEGER NOT NULL,
    timestamp TEXT NOT NULL,
    sensor_packet_id INTEGER,
    status_code INTEGER NOT NULL,
    heart_rate REAL,
    respiration_rate REAL,
    bcg_base64 TEXT NOT NULL,
    raw_packet_base64 TEXT NOT NULL,
    FOREIGN KEY (epoch_id) REFERENCES bcg_epochs(epoch_id) ON DELETE CASCADE,
    UNIQUE(epoch_id, packet_index)
);

CREATE INDEX IF NOT EXISTS idx_bcg_epochs_session ON bcg_epochs(session_id, epoch_index);
CREATE INDEX IF NOT EXISTS idx_bcg_packets_epoch ON bcg_packets(epoch_id, packet_index);
CREATE INDEX IF NOT EXISTS idx_bcg_packets_timestamp ON bcg_packets(timestamp);

INSERT OR REPLACE INTO schema_meta(key, value) VALUES ('schema_version', '2');
