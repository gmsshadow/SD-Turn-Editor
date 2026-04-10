from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from sd_order_gui.core.db import init_db


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

