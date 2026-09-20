"""Browse the preset library: section > group > list, narrowed by tier, chips and search."""
import html

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMenu, QMessageBox, QPushButton, QSplitter, QStackedWidget, QTableWidget,
    QTableWidgetItem, QTextBrowser, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from app import db
from app.preset_dialogs import AddEntriesDialog, NewListDialog

RESULT_LIMIT = 500
PREVIEW_CHARS = 130
FLAG_TEXT = {
    "needs_reference": "Assumes a supplied reference character",
    "possibly_truncated": "Possibly truncated in the source file",
    "near_duplicate": "Very similar to another entry",
}


class LibraryBrowser(QWidget):
    library_reset = Signal()   # emitted after Reset library, so other tabs can go back to their defaults

    def __init__(self, conn, parent=None):
        super().__init__(parent)
        self.conn = conn
        self._scope = None
        self._chips = {}
        self._items_by_key = {}
        self._rebuilding = False
        self._current_entry = None

        root = QVBoxLayout(self)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Show:"))
        self.tier_boxes = {}
        for tier in db.TIERS:
            box = QCheckBox(db.TIER_LABELS[tier])
            box.setToolTip(db.TIER_HELP[tier])
            box.setChecked(db.get_setting(conn, f"library_tier_{tier}", "1") == "1")
            box.toggled.connect(self._on_filter_toggled)
            self.tier_boxes[tier] = box
            bar.addWidget(box)
        bar.addSpacing(16)
        self.adult_box = QCheckBox("Adult content")
        self.adult_box.setToolTip("Include lists marked explicit (hidden by default)")
        self.adult_box.setChecked(db.get_setting(conn, "library_show_adult", "0") == "1")
        self.adult_box.toggled.connect(self._on_filter_toggled)
        bar.addWidget(self.adult_box)
        self.disabled_box = QCheckBox("Disabled lists and entries")
        self.disabled_box.setChecked(db.get_setting(conn, "library_show_disabled", "0") == "1")
        self.disabled_box.toggled.connect(self._on_filter_toggled)
        bar.addWidget(self.disabled_box)
        bar.addSpacing(16)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search inside the selected section, group or list...")
        self.search_edit.setClearButtonEnabled(True)
        bar.addWidget(self.search_edit, stretch=1)
        self.reset_btn = QPushButton("Reset library...")
        self.reset_btn.setToolTip("Put the library back exactly as it was when the app was first installed")
        self.reset_btn.clicked.connect(self.reset_library_dialog)
        bar.addWidget(self.reset_btn)
        root.addLayout(bar)

        splitter = QSplitter(Qt.Horizontal)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setMinimumWidth(340)
        self.tree.currentItemChanged.connect(self._on_tree_selection)
        splitter.addWidget(self.tree)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        self.scope_label = QLabel("")
        font = self.scope_label.font()
        font.setBold(True)
        font.setPointSize(font.pointSize() + 2)
        self.scope_label.setFont(font)
        head = QHBoxLayout()
        head.addWidget(self.scope_label, stretch=1)
        self.new_list_btn = QPushButton("New list...")
        self.new_list_btn.setToolTip("Create your own list of presets")
        self.new_list_btn.clicked.connect(self.new_list_dialog)
        head.addWidget(self.new_list_btn)
        self.add_entries_btn = QPushButton("Add entries...")
        self.add_entries_btn.setToolTip("Add your own entries to the selected list")
        self.add_entries_btn.clicked.connect(self.add_entries_dialog)
        head.addWidget(self.add_entries_btn)
        self.list_menu_btn = QPushButton("This list")
        self.list_menu = QMenu(self.list_menu_btn)
        self.list_menu.aboutToShow.connect(self._build_list_menu)
        self.list_menu_btn.setMenu(self.list_menu)
        head.addWidget(self.list_menu_btn)
        right_layout.addLayout(head)

        self.chip_bar = QWidget()
        self.chip_layout = QHBoxLayout(self.chip_bar)
        self.chip_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(self.chip_bar)

        self.stack = QStackedWidget()
        overview = QWidget()
        overview_layout = QVBoxLayout(overview)
        overview_layout.setContentsMargins(0, 0, 0, 0)
        self.overview_hint = QLabel("")
        self.overview_hint.setWordWrap(True)
        overview_layout.addWidget(self.overview_hint)
        self.overview_table = QTableWidget(0, 5)
        self.overview_table.setHorizontalHeaderLabels(["List", "Group", "Tier", "Entries", "Chips"])
        self.overview_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.overview_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.overview_table.verticalHeader().setVisible(False)
        self.overview_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.overview_table.cellDoubleClicked.connect(self._on_overview_activated)
        overview_layout.addWidget(self.overview_table, stretch=1)
        self.stack.addWidget(overview)

        entries_page = QSplitter(Qt.Vertical)
        self.entry_list = QListWidget()
        self.entry_list.currentItemChanged.connect(self._on_entry_changed)
        entries_page.addWidget(self.entry_list)
        detail_box = QWidget()
        detail_layout = QVBoxLayout(detail_box)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        self.detail = QTextBrowser()
        detail_layout.addWidget(self.detail, stretch=1)
        buttons = QHBoxLayout()
        self.copy_btn = QPushButton("Copy text")
        self.copy_btn.clicked.connect(self._copy_text)
        buttons.addWidget(self.copy_btn)
        self.edit_btn = QPushButton("Edit...")
        self.edit_btn.setToolTip("Change an entry you added")
        self.edit_btn.clicked.connect(self.edit_entry_dialog)
        buttons.addWidget(self.edit_btn)
        self.delete_btn = QPushButton("Delete")
        self.delete_btn.setToolTip("Delete an entry you added")
        self.delete_btn.clicked.connect(self.delete_entry)
        buttons.addWidget(self.delete_btn)
        self.enabled_box = QCheckBox("Enabled (used by the builder and wildcard)")
        self.enabled_box.toggled.connect(self._on_entry_enabled_toggled)
        buttons.addWidget(self.enabled_box)
        buttons.addStretch(1)
        detail_layout.addLayout(buttons)
        entries_page.addWidget(detail_box)
        entries_page.setStretchFactor(0, 3)
        entries_page.setStretchFactor(1, 1)
        self.stack.addWidget(entries_page)
        right_layout.addWidget(self.stack, stretch=1)

        self.status_label = QLabel("")
        right_layout.addWidget(self.status_label)
        splitter.addWidget(right)
        splitter.setSizes([380, 1020])
        root.addWidget(splitter, stretch=1)

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(250)
        self._search_timer.timeout.connect(self.refresh_results)
        self.search_edit.textChanged.connect(lambda _text: self._search_timer.start())

        self.refresh_tree()
        self.refresh_results()

    # --- filters and tree ---------------------------------------------------

    def _selected_tiers(self):
        return [t for t, box in self.tier_boxes.items() if box.isChecked()]

    def _on_filter_toggled(self, _checked=False):
        for tier, box in self.tier_boxes.items():
            db.set_setting(self.conn, f"library_tier_{tier}", "1" if box.isChecked() else "0")
        db.set_setting(self.conn, "library_show_adult", "1" if self.adult_box.isChecked() else "0")
        db.set_setting(self.conn, "library_show_disabled", "1" if self.disabled_box.isChecked() else "0")
        self.refresh_tree()
        self.refresh_results()

    def refresh_tree(self):
        previous_key = self._scope["key"] if self._scope else None
        self._rebuilding = True
        self.tree.clear()
        self._items_by_key = {}
        for section, groups in db.sections_tree(self.conn, self._selected_tiers(), self.adult_box.isChecked(),
                                                self.disabled_box.isChecked()):
            label = db.SECTION_LABELS[section]
            all_lists = [c for _, cols in groups for c in cols]
            sec_item = self._make_item(f"{label}  ({sum(c['n'] for c in all_lists):,})", {
                "kind": "section", "key": f"section:{section}", "label": label, "collections": all_lists})
            self.tree.addTopLevelItem(sec_item)
            for group, cols in groups:
                group_item = self._make_item(f"{group}  ({sum(c['n'] for c in cols):,})", {
                    "kind": "group", "key": f"group:{section}:{group}", "label": f"{label}  ›  {group}",
                    "collections": cols})
                sec_item.addChild(group_item)
                for c in cols:
                    off = "" if c["enabled"] else "  ·  off"
                    list_item = self._make_item(f"{c['display_name']}  ({c['n']:,})  ·  {c['tier']}{off}", {
                        "kind": "list", "key": f"list:{c['id']}", "label": f"{label}  ›  {group}  ›  {c['display_name']}",
                        "collections": [c]})
                    group_item.addChild(list_item)
        self.tree.expandToDepth(0)
        item = self._items_by_key.get(previous_key)
        if item is not None:
            self.tree.setCurrentItem(item)
            self._set_scope(item.data(0, Qt.UserRole), reset_chips=False)
        else:
            self._scope = None
            self.scope_label.setText("")
            self._build_chips()
            self._update_scope_buttons()
        self._rebuilding = False

    def _make_item(self, text, data):
        item = QTreeWidgetItem([text])
        data = dict(data, ids=[c["id"] for c in data["collections"]])
        item.setData(0, Qt.UserRole, data)
        self._items_by_key[data["key"]] = item
        return item

    def _on_tree_selection(self, current, _previous):
        if self._rebuilding or current is None:
            return
        self._set_scope(current.data(0, Qt.UserRole), reset_chips=True)
        self.refresh_results()

    def _set_scope(self, data, reset_chips):
        self._scope = data
        self.scope_label.setText(data["label"])
        if reset_chips:
            self._build_chips()
        self._update_scope_buttons()

    # --- chips --------------------------------------------------------------

    def _build_chips(self):
        while self.chip_layout.count():
            child = self.chip_layout.takeAt(0)
            if child.widget() is not None:
                child.widget().deleteLater()
        self._chips = {}
        names = []
        if self._scope and self._scope["kind"] == "list":
            names = db.collection_facet_names(self.conn, self._scope["ids"][0])
        for name in names:
            self.chip_layout.addWidget(QLabel(db.FACET_LABELS.get(name, name.title()) + ":"))
            box = QComboBox()
            box.setMinimumWidth(170)
            box.currentIndexChanged.connect(self._on_chip_changed)
            self._chips[name] = box
            self.chip_layout.addWidget(box)
        self.chip_layout.addStretch(1)
        self.chip_bar.setVisible(bool(names))

    def _active_facets(self):
        return {name: box.currentData() for name, box in self._chips.items() if box.currentData() is not None}

    def _on_chip_changed(self, _index):
        if not self._rebuilding:
            self.refresh_results()

    def _refresh_chip_options(self, ids, facets, query, include_disabled):
        counts = db.facet_counts(self.conn, ids, list(self._chips), facets, query, include_disabled)
        self._rebuilding = True
        for name, box in self._chips.items():
            selected = facets.get(name)
            values = dict(counts[name])
            if selected is not None and selected not in values:
                values[selected] = 0
            ordered = sorted(values.items(), key=lambda kv: (kv[0] == "other", -kv[1], kv[0]))
            box.clear()
            box.addItem(f"All  ({sum(values.values()):,})", None)
            for value, n in ordered:
                box.addItem(f"{value}  ({n:,})", value)
            box.setCurrentIndex(max(0, box.findData(selected)) if selected is not None else 0)
        self._rebuilding = False

    # --- results ------------------------------------------------------------

    def refresh_results(self):
        scope = self._scope
        query = self.search_edit.text().strip()
        if scope is None:
            self._show_overview(None)
            return
        if scope["kind"] != "list" and not query:
            self._show_overview(scope)
            return
        ids = scope["ids"]
        single = scope["kind"] == "list"
        include_disabled = self.disabled_box.isChecked()
        facets = self._active_facets() if single else {}
        if single:
            self._refresh_chip_options(ids, facets, query, include_disabled)
        total = db.count_entries(self.conn, ids, facets, query, include_disabled)
        rows = db.search_entries(self.conn, ids, facets, query, include_disabled, RESULT_LIMIT)
        self._fill_entries(rows, single)
        note = f"{total:,} match" if (query or facets) else f"{total:,} entries"
        if total > RESULT_LIMIT:
            note += f"  -  showing the first {RESULT_LIMIT}; narrow it with the chips or the search box"
        self.status_label.setText(note)

    def _fill_entries(self, rows, single_list):
        self.entry_list.blockSignals(True)
        self.entry_list.clear()
        for r in rows:
            body = f"{r['label']}  —  {r['text']}" if r["label"] else r["text"]
            preview = body if len(body) <= PREVIEW_CHARS else body[:PREVIEW_CHARS - 1] + "…"
            prefix = "" if single_list else f"[{r['display_name']}]  "
            item = QListWidgetItem(prefix + preview + ("" if r["enabled"] else "   (disabled)"))
            item.setData(Qt.UserRole, r["id"])
            item.setToolTip(body)
            if not r["enabled"]:
                item.setForeground(QBrush(QColor("#888888")))
            self.entry_list.addItem(item)
        self.entry_list.blockSignals(False)
        self.stack.setCurrentIndex(1)
        if self.entry_list.count():
            self.entry_list.setCurrentRow(0)
        else:
            self._show_detail(None)

    def _show_overview(self, scope):
        self.stack.setCurrentIndex(0)
        if scope is None:
            self.overview_hint.setText("Pick a section, group or list on the left. Type in the search box to search "
                                       "everything inside whatever is selected.")
            self.overview_table.setRowCount(0)
            self.status_label.setText("")
            return
        cols = scope["collections"]
        total = sum(c["n"] for c in cols)
        self.overview_hint.setText(f"{len(cols)} lists, {total:,} entries. Double-click a list to browse it, or type "
                                   f"in the search box to search all of {scope['label'].split('›')[-1].strip()}.")
        self.overview_table.setRowCount(len(cols))
        for row, c in enumerate(cols):
            chips = ", ".join(db.FACET_LABELS.get(n, n.title()) for n in db.collection_facet_names(self.conn, c["id"]))
            cells = [c["display_name"], c["grp"], db.TIER_LABELS[c["tier"]], f"{c['n']:,}", chips or "-"]
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if col == 0:
                    item.setData(Qt.UserRole, c["id"])
                if col == 3:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.overview_table.setItem(row, col, item)
        self.status_label.setText(f"{len(cols)} lists, {total:,} entries")

    def _on_overview_activated(self, row, _col):
        cid = self.overview_table.item(row, 0).data(Qt.UserRole)
        item = self._items_by_key.get(f"list:{cid}")
        if item is not None:
            self.tree.setCurrentItem(item)

    # --- entry detail -------------------------------------------------------

    def _on_entry_changed(self, current, _previous):
        self._show_detail(current.data(Qt.UserRole) if current is not None else None)

    def _show_detail(self, entry_id):
        self._current_entry = db.get_entry(self.conn, entry_id) if entry_id else None
        e = self._current_entry
        self.copy_btn.setEnabled(e is not None)
        mine = e is not None and e["origin"] == "user"
        self.edit_btn.setEnabled(mine)
        self.delete_btn.setEnabled(mine)
        self.enabled_box.blockSignals(True)
        self.enabled_box.setEnabled(e is not None)
        self.enabled_box.setChecked(bool(e["enabled"]) if e else False)
        self.enabled_box.blockSignals(False)
        if e is None:
            self.detail.setHtml("")
            return
        esc = html.escape
        parts = []
        if e["label"]:
            parts.append(f"<p><b>{esc(e['label'])}</b></p>")
        parts.append(f"<p>{esc(e['text'])}</p>")
        if e["vibe"]:
            parts.append(f"<p><i>Vibe:</i> {esc(e['vibe'])}</p>")
        meta = [f"From: {db.SECTION_LABELS[e['section']]} › {esc(e['grp'])} › {esc(e['display_name'])} "
                f"· {db.TIER_LABELS[e['tier']]}"]
        if e["origin"] == "user":
            meta.append("Added by you")
        if e["facets"]:
            meta.append("Chips: " + " · ".join(f"{esc(db.FACET_LABELS.get(k, k))}: {esc(v)}" for k, v in e["facets"].items()))
        if e["covers"]:
            meta.append("Also fills: " + ", ".join(db.SECTION_LABELS[s] for s in e["covers"]))
        for flag in e["flags"]:
            if flag in FLAG_TEXT:
                meta.append(FLAG_TEXT[flag])
        parts.append("<p style='color:#666'>" + "<br>".join(meta) + "</p>")
        self.detail.setHtml("".join(parts))

    # --- your own presets ---------------------------------------------------

    def _single_list(self):
        """The list that is selected in the tree, or None when a section or group is selected."""
        if self._scope and self._scope["kind"] == "list":
            return self._scope["collections"][0]
        return None

    def _update_scope_buttons(self):
        self.add_entries_btn.setEnabled(self._single_list() is not None)
        self.list_menu_btn.setEnabled(self._single_list() is not None)

    def _build_list_menu(self):
        self.list_menu.clear()
        c = self._single_list()
        if c is None:
            return
        on = bool(c["enabled"])
        self.list_menu.addAction("Turn this list off" if on else "Turn this list on", lambda: self.set_list_enabled(not on))
        if db.is_user_collection(c["id"]):
            self.list_menu.addSeparator()
            self.list_menu.addAction("Delete this list...", self.delete_list)

    def new_list_dialog(self):
        section = self._scope["collections"][0]["section"] if self._scope and self._scope["collections"] else "subject"
        dialog = NewListDialog(self.conn, self, section)
        if dialog.exec() == NewListDialog.Accepted:
            spec = dialog.spec()
            try:
                self.create_list(**spec)
            except ValueError as error:
                QMessageBox.warning(self, "New list", str(error))

    def create_list(self, name, section, slot, tier, texts, grp=None, content_level="general", covers=()):
        """Create your own list and select it in the tree. Returns its id."""
        list_id = db.create_user_collection(self.conn, name, section, slot, tier, texts, grp, content_level, covers)
        self.refresh_tree()
        item = self._items_by_key.get(f"list:{list_id}")
        if item is not None:
            self.tree.setCurrentItem(item)
        return list_id

    def add_entries_dialog(self):
        c = self._single_list()
        if c is None:
            return
        dialog = AddEntriesDialog(self.conn, c, self)
        if dialog.exec() == AddEntriesDialog.Accepted:
            self.add_entries(c["id"], dialog.lines())

    def add_entries(self, collection_id, texts):
        added, skipped = db.add_user_entries(self.conn, collection_id, texts)
        self.refresh_tree()
        self.refresh_results()
        self.status_label.setText(f"Added {len(added)}" + (f", skipped {len(skipped)} already in the list" if skipped else ""))
        return added, skipped

    def edit_entry_dialog(self):
        e = self._current_entry
        if e is None or e["origin"] != "user":
            return
        text, ok = QInputDialog.getMultiLineText(self, "Edit entry", "Text:", e["text"])
        if ok:
            self.edit_entry(e["id"], text)

    def edit_entry(self, entry_id, text):
        result = db.update_user_entry(self.conn, entry_id, text)
        if result == "ok":
            self.refresh_results()
        else:
            QMessageBox.warning(self, "Edit entry", {"empty": "An entry cannot be empty.",
                                                     "duplicate": "That text is already in this list."}.get(result, "That entry cannot be edited."))
        return result

    def delete_entry(self):
        e = self._current_entry
        if e is None or e["origin"] != "user":
            return
        if QMessageBox.question(self, "Delete entry", "Delete this entry?\n\n" + e["text"][:200]) == QMessageBox.Yes:
            self.remove_entry(e["id"])

    def remove_entry(self, entry_id):
        db.delete_user_entry(self.conn, entry_id)
        self.refresh_tree()
        self.refresh_results()

    def set_list_enabled(self, enabled):
        c = self._single_list()
        if c is not None:
            db.set_collection_enabled(self.conn, c["id"], enabled)
            self.refresh_tree()
            self.refresh_results()

    def delete_list(self):
        c = self._single_list()
        if c is None or not db.is_user_collection(c["id"]):
            return
        if QMessageBox.question(self, "Delete list", f"Delete your list \"{c['display_name']}\" and its {c['n']} entries?") == QMessageBox.Yes:
            self.remove_list(c["id"])

    def remove_list(self, collection_id):
        db.delete_user_collection(self.conn, collection_id)
        self._scope = None
        self.refresh_tree()
        self.refresh_results()

    # --- reset to default ---------------------------------------------------

    def reset_library_dialog(self):
        gone = db.reset_preview(self.conn)
        lines = ["Put the library back exactly as it was when the app was first installed?", "", "This removes:"]
        lines.append(f"• lists and entries you added ({gone['user_lists']} lists, {gone['user_entries']} entries)")
        lines.append(f"• your on/off changes ({gone['switched_off_lists']} lists and {gone['switched_off_entries']} entries switched off)")
        lines.append("• your saved options (filters and Builder settings)")
        folder = db.backup_folder(self.conn)
        lines += ["", "The built-in presets are restored from the original data, which is never changed.", "Your saved prompts are kept."]
        if folder is not None:
            lines.append(f"A backup copy of your current library is saved first in:\n{folder}")
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("Reset library")
        box.setText("\n".join(lines))
        reset = box.addButton("Reset library", QMessageBox.DestructiveRole)
        cancel = box.addButton(QMessageBox.Cancel)
        box.setDefaultButton(cancel)
        box.exec()
        if box.clickedButton() is reset:
            self.perform_reset()

    def perform_reset(self):
        """Reset the library to the first-install state and bring this tab (and the others) back to their defaults."""
        try:
            result = db.reset_library(self.conn)
        except FileNotFoundError as error:
            QMessageBox.warning(self, "Reset library", f"The original preset data was not found, so nothing was changed.\n\n{error}")
            return None
        except Exception as error:   # the reset is one transaction: the library is as it was before
            QMessageBox.critical(self, "Reset library", f"The reset failed and nothing was changed.\n\n{error}")
            return None
        for box, default in [(b, True) for b in self.tier_boxes.values()] + [(self.adult_box, False), (self.disabled_box, False)]:
            box.blockSignals(True)
            box.setChecked(default)
            box.blockSignals(False)
        self.search_edit.blockSignals(True)
        self.search_edit.clear()
        self.search_edit.blockSignals(False)
        self._scope = None
        self.refresh_tree()
        self.refresh_results()
        self.library_reset.emit()
        where = f"  Backup: {result['backup']}" if result["backup"] else ""
        self.status_label.setText(f"Library reset to the first-install state.{where}")
        return result

    def _copy_text(self):
        if self._current_entry:
            QApplication.clipboard().setText(self._current_entry["text"])

    def _on_entry_enabled_toggled(self, checked):
        e = self._current_entry
        if e is None:
            return
        db.set_entry_enabled(self.conn, e["id"], checked)
        e["enabled"] = int(checked)
        item = self.entry_list.currentItem()
        if item is not None:
            text = item.text().replace("   (disabled)", "")
            item.setText(text if checked else text + "   (disabled)")
            item.setForeground(QBrush(QColor("#000000" if checked else "#888888")))
        self.refresh_tree()
