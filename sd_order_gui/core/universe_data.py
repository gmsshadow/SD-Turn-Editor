from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

import yaml

from sd_order_gui.integrations.stellar_dominion.db_access import (
    connect_sd,
    resolve_sd_db_paths,
)


@dataclass(frozen=True)
class StarSystem:
    system_id: int
    name: str


@dataclass(frozen=True)
class CelestialBody:
    body_id: int
    system_id: int
    name: str
    body_type: str
    parent_body_id: int | None


@dataclass(frozen=True)
class SystemLink:
    system_a: int
    system_b: int


@dataclass(frozen=True)
class UniverseData:
    systems: list[StarSystem]
    bodies: list[CelestialBody]
    links: list[SystemLink]


def load_universe_from_sd_db(*, sd_repo_root: Path, state_db_path: str, universe_db_path: str) -> UniverseData:
    paths = resolve_sd_db_paths(
        sd_repo_root=sd_repo_root,
        state_db_path=state_db_path,
        universe_db_path=universe_db_path,
    )
    conn = connect_sd(paths=paths)
    try:
        systems = [
            StarSystem(int(r["system_id"]), str(r["name"]))
            for r in conn.execute(
                "SELECT system_id, name FROM universe.star_systems ORDER BY name"
            ).fetchall()
        ]
        bodies = [
            CelestialBody(
                int(r["body_id"]),
                int(r["system_id"]),
                str(r["name"]),
                str(r["body_type"]),
                int(r["parent_body_id"]) if r["parent_body_id"] is not None else None,
            )
            for r in conn.execute(
                "SELECT body_id, system_id, name, body_type, parent_body_id "
                "FROM universe.celestial_bodies ORDER BY system_id, name"
            ).fetchall()
        ]
        links = [
            SystemLink(int(r["system_a"]), int(r["system_b"]))
            for r in conn.execute(
                "SELECT system_a, system_b FROM universe.system_links ORDER BY system_a, system_b"
            ).fetchall()
        ]
        return UniverseData(systems=systems, bodies=bodies, links=links)
    finally:
        conn.close()


def load_universe_override(path: Path) -> UniverseData:
    if not path.exists():
        raise FileNotFoundError(str(path))
    raw_text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in (".yaml", ".yml"):
        data = yaml.safe_load(raw_text)
    else:
        data = json.loads(raw_text)
    if not isinstance(data, dict):
        raise ValueError("Universe override must be a mapping/object")

    def _req_list(key: str) -> list[dict[str, Any]]:
        v = data.get(key, [])
        if v is None:
            return []
        if not isinstance(v, list):
            raise ValueError(f"'{key}' must be a list")
        out: list[dict[str, Any]] = []
        for item in v:
            if not isinstance(item, dict):
                raise ValueError(f"'{key}' items must be objects")
            out.append(item)
        return out

    systems = [
        StarSystem(int(s["system_id"]), str(s["name"]))
        for s in _req_list("systems")
    ]
    bodies = [
        CelestialBody(
            int(b["body_id"]),
            int(b["system_id"]),
            str(b["name"]),
            str(b.get("body_type", "planet")),
            int(b["parent_body_id"]) if b.get("parent_body_id") is not None else None,
        )
        for b in _req_list("bodies")
    ]
    links = [
        SystemLink(int(l["system_a"]), int(l["system_b"]))
        for l in _req_list("links")
    ]
    return UniverseData(systems=systems, bodies=bodies, links=links)


def load_universe(*, sd_repo_root: Path, state_db_path: str, universe_db_path: str, override_path: str) -> UniverseData:
    if override_path and override_path.strip():
        return load_universe_override(Path(override_path))
    return load_universe_from_sd_db(
        sd_repo_root=sd_repo_root,
        state_db_path=state_db_path,
        universe_db_path=universe_db_path,
    )

