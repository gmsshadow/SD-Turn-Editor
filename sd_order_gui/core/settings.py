from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path


@dataclass(frozen=True)
class AppSettings:
    sd_repo_path: str
    sd_state_db_path: str
    sd_universe_db_path: str
    output_dir: str
    game_id: str


DEFAULT_SETTINGS = AppSettings(
    sd_repo_path=r"C:\Users\barry\GitHub\stellar_dominion",
    sd_state_db_path="",
    sd_universe_db_path="",
    output_dir="output",
    game_id="OMICRON101",
)


def load_settings(path: Path) -> AppSettings:
    if not path.exists():
        save_settings(path, DEFAULT_SETTINGS)
        return DEFAULT_SETTINGS

    data = json.loads(path.read_text(encoding="utf-8"))
    return AppSettings(
        sd_repo_path=str(data.get("sd_repo_path", DEFAULT_SETTINGS.sd_repo_path)),
        sd_state_db_path=str(data.get("sd_state_db_path", DEFAULT_SETTINGS.sd_state_db_path)),
        sd_universe_db_path=str(data.get("sd_universe_db_path", DEFAULT_SETTINGS.sd_universe_db_path)),
        output_dir=str(data.get("output_dir", DEFAULT_SETTINGS.output_dir)),
        game_id=str(data.get("game_id", DEFAULT_SETTINGS.game_id)),
    )


def save_settings(path: Path, settings: AppSettings) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "sd_repo_path": settings.sd_repo_path,
                "sd_state_db_path": settings.sd_state_db_path,
                "sd_universe_db_path": settings.sd_universe_db_path,
                "output_dir": settings.output_dir,
                "game_id": settings.game_id,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

