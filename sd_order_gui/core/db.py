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
  system_id INTEGER,                      -- for scansystem
  body_id INTEGER,                        -- for scansurface (best-effort)
  turn_number TEXT NOT NULL,
  source_report_path TEXT NOT NULL,
  stored_path TEXT NOT NULL,
  extracted_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_map_artifacts_lookup
  ON map_artifacts(map_type, system_id, body_id, turn_number);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
    conn.commit()

