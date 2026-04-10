from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QStatusBar,
    QToolBar,
)

from sd_order_gui.core import db
from sd_order_gui.core.paths import get_paths
from sd_order_gui.core.turn_ingest import ingest_turn_files


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Stellar Dominion - Order GUI (WIP)")
        self.resize(1000, 650)

        self._paths = get_paths()
        self._paths.data_dir.mkdir(parents=True, exist_ok=True)
        self._paths.turns_dir.mkdir(parents=True, exist_ok=True)

        self._list = QListWidget()
        self._list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.setCentralWidget(self._list)

        self.setStatusBar(QStatusBar())

        tb = QToolBar("Main")
        tb.setMovable(False)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, tb)

        import_action = tb.addAction("Import turns…")
        import_action.triggered.connect(self.import_turns)  # type: ignore[arg-type]

        refresh_action = tb.addAction("Refresh entities")
        refresh_action.triggered.connect(self.refresh_entities)  # type: ignore[arg-type]

        self.refresh_entities()

    def refresh_entities(self) -> None:
        self._list.clear()
        conn = db.connect(self._paths.db_path)
        try:
            db.init_db(conn)
            rows = conn.execute(
                """
                SELECT entity_type, entity_id, name, last_seen_turn
                FROM entities
                ORDER BY entity_type, name
                """
            ).fetchall()
        finally:
            conn.close()

        for r in rows:
            self._list.addItem(
                f"{r['entity_type'].upper():8} {r['name']} ({r['entity_id']})  — last seen {r['last_seen_turn']}"
            )

    def import_turns(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Select turn report text files",
            str(Path.home()),
            "Text files (*.txt);;All files (*.*)",
        )
        if not files:
            return

        conn = db.connect(self._paths.db_path)
        try:
            results = ingest_turn_files(
                conn=conn,
                turns_root=self._paths.turns_dir,
                files=[Path(f) for f in files],
            )
        finally:
            conn.close()

        ok = [r for r in results if not r.error]
        bad = [r for r in results if r.error]

        for r in results:
            if r.error:
                self._list.addItem(f"ERROR: {r.original_path} — {r.error}")
            else:
                self._list.addItem(
                    f"Imported turn {r.turn_number}: {r.original_path.name} → {r.stored_path}"
                )

        self.statusBar().showMessage(
            f"Imported {len(ok)} file(s), {len(bad)} failed.", 10_000
        )

        if bad:
            msg = "\n".join(
                f"- {b.original_path.name}: {b.error}" for b in bad if b.error
            )
            QMessageBox.warning(
                self,
                "Some files failed to import",
                f"{len(bad)} file(s) could not be imported:\n\n{msg}",
            )

        self.refresh_entities()


def run_app() -> None:
    app = QApplication([])
    w = MainWindow()
    w.show()
    raise SystemExit(app.exec())

