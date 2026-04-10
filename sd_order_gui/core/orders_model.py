from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class DraftOrder:
    command: str
    raw_params: Any  # whatever the UI collected (str/int/dict/None)


@dataclass
class DraftOrderFile:
    game: str
    account: str
    subject_type: str  # ship | prefect | starbase | port | outpost
    subject_id: str
    orders: list[DraftOrder]

