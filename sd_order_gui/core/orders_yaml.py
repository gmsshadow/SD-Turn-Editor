from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from sd_order_gui.core.orders_model import DraftOrderFile


def _yaml_order_item(command: str, parsed_params: Any) -> Any:
    if parsed_params is None:
        return command

    # Coordinate params are parsed by game code into {col,row}. For YAML writing,
    # the game accepts MOVE: "M13" style; keep it human-friendly.
    if isinstance(parsed_params, dict) and set(parsed_params.keys()) == {"col", "row"}:
        return {command: f"{parsed_params['col']}{int(parsed_params['row']):02d}"}

    return {command: parsed_params}


def build_orders_yaml(doc: DraftOrderFile, *, parsed_orders: list[tuple[str, Any]]) -> str:
    """
    parsed_orders are (command, parsed_params) output from SD's parse_order().
    """
    data: dict[str, Any] = {
        "game": doc.game,
        "account": doc.account,
        doc.subject_type: int(doc.subject_id) if doc.subject_id.isdigit() else doc.subject_id,
        "orders": [_yaml_order_item(cmd, params) for (cmd, params) in parsed_orders],
    }
    return yaml.safe_dump(data, sort_keys=False)


def default_output_filename(*, entity_name: str, entity_id: str, turn_number: str) -> str:
    # User-requested pattern: "<Name> <ID> <turn>.yaml"
    # Keep it filesystem-safe-ish; avoid slashes and colons.
    safe_name = "".join(c for c in entity_name if c not in r'<>:"/\|?*').strip()
    safe_name = " ".join(safe_name.split())
    return f"{safe_name} {entity_id} {turn_number}.yaml"


def write_orders_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")

