from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


@dataclass(frozen=True)
class ParsedEntity:
    entity_type: str  # ship | prefect | starbase | port | outpost
    entity_id: str
    name: str
    account_number: str | None


# Examples (from sample report):
#   "STA SHIP Resolute (50838081)"
#   "STA PREFECT Erik Voss (55605243)"
ENTITY_HEADER_RE = re.compile(
    r"^\s*(?P<faction>[A-Z]{2,5})\s+"
    r"(?P<kind>SHIP|PREFECT|STARBASE|PORT|OUTPOST)\s+"
    r"(?P<name>.+?)\s*\((?P<id>\d+)\)\s*$"
)

ACCOUNT_RE = re.compile(r"^\s*Account:\s*(?P<acct>\d+)\s*$")


def parse_entities_from_report_text(text: str) -> tuple[str | None, list[ParsedEntity]]:
    """
    Returns (turn_number, entities) found in a report.
    turn_number uses the report marker: 'Star Date 500.1'
    """
    turn_m = re.search(r"Star Date\s+(?P<turn>\d+\.\d+)", text)
    turn_number = turn_m.group("turn") if turn_m else None

    entities: list[ParsedEntity] = []
    last_account: str | None = None
    pending_entity_idx: int | None = None

    # Account lines tend to appear immediately after the entity header in reports,
    # so we attach the next seen account number to the most recent entity.
    for raw_line in text.splitlines():
        line = raw_line.rstrip("\n")

        m = ENTITY_HEADER_RE.match(line)
        if m:
            kind = m.group("kind").lower()
            entity_type = {"ship": "ship", "prefect": "prefect"}.get(kind, kind)
            entities.append(
                ParsedEntity(
                    entity_type=entity_type,
                    entity_id=m.group("id"),
                    name=m.group("name").strip(),
                    account_number=None,
                )
            )
            pending_entity_idx = len(entities) - 1
            continue

        am = ACCOUNT_RE.match(line)
        if am:
            last_account = am.group("acct")
            if pending_entity_idx is not None:
                e = entities[pending_entity_idx]
                entities[pending_entity_idx] = ParsedEntity(
                    entity_type=e.entity_type,
                    entity_id=e.entity_id,
                    name=e.name,
                    account_number=last_account,
                )
                pending_entity_idx = None
            continue

    # De-duplicate (same entity may appear multiple times in concatenated files)
    uniq: dict[tuple[str, str], ParsedEntity] = {}
    for e in entities:
        uniq[(e.entity_type, e.entity_id)] = e
    return turn_number, list(uniq.values())


def parse_entities_from_file(path: Path) -> tuple[str | None, list[ParsedEntity]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    return parse_entities_from_report_text(text)

