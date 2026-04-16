from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontDatabase, QIntValidator
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QStatusBar,
    QTextEdit,
    QToolBar,
    QVBoxLayout,
    QWidget,
    QSplitter,
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
from sd_order_gui.integrations.stellar_dominion.db_access import (
    connect_sd,
    resolve_sd_db_paths,
)


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

        self._report = QTextEdit()
        self._report.setReadOnly(True)
        self._report.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self._report.setFont(_fixed_width_font(point_size=10))

        splitter = QSplitter()
        splitter.addWidget(self._list)
        splitter.addWidget(self._report)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        self.setCentralWidget(splitter)

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

        self._list.currentRowChanged.connect(self._on_entity_selected)  # type: ignore[arg-type]

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

        if self._list.count() > 0 and self._list.currentRow() < 0:
            self._list.setCurrentRow(0)

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

    def _on_entity_selected(self) -> None:
        ent = self._get_selected_entity()
        if not ent:
            self._report.setPlainText("")
            return

        # Load the most recently-seen report for this entity.
        conn = db.connect(self._paths.db_path)
        try:
            row = conn.execute(
                """
                SELECT last_seen_report_path, last_seen_turn, account_number
                FROM entities
                WHERE entity_type = ? AND entity_id = ?
                """,
                (str(ent["entity_type"]), str(ent["entity_id"])),
            ).fetchone()
        finally:
            conn.close()

        if not row:
            self._report.setPlainText("")
            return

        report_path = Path(str(row["last_seen_report_path"]))
        if not report_path.exists():
            self._report.setPlainText(
                f"Report not found on disk:\n{report_path}\n\n"
                "This can happen if the file was moved/deleted after import."
            )
            return

        text = report_path.read_text(encoding="utf-8", errors="replace")
        header = (
            f"{str(ent['entity_type']).upper()} {ent['name']} ({ent['entity_id']})\n"
            f"Last seen turn: {row['last_seen_turn']}\n"
            f"Report: {report_path}\n"
            "\n"
        )
        self._report.setPlainText(header + text)

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
        dlg = ComposeOrdersDialog(
            parent=self,
            initial_entity=ent,
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

        self._sd_conn = None
        try:
            sd_repo = Path(settings.sd_repo_path)
            paths = resolve_sd_db_paths(
                sd_repo_root=sd_repo,
                state_db_path=getattr(settings, "sd_state_db_path", ""),
                universe_db_path=getattr(settings, "sd_universe_db_path", ""),
            )
            if paths.state_db.exists():
                self._sd_conn = connect_sd(paths=paths)
        except Exception:
            self._sd_conn = None

        self._command = QComboBox()
        allowed = self._allowed_commands_for_subject(subject_type)
        for spec in allowed:
            self._command.addItem(f"{spec.command} — {spec.description}", spec.command)

        self._stack = QStackedWidget()
        self._param_pages: dict[str, QWidget] = {}
        self._param_readers: dict[str, callable] = {}

        form = QFormLayout()
        form.addRow("Command", self._command)
        form.addRow("Parameters", self._stack)

        self._command.currentIndexChanged.connect(self._on_command_changed)  # type: ignore[arg-type]
        self._build_param_pages()
        self._on_command_changed()

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)  # type: ignore[arg-type]
        buttons.rejected.connect(self.reject)  # type: ignore[arg-type]

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addWidget(buttons)
        self.setLayout(layout)

    def closeEvent(self, event):  # type: ignore[override]
        if self._sd_conn is not None:
            try:
                self._sd_conn.close()
            except Exception:
                pass
        self._sd_conn = None
        super().closeEvent(event)

    def _allowed_commands_for_subject(self, subject_type: str):
        if subject_type in ("ship", "prefect"):
            return self._catalog.allowed_for_subject(subject_type=subject_type)
        if subject_type in ("starbase", "port", "outpost"):
            # Stellar Dominion treats base subjects separately; for now expose only
            # the explicitly base-oriented commands + base combat lists.
            base_cmds = {"BUILD", "SETBUY", "SETSELL", "TARGET", "DEFEND"}
            if subject_type == "starbase":
                base_cmds.add("RENAMEBASE")
            return sorted(
                [c for c in self._catalog.commands.values() if c.command in base_cmds],
                key=lambda s: s.command,
            )
        return self._catalog.allowed_for_subject(subject_type="ship")

    def _build_param_pages(self) -> None:
        # One page per command, based on the param type in the catalog.
        # Each page registers a reader that returns raw_params in a shape accepted by SD's parse_order().
        for cmd, spec in sorted(self._catalog.commands.items()):
            page, reader = self._make_page_for_param_type(spec.params)
            self._param_pages[cmd] = page
            self._param_readers[cmd] = reader
            self._stack.addWidget(page)

        # Fallback page (shouldn't happen)
        fallback = QWidget()
        fl = QHBoxLayout()
        fl.addWidget(QLabel("No parameters"))
        fallback.setLayout(fl)
        self._param_pages["__fallback__"] = fallback
        self._param_readers["__fallback__"] = lambda: None
        self._stack.addWidget(fallback)

    def _make_page_for_param_type(self, param_type: str) -> tuple[QWidget, callable]:
        w = QWidget()
        form = QFormLayout()
        w.setLayout(form)

        def int_line(label: str, placeholder: str = "") -> QLineEdit:
            le = QLineEdit()
            le.setValidator(QIntValidator(0, 2_000_000_000, le))
            le.setPlaceholderText(placeholder)
            form.addRow(label, le)
            return le

        def db_combo(label: str, rows: list[tuple[int, str]], placeholder: str) -> tuple[QComboBox, QLineEdit]:
            """
            Returns (combo, manual_id_line). If manual id is set, it overrides combo.
            """
            cb = QComboBox()
            cb.addItem(placeholder, None)
            for _id, text in rows:
                cb.addItem(text, int(_id))
            manual = QLineEdit()
            manual.setValidator(QIntValidator(1, 2_000_000_000, manual))
            manual.setPlaceholderText("or enter ID manually")
            form.addRow(label, cb)
            form.addRow("", manual)
            return cb, manual

        def pick_id(cb: QComboBox, manual: QLineEdit) -> int | None:
            if manual.text().strip():
                return int(manual.text())
            data = cb.currentData()
            return int(data) if data is not None else None

        bases: list[tuple[int, str]] = []
        bodies: list[tuple[int, str]] = []
        systems: list[tuple[int, str]] = []
        goods: list[tuple[int, str]] = []
        if self._sd_conn is not None:
            try:
                bases = [
                    (int(r["base_id"]), f"{r['name']} ({r['base_id']})")
                    for r in self._sd_conn.execute(
                        "SELECT base_id, name FROM starbases ORDER BY name"
                    ).fetchall()
                ]
            except Exception:
                bases = []
            try:
                bodies = [
                    (int(r["body_id"]), f"{r['name']} ({r['body_id']})")
                    for r in self._sd_conn.execute(
                        "SELECT body_id, name FROM universe.celestial_bodies ORDER BY name"
                    ).fetchall()
                ]
            except Exception:
                bodies = []
            try:
                systems = [
                    (int(r["system_id"]), f"{r['name']} ({r['system_id']})")
                    for r in self._sd_conn.execute(
                        "SELECT system_id, name FROM universe.star_systems ORDER BY name"
                    ).fetchall()
                ]
            except Exception:
                systems = []
            try:
                goods = [
                    (int(r["item_id"]), f"{r['name']} ({r['item_id']})")
                    for r in self._sd_conn.execute(
                        "SELECT item_id, name FROM universe.trade_goods ORDER BY name"
                    ).fetchall()
                ]
            except Exception:
                goods = []

        if param_type == "none":
            form.addRow(QLabel("No parameters for this command."))
            return w, (lambda: None)

        if param_type == "integer":
            sb = QSpinBox()
            sb.setRange(0, 1_000_000)
            form.addRow("Value", sb)
            return w, (lambda sb=sb: int(sb.value()))

        if param_type == "optional_integer":
            sb = QSpinBox()
            sb.setRange(1, 1_000_000)
            sb.setValue(1)
            form.addRow("Duration (default 1)", sb)
            hint = QLabel("Leave as 1 for the default active scan duration.")
            hint.setWordWrap(True)
            form.addRow("", hint)
            return w, (lambda sb=sb: int(sb.value()))

        if param_type == "doctrine_choice":
            cb = QComboBox()
            cb.addItem("aggressive")
            cb.addItem("defensive")
            cb.addItem("evasive")
            form.addRow("Doctrine", cb)
            return w, (lambda cb=cb: {"doctrine": str(cb.currentText())})

        if param_type == "list_op":
            op = QComboBox()
            op.addItem("add")
            op.addItem("remove")
            op.addItem("clear")
            entry_type = QComboBox()
            entry_type.addItem("ship")
            entry_type.addItem("base")
            entry_type.addItem("faction")
            entry_id = QLineEdit()
            entry_id.setValidator(QIntValidator(1, 2_000_000_000, entry_id))
            entry_id.setPlaceholderText("numeric id (required for add/remove)")
            form.addRow("Operation", op)
            form.addRow("Entry type", entry_type)
            form.addRow("Entry ID", entry_id)

            def reader():
                op_val = str(op.currentText())
                if op_val == "clear":
                    return {"op": "clear", "type": None, "id": None}
                if not entry_id.text().strip():
                    return None
                return {
                    "op": op_val,
                    "type": str(entry_type.currentText()),
                    "id": int(entry_id.text()),
                }

            return w, reader

        if param_type == "coordinate":
            le = QLineEdit()
            le.setPlaceholderText("e.g. M13, H04, D08")
            form.addRow("Coordinate", le)
            return w, (lambda le=le: le.text().strip() or None)

        if param_type == "base_id":
            if bases:
                cb, manual = db_combo("Base", bases, "(select a base)")
                return w, (lambda cb=cb, manual=manual: pick_id(cb, manual))
            le = int_line("Base ID", "numeric id")
            return w, (lambda le=le: int(le.text()) if le.text().strip() else None)

        if param_type == "body_id":
            if bodies:
                cb, manual = db_combo("Body", bodies, "(select a body)")
                return w, (lambda cb=cb, manual=manual: pick_id(cb, manual))
            le = int_line("Body ID", "numeric id")
            return w, (lambda le=le: int(le.text()) if le.text().strip() else None)

        if param_type == "system_id":
            if systems:
                cb, manual = db_combo("System", systems, "(select a system)")
                return w, (lambda cb=cb, manual=manual: pick_id(cb, manual))
            le = int_line("System ID", "numeric id")
            return w, (lambda le=le: int(le.text()) if le.text().strip() else None)

        if param_type == "trade_order":
            if bases:
                base_cb, base_manual = db_combo("Base", bases, "(select a base)")
            else:
                base_cb, base_manual = None, None
                base_line = int_line("Base ID", "e.g. 45687590")

            if goods:
                item_cb, item_manual = db_combo("Trade good", goods, "(select an item)")
            else:
                item_cb, item_manual = None, None
                item_line = int_line("Item ID", "e.g. 100102")

            qty = QSpinBox()
            qty.setRange(1, 1_000_000)
            install = QCheckBox("Install immediately (if applicable)")
            form.addRow("Quantity", qty)
            form.addRow("", install)

            def reader():
                if bases:
                    base_id = pick_id(base_cb, base_manual)  # type: ignore[arg-type]
                else:
                    base_id = int(base_line.text()) if base_line.text().strip() else None

                if goods:
                    item_id = pick_id(item_cb, item_manual)  # type: ignore[arg-type]
                else:
                    item_id = int(item_line.text()) if item_line.text().strip() else None

                if not base_id or not item_id:
                    return None
                return {
                    "base": int(base_id),
                    "item": int(item_id),
                    "qty": int(qty.value()),
                    "install": bool(install.isChecked()),
                }

            return w, reader

        if param_type == "land_order":
            if bodies:
                body_cb, body_manual = db_combo("Body", bodies, "(select a body)")
                body_line = None
            else:
                body_cb, body_manual = None, None
                body_line = int_line("Body ID", "e.g. 247985")
            x = QSpinBox()
            y = QSpinBox()
            x.setRange(1, 31)
            y.setRange(1, 31)
            form.addRow("X", x)
            form.addRow("Y", y)

            def reader():
                if bodies:
                    body_id = pick_id(body_cb, body_manual)  # type: ignore[arg-type]
                else:
                    body_id = int(body_line.text()) if body_line and body_line.text().strip() else None
                if not body_id:
                    return None
                return {"body": int(body_id), "x": int(x.value()), "y": int(y.value())}

            return w, reader

        if param_type == "message_order":
            target = int_line("Target ID", "e.g. 78901234")
            text = QLineEdit()
            text.setPlaceholderText("message text")
            form.addRow("Text", text)

            def reader():
                if not target.text().strip():
                    return None
                return {"target": int(target.text()), "text": text.text()}

            return w, reader

        if param_type == "makeofficer_order":
            ship_id = int_line("Ship ID", "defaults to this ship if left blank")
            crew_type = int_line("Crew Type ID", "e.g. 401")
            name = QLineEdit()
            name.setPlaceholderText("(optional) officer name")
            form.addRow("Name (optional)", name)

            def reader():
                if not crew_type.text().strip():
                    return None
                out = {"crew_type": int(crew_type.text())}
                if ship_id.text().strip():
                    out["ship"] = int(ship_id.text())
                if name.text().strip():
                    out["name"] = name.text().strip()
                return out

            return w, reader

        if param_type == "component_order":
            comp = int_line("Component ID", "e.g. 130")
            qty = QSpinBox()
            qty.setRange(1, 1_000_000)
            form.addRow("Quantity", qty)

            def reader():
                if not comp.text().strip():
                    return None
                return {"component": int(comp.text()), "qty": int(qty.value())}

            return w, reader

        if param_type == "build_order":
            mod = int_line("Module ID", "e.g. 510")
            qty = QSpinBox()
            qty.setRange(1, 1_000_000)
            form.addRow("Quantity", qty)

            def reader():
                if not mod.text().strip():
                    return None
                return {"module": int(mod.text()), "qty": int(qty.value())}

            return w, reader

        if param_type == "setprice_order":
            item = int_line("Item ID", "e.g. 100101")
            price = QSpinBox()
            price.setRange(0, 1_000_000_000)
            form.addRow("Price", price)

            def reader():
                if not item.text().strip():
                    return None
                return {"item": int(item.text()), "price": int(price.value())}

            return w, reader

        if param_type == "rename_id_name":
            target_id = int_line("ID", "numeric id to rename")
            name = QLineEdit()
            name.setPlaceholderText("new name")
            form.addRow("New name", name)

            def reader():
                if not target_id.text().strip() or not name.text().strip():
                    return None
                return {"id": int(target_id.text()), "name": name.text().strip()}

            return w, reader

        if param_type == "rename_officer":
            ship_id = int_line("Ship ID", "e.g. 52589098")
            crew_num = QSpinBox()
            crew_num.setRange(1, 10_000)
            name = QLineEdit()
            name.setPlaceholderText("new name")
            form.addRow("Crew number", crew_num)
            form.addRow("New name", name)

            def reader():
                if not ship_id.text().strip() or not name.text().strip():
                    return None
                return {
                    "ship": int(ship_id.text()),
                    "crew_number": int(crew_num.value()),
                    "name": name.text().strip(),
                }

            return w, reader

        if param_type == "changefaction_order":
            faction_id = QSpinBox()
            faction_id.setRange(0, 1_000_000_000)
            reason = QLineEdit()
            reason.setPlaceholderText("(optional) reason")
            form.addRow("Faction ID", faction_id)
            form.addRow("Reason (optional)", reason)
            return w, (lambda: {"faction": int(faction_id.value()), "reason": reason.text().strip()})

        if param_type == "moderator_order":
            text = QLineEdit()
            text.setPlaceholderText("request text")
            form.addRow("Text", text)
            return w, (lambda: text.text().strip() or None)

        # Unknown param type: allow raw text entry (still validated on save).
        le = QLineEdit()
        le.setPlaceholderText("Enter parameters as text")
        form.addRow("Params", le)
        return w, (lambda le=le: le.text().strip() or None)

    def _on_command_changed(self) -> None:
        cmd = str(self._command.currentData())
        page = self._param_pages.get(cmd, self._param_pages["__fallback__"])
        self._stack.setCurrentWidget(page)

    def get_order(self) -> DraftOrder | None:
        if self.exec() != QDialog.DialogCode.Accepted:
            return None
        cmd = str(self._command.currentData())
        reader = self._param_readers.get(cmd, self._param_readers["__fallback__"])
        raw_params = reader()
        return DraftOrder(command=cmd, raw_params=raw_params)


