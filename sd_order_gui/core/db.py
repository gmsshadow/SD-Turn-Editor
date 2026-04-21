from __future__ import annotations

import sqlite3
from pathlib import Path


SCHEMA_SQL = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS imported_turn_files (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  turn_number TEXT NOT NULL,
  original_path TEXT NOT NULL,
  stored_path TEXT NOT NULL,
  imported_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_imported_turn_files_turn
  ON imported_turn_files(turn_number);

CREATE TABLE IF NOT EXISTS entities (
  entity_type TEXT NOT NULL,               -- ship | prefect | starbase | port | outpost
  entity_id TEXT NOT NULL,                 -- numeric, but stored as text for safety
  name TEXT NOT NULL,
  account_number TEXT,                     -- secret; may be null if unknown
  last_seen_turn TEXT NOT NULL,
  last_seen_report_path TEXT NOT NULL,
  PRIMARY KEY (entity_type, entity_id)
);

CREATE INDEX IF NOT EXISTS idx_entities_type_name
  ON entities(entity_type, name);

CREATE TABLE IF NOT EXISTS map_artifacts (
  artifact_id INTEGER PRIMARY KEY AUTOINCREMENT,
  map_type TEXT NOT NULL,                 -- scansystem | scansurface
  system_id INTEGER NOT NULL DEFAULT 0,   -- for scansystem (else 0)
  body_id INTEGER NOT NULL DEFAULT 0,     -- for scansurface (else 0)
  turn_number TEXT NOT NULL,
  source_report_path TEXT NOT NULL,
  stored_path TEXT NOT NULL,
  extracted_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_map_artifacts_lookup
  ON map_artifacts(map_type, system_id, body_id, turn_number);

-- Latest map per (type, system_id, body_id). Use 0 for unused id so PK works.
CREATE TABLE IF NOT EXISTS map_latest (
  map_type TEXT NOT NULL,                 -- scansystem | scansurface
  system_id INTEGER NOT NULL DEFAULT 0,
  body_id INTEGER NOT NULL DEFAULT 0,
  turn_number TEXT NOT NULL,
  source_report_path TEXT NOT NULL,
  stored_path TEXT NOT NULL,
  extracted_at TEXT NOT NULL,
  PRIMARY KEY (map_type, system_id, body_id)
);

CREATE INDEX IF NOT EXISTS idx_map_latest_type
  ON map_latest(map_type);

-- Migration helpers (safe to run repeatedly)
UPDATE map_artifacts SET system_id = 0 WHERE system_id IS NULL;
UPDATE map_artifacts SET body_id = 0 WHERE body_id IS NULL;

-- Rebuild map_latest to eliminate NULL-key duplicates from older schema.
CREATE TABLE IF NOT EXISTS map_latest_v2 (
  map_type TEXT NOT NULL,
  system_id INTEGER NOT NULL DEFAULT 0,
  body_id INTEGER NOT NULL DEFAULT 0,
  turn_number TEXT NOT NULL,
  source_report_path TEXT NOT NULL,
  stored_path TEXT NOT NULL,
  extracted_at TEXT NOT NULL,
  PRIMARY KEY (map_type, system_id, body_id)
);
INSERT OR REPLACE INTO map_latest_v2(map_type, system_id, body_id, turn_number, source_report_path, stored_path, extracted_at)
SELECT map_type, COALESCE(system_id, 0), COALESCE(body_id, 0), turn_number, source_report_path, stored_path, extracted_at
FROM map_latest;
DROP TABLE IF EXISTS map_latest;
ALTER TABLE map_latest_v2 RENAME TO map_latest;
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
    conn.commit()

