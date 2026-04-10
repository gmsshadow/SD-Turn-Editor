from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import importlib.util
from types import ModuleType


@dataclass(frozen=True)
class CommandSpec:
    command: str
    params: str
    subject: str  # ship | prefect | both
    description: str


@dataclass(frozen=True)
class OrderCatalog:
    commands: dict[str, CommandSpec]

    def allowed_for_subject(self, *, subject_type: str) -> list[CommandSpec]:
        out: list[CommandSpec] = []
        for spec in self.commands.values():
            if spec.subject == "both" or spec.subject == subject_type:
                out.append(spec)
        return sorted(out, key=lambda s: s.command)


def _load_module_from_path(module_path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location("sd_engine_orders_parser", str(module_path))
    if not spec or not spec.loader:
        raise RuntimeError(f"Could not import module from {module_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return mod


def load_catalog_from_sd_repo(sd_repo_root: Path) -> tuple[OrderCatalog, ModuleType]:
    """
    Loads `engine/orders/parser.py` from a Stellar Dominion checkout.
    Returns (catalog, parser_module) so callers can reuse `parse_order()` for validation.
    """
    parser_path = sd_repo_root / "engine" / "orders" / "parser.py"
    if not parser_path.exists():
        raise FileNotFoundError(f"Could not find Stellar Dominion order parser at {parser_path}")

    mod = _load_module_from_path(parser_path)
    raw = getattr(mod, "VALID_COMMANDS", None)
    if not isinstance(raw, dict):
        raise RuntimeError("VALID_COMMANDS not found or invalid in Stellar Dominion parser.py")

    commands: dict[str, CommandSpec] = {}
    for cmd, spec in raw.items():
        if not isinstance(spec, dict):
            continue
        params = str(spec.get("params", "none"))
        subject = str(spec.get("subject", "ship"))
        desc = str(spec.get("description", ""))
        commands[str(cmd)] = CommandSpec(
            command=str(cmd),
            params=params,
            subject=subject,
            description=desc,
        )

    return OrderCatalog(commands=commands), mod