class ComposeOrdersDialog(QDialog):
    def __init__(
        self,
        *,
        parent,
        initial_entity: dict | None,
        settings,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Compose Orders")
        self.resize(900, 600)

        self._settings = settings

        self._entity_combo = QComboBox()
        self._entity_combo.currentIndexChanged.connect(self._on_entity_combo_changed)  # type: ignore[arg-type]

        self._entity_summary = QLineEdit()
        self._entity_summary.setReadOnly(True)

        self._account = QLineEdit("")
        self._account.setPlaceholderText("Account number (secret)")

        self._orders = QListWidget()

        add_btn = QPushButton("Add order…")
        add_btn.clicked.connect(self._add_order)  # type: ignore[arg-type]

        remove_btn = QPushButton("Remove selected")
        remove_btn.clicked.connect(self._remove_selected)  # type: ignore[arg-type]

        save_btn = QPushButton("Save YAML…")
        save_btn.clicked.connect(self._save_yaml)  # type: ignore[arg-type]

        top_form = QFormLayout()
        top_form.addRow("Subject", self._entity_combo)
        top_form.addRow("Selected", self._entity_summary)
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

        self._load_entities(initial_entity=initial_entity)

    def _display_for_order(self, order: DraftOrder) -> str:
        if order.raw_params is None:
            return order.command
        if isinstance(order.raw_params, dict):
            parts = ", ".join(f"{k}={v}" for k, v in order.raw_params.items())
            return f"{order.command}: {parts}"
        return f"{order.command}: {order.raw_params}"

    def _add_order(self) -> None:
        ent = self._current_entity()
        if not ent:
            QMessageBox.warning(self, "No subject selected", "Select a subject first.")
            return
        dlg = AddOrderDialog(parent=self, subject_type=str(ent["entity_type"]), settings=self._settings)
        order = dlg.get_order()
        if not order:
            return
        item = QListWidgetItem(self._display_for_order(order))
        item.setData(Qt.ItemDataRole.UserRole, {"command": order.command, "raw_params": order.raw_params})
        self._orders.addItem(item)

    def _remove_selected(self) -> None:
        for it in self._orders.selectedItems():
            row = self._orders.row(it)
            self._orders.takeItem(row)

    def _save_yaml(self) -> None:
        ent = self._current_entity()
        if not ent:
            QMessageBox.warning(self, "No subject selected", "Select a subject first.")
            return

        account = self._account.text().strip()
        if not account.isdigit():
            QMessageBox.warning(self, "Account required", "Enter a numeric account number.")
            return

        catalog, parser_mod = load_catalog_from_sd_repo(Path(self._settings.sd_repo_path))
        _ = catalog  # reserved for richer UI later

        draft = DraftOrderFile(
            game=self._settings.game_id,
            account=account,
            subject_type=str(ent["entity_type"]),
            subject_id=str(ent["entity_id"]),
            orders=[],
        )

        parsed_orders: list[tuple[str, object]] = []
        for i in range(self._orders.count()):
            it = self._orders.item(i)
            payload = it.data(Qt.ItemDataRole.UserRole) if it else None
            if not isinstance(payload, dict) or "command" not in payload:
                QMessageBox.warning(self, "Internal error", f"Order {i+1} is missing data.")
                return

            cmd = str(payload["command"]).strip().upper()
            params = payload.get("raw_params", None)
            parse_order = getattr(parser_mod, "parse_order")
            command, parsed_params, error = parse_order(cmd, params)
            if error:
                QMessageBox.warning(self, "Invalid order", f"Order {i+1}: {error}\n\nCommand: {cmd}")
                return
            parsed_orders.append((command, parsed_params))

        content = build_orders_yaml(draft, parsed_orders=parsed_orders)

        default_name = default_output_filename(
            entity_name=str(ent["name"]),
            entity_id=str(ent["entity_id"]),
            turn_number=str(ent["last_seen_turn"]),
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

    def _load_entities(self, *, initial_entity: dict | None) -> None:
        self._entity_combo.clear()
        paths = get_paths()
        conn = db.connect(paths.db_path)
        try:
            db.init_db(conn)
            rows = conn.execute(
                """
                SELECT entity_type, entity_id, name, account_number, last_seen_turn
                FROM entities
                ORDER BY entity_type, name
                """
            ).fetchall()
        finally:
            conn.close()

        initial_key = None
        if initial_entity:
            initial_key = (str(initial_entity.get("entity_type")), str(initial_entity.get("entity_id")))

        initial_index = 0
        for idx, r in enumerate(rows):
            label = f"{r['entity_type'].upper():8} {r['name']} ({r['entity_id']}) — {r['last_seen_turn']}"
            payload = {
                "entity_type": r["entity_type"],
                "entity_id": r["entity_id"],
                "name": r["name"],
                "account_number": r["account_number"],
                "last_seen_turn": r["last_seen_turn"],
            }
            self._entity_combo.addItem(label, payload)
            if initial_key and (str(r["entity_type"]), str(r["entity_id"])) == initial_key:
                initial_index = idx

        if self._entity_combo.count() > 0:
            self._entity_combo.setCurrentIndex(initial_index)
        self._on_entity_combo_changed()

    def _current_entity(self) -> dict | None:
        payload = self._entity_combo.currentData()
        return payload if isinstance(payload, dict) else None

    def _on_entity_combo_changed(self) -> None:
        ent = self._current_entity()
        if not ent:
            self._entity_summary.setText("")
            return
        self._entity_summary.setText(
            f"{str(ent['entity_type']).upper()} {ent['name']} ({ent['entity_id']}) — last seen {ent['last_seen_turn']}"
        )
        acct = ent.get("account_number")
        if acct and (not self._account.text().strip()):
            self._account.setText(str(acct))


def run_app() -> None:
    app = QApplication([])
    w = MainWindow()
    w.show()
    raise SystemExit(app.exec())


def _fixed_width_font(*, point_size: int = 10) -> QFont:
    """
    Prefer the platform's default fixed font for proper ASCII alignment.
    Fall back to common monospace faces.
    """
    font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
    if font and font.fixedPitch():
        font.setPointSize(point_size)
        return font

    for family in ("Consolas", "Cascadia Mono", "Courier New", "Liberation Mono", "Monospace"):
        f = QFont(family)
        if f.exactMatch():
            f.setFixedPitch(True)
            f.setPointSize(point_size)
            return f

    font = QFont()
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setFixedPitch(True)
    font.setPointSize(point_size)
    return font

