from __future__ import annotations

from dataclasses import dataclass
import re
from pathlib import Path


@dataclass(frozen=True)
class MapArtifact:
    map_type: str  # scansystem | scansurface
    system_id: int | None
    body_id: int | None
    text: str


TURN_LINE_RE = re.compile(r"^>OC\s+\d+:\s+(?P<cmd>[A-Z]+)\s*$")
SYSTEM_ID_RE = re.compile(r"\bSystem\s*\((?P<id>\d+)\)")
BODY_ID_RE = re.compile(r"\((?P<id>\d+)\)")
SURFACE_MAP_TITLE_RE = re.compile(r"^\s*Surface Map:\s+.+\((?P<id>\d+)\)\s*\[", re.IGNORECASE)


def _find_current_system_id(text: str) -> int | None:
    # Prefer the "Starting Location" line if present.
    # Example: "P15 - Omicron System (101)"
    for line in text.splitlines():
        m = SYSTEM_ID_RE.search(line)
        if m:
            try:
                return int(m.group("id"))
            except ValueError:
                return None
    return None


def _guess_body_id_near(lines: list[str], start_idx: int) -> int | None:
    """
    Best-effort guess: look back for an 'Orbiting ... (123)' or 'Landed on ... (123)'
    style line that includes a numeric id in parentheses.
    """
    for i in range(max(0, start_idx - 60), start_idx):
        line = lines[i]
        if "Orbit" in line or "orbit" in line or "Landed" in line or "landed" in line:
            m = BODY_ID_RE.search(line)
            if m:
                try:
                    return int(m.group("id"))
                except ValueError:
                    pass
    return None


def extract_map_artifacts(report_text: str) -> list[MapArtifact]:
    """
    Extract ASCII map blocks emitted by SCANSYSTEM / SCANSURFACE from a report.
    We capture from the command line until either:
      - the next '>OC ...:' line (next command), or
      - the next boxed section of the report begins (lines starting with '|')

    This intentionally keeps embedded blank lines, because map output can include
    a legend under the grid separated by blank lines.
    """
    lines = report_text.splitlines()
    artifacts: list[MapArtifact] = []

    system_id = _find_current_system_id(report_text)

    i = 0
    while i < len(lines):
        m = TURN_LINE_RE.match(lines[i].strip())
        if not m:
            i += 1
            continue

        cmd = m.group("cmd").upper()
        if cmd not in ("SCANSYSTEM", "SCANSURFACE"):
            i += 1
            continue

        # Capture block following the command line.
        start = i
        i += 1
        while i < len(lines):
            if lines[i].startswith(">OC "):
                break
            if lines[i].startswith("|"):
                # Boxed section header (e.g. Command Report) begins.
                break
            i += 1
        block = "\n".join(lines[start:i]).rstrip() + "\n"

        body_id = None
        if cmd == "SCANSURFACE":
            # Prefer the explicit surface map title which includes body id:
            # "Surface Map: Ember (141665) [31x31]"
            for bl in block.splitlines():
                sm = SURFACE_MAP_TITLE_RE.match(bl)
                if sm:
                    try:
                        body_id = int(sm.group("id"))
                    except ValueError:
                        body_id = None
                    break
            if body_id is None:
                body_id = _guess_body_id_near(lines, start_idx=start)

        artifacts.append(
            MapArtifact(
                map_type=("scansystem" if cmd == "SCANSYSTEM" else "scansurface"),
                system_id=system_id if cmd == "SCANSYSTEM" else None,
                body_id=body_id if cmd == "SCANSURFACE" else None,
                text=block,
            )
        )

    return artifacts


def map_cache_path(*, cache_root: Path, artifact: MapArtifact, turn_number: str) -> Path:
    if artifact.map_type == "scansystem":
        sid = artifact.system_id or 0
        return cache_root / "maps" / f"system_{sid}" / f"scansystem_{turn_number}.txt"
    bid = artifact.body_id or 0
    return cache_root / "maps" / f"body_{bid}" / f"scansurface_{turn_number}.txt"


def map_latest_cache_path(*, cache_root: Path, artifact: MapArtifact) -> Path:
    if artifact.map_type == "scansystem":
        sid = artifact.system_id or 0
        return cache_root / "maps" / f"system_{sid}" / "scansystem_latest.txt"
    bid = artifact.body_id or 0
    return cache_root / "maps" / f"body_{bid}" / "scansurface_latest.txt"

