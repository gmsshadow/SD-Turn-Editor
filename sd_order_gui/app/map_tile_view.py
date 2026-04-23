from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QPixmap, QPainter
from PySide6.QtWidgets import QGraphicsPixmapItem, QGraphicsScene, QGraphicsView

from sd_order_gui.core.ascii_surface_map import ParsedSurfaceMap
from sd_order_gui.core.ascii_system_map import ParsedSystemMap


@dataclass(frozen=True)
class MapTileViewConfig:
    tile_px: int = 24
    show_grid_lines: bool = False


class _TileItem(QGraphicsPixmapItem):
    def __init__(self, pixmap: QPixmap, *, x: int, y: int, terrain: str) -> None:
        super().__init__(pixmap)
        self.setAcceptHoverEvents(True)
        self._x = x
        self._y = y
        self._terrain = terrain
        self._sync_tooltip()

    def _sync_tooltip(self) -> None:
        self.setToolTip(f"({self._x},{self._y}) — {self._terrain}")


class MapTileView(QGraphicsView):
    """
    Simple tile renderer for SCANSURFACE maps.
    """

    def __init__(self, *, tiles_dir: Path, config: MapTileViewConfig | None = None, parent=None) -> None:
        super().__init__(parent)
        self._tiles_dir = tiles_dir
        self._cfg = config or MapTileViewConfig()
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)

        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        self._pix: dict[str, QPixmap] = {}
        self._sys_pix: dict[str, QPixmap] = {}
        self._load_tiles()
        self._load_system_tiles()

    def _load_tiles(self) -> None:
        def load(name: str) -> QPixmap | None:
            p = self._tiles_dir / f"{name}.png"
            if not p.exists():
                return None
            pm = QPixmap(str(p))
            return pm if not pm.isNull() else None

        # Terrain names match the user's asset filenames.
        for t in (
            "shallows",
            "sea",
            "ice",
            "tundra",
            "grassland",
            "plains",
            "forest",
            "jungle",
            "swamp",
            "marsh",
            "hills",
            "mountains",
            "rock",
            "dust",
            "crater",
            "volcanic",
            "desert",
            "cultivated",
            "ruin",
            "urban",
            "gas",
        ):
            pm = load(t)
            if pm:
                self._pix[t.title() if t != "gas" else "Gas"] = pm
                # Most names Title() correctly except maybe multiword; current set is single-word.
                if t == "grassland":
                    self._pix["Grassland"] = pm
                if t == "shallows":
                    self._pix["Shallows"] = pm
                if t == "mountains":
                    self._pix["Mountains"] = pm
                if t == "cultivated":
                    self._pix["Cultivated"] = pm
                if t == "volcanic":
                    self._pix["Volcanic"] = pm
                if t == "tundra":
                    self._pix["Tundra"] = pm
                if t == "crater":
                    self._pix["Crater"] = pm
                if t == "grassland":
                    self._pix["Grassland"] = pm
                if t == "sea":
                    self._pix["Sea"] = pm
                if t == "ice":
                    self._pix["Ice"] = pm
                if t == "forest":
                    self._pix["Forest"] = pm
                if t == "jungle":
                    self._pix["Jungle"] = pm
                if t == "swamp":
                    self._pix["Swamp"] = pm
                if t == "marsh":
                    self._pix["Marsh"] = pm
                if t == "hills":
                    self._pix["Hills"] = pm
                if t == "rock":
                    self._pix["Rock"] = pm
                if t == "dust":
                    self._pix["Dust"] = pm
                if t == "desert":
                    self._pix["Desert"] = pm
                if t == "ruin":
                    self._pix["Ruin"] = pm
                if t == "urban":
                    self._pix["Urban"] = pm

        # Fallback tile (reuse Rock if present)
        if "Rock" in self._pix:
            self._pix.setdefault("Unknown", self._pix["Rock"])

    def _load_system_tiles(self) -> None:
        def load(name: str) -> QPixmap | None:
            p = self._tiles_dir / f"{name}.png"
            if not p.exists():
                return None
            pm = QPixmap(str(p))
            return pm if not pm.isNull() else None

        mapping = {
            "Star": "star",
            "Planet": "planet",
            "Moon": "moon",
            "Gas Giant": "gas_giant",
            "Asteroid": "asteroid",
            "Empty Space": "space",
            "Nebula": "nebula",
            "Stargate": "stargate",
            # Fallbacks for symbols the engine may emit
            "Base": "stargate",   # placeholder until a base tile exists
            "Ship": "stargate",   # placeholder until a ship tile exists
            "Contact": "stargate",  # placeholder until a contact tile exists
        }
        for obj, fname in mapping.items():
            pm = load(fname)
            if pm:
                self._sys_pix[obj] = pm

        # Best-effort fallbacks
        if "Empty Space" in self._sys_pix:
            self._sys_pix.setdefault("Unknown", self._sys_pix["Empty Space"])

    def clear_map(self) -> None:
        self._scene.clear()
        self._scene.setSceneRect(QRectF())

    def set_surface_map(self, parsed: ParsedSurfaceMap) -> None:
        self._scene.clear()

        tile_px = int(self._cfg.tile_px)
        size = int(parsed.size)

        for (x, y), terrain in parsed.terrain_by_xy.items():
            pm = self._pix.get(terrain) or self._pix.get("Unknown")
            if not pm:
                continue
            if pm.width() != tile_px or pm.height() != tile_px:
                pm = pm.scaled(tile_px, tile_px, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.FastTransformation)

            it = _TileItem(pm, x=x, y=y, terrain=terrain)
            # Match ASCII layout: y increases upward. Put y=size at top row (y=GS -> row 0).
            it.setPos((x - 1) * tile_px, (size - y) * tile_px)
            self._scene.addItem(it)

        self._scene.setSceneRect(QRectF(0, 0, size * tile_px, size * tile_px))
        # Ensure the newly-rendered map is visible even after previous pan/zoom.
        self.resetTransform()
        self.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def set_system_map(self, parsed: ParsedSystemMap, *, details_by_xy: dict[tuple[int, int], str] | None = None) -> None:
        self._scene.clear()

        tile_px = int(self._cfg.tile_px)
        w = int(parsed.width)
        h = int(parsed.height)

        for (col, row), obj in parsed.object_by_xy.items():
            pm = self._sys_pix.get(obj) or self._sys_pix.get("Unknown")
            if not pm:
                continue
            if pm.width() != tile_px or pm.height() != tile_px:
                pm = pm.scaled(
                    tile_px,
                    tile_px,
                    Qt.AspectRatioMode.IgnoreAspectRatio,
                    Qt.TransformationMode.FastTransformation,
                )

            # Tooltip uses map coordinates like "H04"
            col_letter = chr(ord("A") + (col - 1))
            coord = f"{col_letter}{row:02d}"
            it = _TileItem(pm, x=col, y=row, terrain=obj)
            detail = details_by_xy.get((col, row)) if details_by_xy else None
            it.setToolTip(f"{coord} — {detail or obj}")
            # System maps are rendered top-down: row 01 at top.
            it.setPos((col - 1) * tile_px, (row - 1) * tile_px)
            self._scene.addItem(it)

        self._scene.setSceneRect(QRectF(0, 0, w * tile_px, h * tile_px))
        # Ensure the newly-rendered map is visible even after previous pan/zoom.
        self.resetTransform()
        self.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def wheelEvent(self, event) -> None:  # type: ignore[override]
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            # Ctrl+wheel zoom
            angle = event.angleDelta().y()
            factor = 1.15 if angle > 0 else (1 / 1.15)
            self.scale(factor, factor)
            event.accept()
            return
        super().wheelEvent(event)

