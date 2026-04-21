from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from sd_order_gui.core.db import init_db
from sd_order_gui.core.map_extract import (
    extract_map_artifacts,
    map_cache_path,
    map_latest_cache_path,
)
from sd_order_gui.core.turn_parse import parse_entities_from_report_text


TURN_NUMBER_RE = r"Star Date\s+(?P<turn>\d+\.\d+)"


@dataclass(frozen=True)
class IngestResult:
    original_path: Path
    stored_path: Path | None
    turn_number: str | None
    error: str | None = None


def detect_turn_number(text: str) -> str | None:
    # Keep it simple and robust; the sample report includes:
    # "Printed on 10 March 2026, Star Date 500.1"
    import re

    m = re.search(TURN_NUMBER_RE, text)
    return m.group("turn") if m else None


def safe_copy_into_turn_folder(
    *,
    src: Path,
    dest_turn_dir: Path,
) -> Path:
    dest_turn_dir.mkdir(parents=True, exist_ok=True)
    target = dest_turn_dir / src.name
    if not target.exists():
        shutil.copy2(src, target)
        return target

    stem = src.stem
    suffix = src.suffix
    for i in range(2, 10_000):
        candidate = dest_turn_dir / f"{stem} ({i}){suffix}"
        if not candidate.exists():
            shutil.copy2(src, candidate)
            return candidate

    raise RuntimeError("Too many duplicate filenames while importing.")


def ingest_turn_files(
    *,
    conn,
    turns_root: Path,
    files: Iterable[Path],
) -> list[IngestResult]:
    init_db(conn)
    results: list[IngestResult] = []
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
            turn_number = detect_turn_number(text)
            if not turn_number:
                results.append(
                    IngestResult(
                        original_path=f,
                        stored_path=None,
                        turn_number=None,
                        error="Could not detect turn number (missing 'Star Date <year>.<week>').",
                    )
                )
                continue

            stored = safe_copy_into_turn_folder(
                src=f, dest_turn_dir=turns_root / str(turn_number)
            )

            conn.execute(
                """
                INSERT INTO imported_turn_files(turn_number, original_path, stored_path, imported_at)
                VALUES (?, ?, ?, ?)
                """,
                (str(turn_number), str(f), str(stored), now),
            )

            # Parse + upsert any entities found in this report.
            _, entities = parse_entities_from_report_text(text)
            for e in entities:
                conn.execute(
                    """
                    INSERT INTO entities(entity_type, entity_id, name, account_number, last_seen_turn, last_seen_report_path)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(entity_type, entity_id) DO UPDATE SET
                      name = excluded.name,
                      account_number = COALESCE(excluded.account_number, entities.account_number),
                      last_seen_turn = excluded.last_seen_turn,
                      last_seen_report_path = excluded.last_seen_report_path
                    """,
                    (
                        e.entity_type,
                        e.entity_id,
                        e.name,
                        e.account_number,
                        str(turn_number),
                        str(stored),
                    ),
                )

            # Extract and cache map artifacts (SCANSYSTEM / SCANSURFACE).
            cache_root = turns_root.parent / "Cache"
            extracted_at = now
            for art in extract_map_artifacts(text):
                # Use 0 instead of NULL so uniqueness keys behave.
                sys_id = int(art.system_id or 0)
                body_id = int(art.body_id or 0)

                stored_map_path = map_cache_path(
                    cache_root=cache_root, artifact=art, turn_number=str(turn_number)
                )
                stored_map_path.parent.mkdir(parents=True, exist_ok=True)
                stored_map_path.write_text(art.text, encoding="utf-8")

                # Maintain an always-latest copy per system/body.
                latest_path = map_latest_cache_path(cache_root=cache_root, artifact=art)
                latest_path.parent.mkdir(parents=True, exist_ok=True)
                latest_path.write_text(art.text, encoding="utf-8")

                conn.execute(
                    """
                    INSERT INTO map_artifacts(map_type, system_id, body_id, turn_number, source_report_path, stored_path, extracted_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        art.map_type,
                        sys_id,
                        body_id,
                        str(turn_number),
                        str(stored),
                        str(stored_map_path),
                        extracted_at,
                    ),
                )

                conn.execute(
                    """
                    INSERT INTO map_latest(map_type, system_id, body_id, turn_number, source_report_path, stored_path, extracted_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(map_type, system_id, body_id) DO UPDATE SET
                      turn_number = excluded.turn_number,
                      source_report_path = excluded.source_report_path,
                      stored_path = excluded.stored_path,
                      extracted_at = excluded.extracted_at
                    """,
                    (
                        art.map_type,
                        sys_id,
                        body_id,
                        str(turn_number),
                        str(stored),
                        str(latest_path),
                        extracted_at,
                    ),
                )

                # Prune older scan history for this key (keep only the most recent).
                old_rows = conn.execute(
                    """
                    SELECT artifact_id, stored_path
                    FROM map_artifacts
                    WHERE map_type = ? AND system_id = ? AND body_id = ? AND turn_number != ?
                    """,
                    (art.map_type, sys_id, body_id, str(turn_number)),
                ).fetchall()
                for r in old_rows:
                    try:
                        p = Path(str(r["stored_path"]))
                        if p.exists() and p.resolve() != latest_path.resolve():
                            p.unlink(missing_ok=True)
                    except Exception:
                        pass
                    conn.execute("DELETE FROM map_artifacts WHERE artifact_id = ?", (r["artifact_id"],))
            conn.commit()

            results.append(
                IngestResult(
                    original_path=f,
                    stored_path=stored,
                    turn_number=str(turn_number),
                )
            )
        except Exception as e:  # noqa: BLE001 - surface in UI
            results.append(
                IngestResult(
                    original_path=f,
                    stored_path=None,
                    turn_number=None,
                    error=str(e),
                )
            )

    return results

