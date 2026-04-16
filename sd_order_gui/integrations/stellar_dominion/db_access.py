from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SdDbPaths:
    state_db: Path
    universe_db: Path


def resolve_sd_db_paths(*, sd_repo_root: Path, state_db_path: str, universe_db_path: str) -> SdDbPaths:
    """
    The game stores DBs under <repo>/game_data by default:
      - game_state.db
      - universe.db
    """
    if state_db_path.strip():
        state = Path(state_db_path)
    else:
        state = sd_repo_root / "game_data" / "game_state.db"

    if universe_db_path.strip():
        uni = Path(universe_db_path)
    else:
        uni = sd_repo_root / "game_data" / "universe.db"

    return SdDbPaths(state_db=state, universe_db=uni)


def connect_sd(*, paths: SdDbPaths) -> sqlite3.Connection:
    """
    Open game_state.db and ATTACH universe.db as `universe` so queries can
    reference `universe.*` tables.
    """
    conn = sqlite3.connect(str(paths.state_db))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if paths.universe_db.exists():
        conn.execute("ATTACH DATABASE ? AS universe", (str(paths.universe_db),))
    return conn

