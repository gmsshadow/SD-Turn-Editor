from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppPaths:
    project_root: Path

    @property
    def data_dir(self) -> Path:
        return self.project_root / "data"

    @property
    def turns_dir(self) -> Path:
        return self.data_dir / "Turns"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "knowledge.sqlite"

    @property
    def settings_path(self) -> Path:
        return self.data_dir / "settings.json"


def resolve_project_root() -> Path:
    # Package lives under <root>/sd_order_gui. We want that root folder.
    return Path(__file__).resolve().parents[2]


def get_paths() -> AppPaths:
    return AppPaths(project_root=resolve_project_root())

