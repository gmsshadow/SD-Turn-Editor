from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStatusBar,
    QToolBar,
    QVBoxLayout,
)

from sd_order_gui.core import db
from sd_order_gui.core.orders_model import DraftOrder, DraftOrderFile
from sd_order_gui.core.orders_yaml import (
    build_orders_yaml,
    default_output_filename,
    write_orders_file,
)
from sd_order_gui.core.paths import get_paths
from sd_order_gui.core.settings import load_settings
from sd_order_gui.core.turn_ingest import ingest_turn_files
from sd_order_gui.integrations.stellar_dominion.order_catalog import load_catalog_from_sd_repo


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Stellar Dominion - Order GUI (WIP)")
        self.resize(1000, 650)

        self._paths = get_paths()
        self._paths.data_dir.mkdir(parents=True, exist_ok=True)
        self._paths.turns_dir.mkdir(parents=True, exist_ok=True)
        self._settings = load_settings(self._paths.settings_path)

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

        compose_action = tb.addAction("Compose orders…")
        compose_action.triggered.connect(self.compose_orders)  # type: ignore[arg-type]

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

    def _get_selected_entity(self) -> dict | None:
        row = self._list.currentRow()
        if row < 0:
            return None
        conn = db.connect(self._paths.db_path)
        try:
            rows = conn.execute(
                """
                SELECT entity_type, entity_id, name, account_number, last_seen_turn
                FROM entities
                ORDER BY entity_type, name
                LIMIT 1 OFFSET ?
                """,
                (row,),
            ).fetchall()
        finally:
            conn.close()
        return dict(rows[0]) if rows else None

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

    def compose_orders(self) -> None:
        ent = self._get_selected_entity()
        if not ent:
            QMessageBox.information(self, "Select an entity", "Select a ship/prefect/base first.")
            return

        dlg = ComposeOrdersDialog(
            parent=self,
            entity_type=str(ent["entity_type"]),
            entity_id=str(ent["entity_id"]),
            entity_name=str(ent["name"]),
            account_number=str(ent["account_number"] or ""),
            turn_number=str(ent["last_seen_turn"]),
            settings=self._settings,
        )
        dlg.exec()


class AddOrderDialog(QDialog):
    def __init__(self, *, parent, subject_type: str, settings) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add Order")
        self._subject_type = subject_type
        self._settings = settings

        catalog, _ = load_catalog_from_sd_repo(Path(settings.sd_repo_path))
        self._catalog = catalog

        self._command = QComboBox()
        allowed = self._catalog.allowed_for_subject(subject_type=subject_type if subject_type in ("ship", "prefect") else "ship")
        for spec in allowed:
            self._command.addItem(f"{spec.command} — {spec.description}", spec.command)

        self._params = QLineEdit()
        self._params.setPlaceholderText("Parameters (depends on command). e.g. MOVE: M13, DOCK: 45687590")

        form = QFormLayout()
        form.addRow("Command", self._command)
        form.addRow("Params", self._params)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)  # type: ignore[arg-type]
        buttons.rejected.connect(self.reject)  # type: ignore[arg-type]

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addWidget(buttons)
        self.setLayout(layout)

    def get_order(self) -> DraftOrder | None:
        if self.exec() != QDialog.DialogCode.Accepted:
            return None
        cmd = str(self._command.currentData())
        params = self._params.text().strip()
        return DraftOrder(command=cmd, raw_params=(params if params else None))


class ComposeOrdersDialog(QDialog):
    def __init__(
        self,
        *,
        parent,
        entity_type: str,
        entity_id: str,
        entity_name: str,
        account_number: str,
        turn_number: str,
        settings,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Compose Orders")
        self.resize(900, 600)

        self._entity_type = entity_type
        self._entity_id = entity_id
        self._entity_name = entity_name
        self._turn_number = turn_number
        self._settings = settings

        self._account = QLineEdit(account_number)
        self._account.setPlaceholderText("Account number (secret)")

        self._orders = QListWidget()

        add_btn = QPushButton("Add order…")
        add_btn.clicked.connect(self._add_order)  # type: ignore[arg-type]

        remove_btn = QPushButton("Remove selected")
        remove_btn.clicked.connect(self._remove_selected)  # type: ignore[arg-type]

        save_btn = QPushButton("Save YAML…")
        save_btn.clicked.connect(self._save_yaml)  # type: ignore[arg-type]

        top_form = QFormLayout()
        top_form.addRow("Entity", QLineEdit(f"{entity_type} {entity_name} ({entity_id})"))
        top_form.addRow("Account", self._account)

        btn_row = QHBoxLayout()
        btn_row.addWidget(add_btn)
        btn_row.addWidget(remove_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(save_btn)

        layout = QVBoxLayout()
        layout.addLayout(top_form)
        layout.addWidget(self._orders)
        layout.addLayout(btn_row)
        self.setLayout(layout)

    def _add_order(self) -> None:
        dlg = AddOrderDialog(parent=self, subject_type=self._entity_type, settings=self._settings)
        order = dlg.get_order()
        if not order:
            return
        self._orders.addItem(f"{order.command} {order.raw_params or ''}".rstrip())

    def _remove_selected(self) -> None:
        for it in self._orders.selectedItems():
            row = self._orders.row(it)
            self._orders.takeItem(row)

    def _save_yaml(self) -> None:
        account = self._account.text().strip()
        if not account.isdigit():
            QMessageBox.warning(self, "Account required", "Enter a numeric account number.")
            return

        catalog, parser_mod = load_catalog_from_sd_repo(Path(self._settings.sd_repo_path))
        _ = catalog  # reserved for richer UI later

        draft = DraftOrderFile(
            game=self._settings.game_id,
            account=account,
            subject_type=self._entity_type,
            subject_id=self._entity_id,
            orders=[],
        )

        parsed_orders: list[tuple[str, object]] = []
        for i in range(self._orders.count()):
            line = self._orders.item(i).text()
            parts = line.split(None, 1)
            cmd = parts[0].strip().upper()
            params = parts[1].strip() if len(parts) > 1 else None
            parse_order = getattr(parser_mod, "parse_order")
            command, parsed_params, error = parse_order(cmd, params)
            if error:
                QMessageBox.warning(self, "Invalid order", f"Order {i+1}: {error}\n\nLine: {line}")
                return
            parsed_orders.append((command, parsed_params))

        content = build_orders_yaml(draft, parsed_orders=parsed_orders)

        default_name = default_output_filename(
            entity_name=self._entity_name,
            entity_id=self._entity_id,
            turn_number=self._turn_number,
        )
        output_dir = Path(get_paths().project_root) / self._settings.output_dir
        output_dir.mkdir(parents=True, exist_ok=True)

        path_str, _ = QFileDialog.getSaveFileName(
            self,
            "Save orders YAML",
            str(output_dir / default_name),
            "YAML files (*.yaml *.yml);;All files (*.*)",
        )
        if not path_str:
            return

        write_orders_file(Path(path_str), content)
        QMessageBox.information(self, "Saved", f"Saved orders to:\n{path_str}")


def run_app() -> None:
    app = QApplication([])
    w = MainWindow()
    w.show()
    raise SystemExit(app.exec())

