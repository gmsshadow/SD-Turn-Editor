from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ParsedSystemMap:
    width: int
    height: int
    # object_by_xy[(col,row)] -> object type label (e.g. "Planet", "Star", "Empty")
    object_by_xy: dict[tuple[int, int], str]


# Based on Stellar Dominion `engine/maps/system_map.py`
_SYMBOL_TO_OBJECT: dict[str, str] = {
    "*": "Star",
    "O": "Planet",
    "o": "Moon",
    "G": "Gas Giant",
    "#": "Asteroid",
    "B": "Base",
    "@": "Ship",
    "?": "Contact",
    ".": "Empty Space",
    # Future-proofing (if the engine adds explicit symbols later)
    "N": "Nebula",
    "S": "Stargate",
}

_ROW_RE = re.compile(r"^\s*(?P<row>\d{2})\s+(?P<body>.+?)\s*$")


def parse_scansystem_ascii(text: str) -> ParsedSystemMap | None:
    """
    Parse Phoenix-style SCANSYSTEM output into a 25x25 grid.

    We look for the header line containing columns A..Y and then capture 25 subsequent rows.
    Returns None if no valid system grid is detected.
    """
    lines = text.splitlines()

    # Header line is the column letters A..Y separated by spaces.
    expected_cols = [chr(c) for c in range(ord("A"), ord("Y") + 1)]

    header_idx: int | None = None
    for i, ln in enumerate(lines):
        tokens = [t for t in ln.strip().split() if t]
        if tokens == expected_cols:
            header_idx = i
            break
    if header_idx is None:
        return None

    rows: list[tuple[int, list[str]]] = []
    for ln in lines[header_idx + 1 :]:
        m = _ROW_RE.match(ln)
        if not m:
            # stop after we collected the expected grid
            if rows:
                break
            continue
        try:
            rnum = int(m.group("row"))
        except ValueError:
            continue
        body = m.group("body")
        cells = [t for t in body.split() if t]
        if len(cells) < 25:
            continue
        cells = cells[:25]
        rows.append((rnum, cells))
        if len(rows) >= 25:
            break

    if len(rows) < 25:
        return None

    # Rows are numbered 01..25 from top to bottom.
    object_by_xy: dict[tuple[int, int], str] = {}
    for rnum, cells in rows:
        if rnum < 1 or rnum > 25:
            continue
        row = rnum
        for col, sym in enumerate(cells, start=1):
            obj = _SYMBOL_TO_OBJECT.get(sym, "Unknown")
            object_by_xy[(col, row)] = obj

    return ParsedSystemMap(width=25, height=25, object_by_xy=object_by_xy)

