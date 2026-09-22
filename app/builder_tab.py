"""The prompt builder: one row per section (and per subject detail), a wildcard button, and the finished prompt."""
import random

import time

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFrame, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QPushButton, QScrollArea, QSizePolicy, QSpinBox, QSplitter, QTextBrowser,
    QInputDialog, QMessageBox, QTextEdit, QVBoxLayout, QWidget,
)

from app import composer, db, wildcard

ROW_TEXT_CHARS = 120
LIST_PREVIEW_CHARS = 150
PICKER_LIMIT = 500
DETAIL_LEVELS = [("Minimal", 0.4), ("Normal", 1.0), ("Rich", 1.6)]
BUILDER_SECTIONS = ["clothing", "action", "environment", "camera", "lighting", "style"]
# rows that can be switched to "None": left out of every prompt (e.g. a character LoRA already fixes the eye colour)
NONE_ROWS = {
    "subject:eye colour": "None — leave eye colour out of the prompt",
    "subject:tattoos": "None — leave tattoos out of the prompt",
    "subject:piercings": "None — leave piercings out of the prompt",
}   # first item in that row's list
NONE_ID = "__none__"
NONE_ROW_TEXT = "None — left out of the prompt"
EMPTY_PROMPT_HINT = "Press Wildcard, or Choose... on any row, to start building a prompt."


def _short(text, limit):
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


class PickerDialog(QDialog):
    """Choose one entry by hand: pick a list (or all lists of the section), narrow with search, choose an entry."""

    def __init__(self, conn, title, section, slots, show_adult, parent=None, none_label=None, none_selected=False):
        super().__init__(parent)
        self.conn = conn
        self.selected_id = None
        self._none_label = none_label
        self._none_selected = none_selected
        self.setWindowTitle(title)
        self.resize(900, 620)
        self._lists = db.picker_collections(conn, section, slots, show_adult)

        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        self.list_combo = QComboBox()
        total = sum(c["n"] for c in self._lists)
        self.list_combo.addItem(f"All lists ({total})", None)
        for c in self._lists:
            self.list_combo.addItem(f"{c['grp']}  ›  {c['display_name']}  [{db.TIER_LABELS[c['tier']]}]  ({c['n']})", c["id"])
        self.list_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.list_combo.setMinimumContentsLength(38)
        top.addWidget(self.list_combo, stretch=1)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search...")
        self.search.setClearButtonEnabled(True)
        top.addWidget(self.search, stretch=1)
        layout.addLayout(top)

        self.entries = QListWidget()
        self.entries.setUniformItemSizes(True)
        layout.addWidget(self.entries, stretch=3)
        self.count_label = QLabel("")
        layout.addWidget(self.count_label)
        self.detail = QTextBrowser()
        self.detail.setMaximumHeight(130)
        layout.addWidget(self.detail)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Use this")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.ok_button = buttons.button(QDialogButtonBox.Ok)

        self.list_combo.currentIndexChanged.connect(self.refresh)
        self.search.textChanged.connect(self.refresh)
        self.entries.currentItemChanged.connect(self._on_current)
        self.entries.itemDoubleClicked.connect(lambda _item: self._accept())
        self.refresh()
        self.search.setFocus()

    def refresh(self, *_args):
        chosen = self.list_combo.currentData()
        ids = [chosen] if chosen else [c["id"] for c in self._lists]
        query = self.search.text().strip()
        rows = db.search_entries(self.conn, ids, query=query, limit=PICKER_LIMIT)
        total = db.count_entries(self.conn, ids, query=query)
        self.entries.clear()
        if self._none_label:
            item = QListWidgetItem(self._none_label)
            item.setData(Qt.UserRole, NONE_ID)
            item.setToolTip("Nothing is added to the prompt for this row, and the wildcard never draws it "
                            "(for example when a character LoRA already fixes it).")
            font = item.font()
            font.setItalic(True)
            item.setFont(font)
            self.entries.addItem(item)
        for row in rows:
            item = QListWidgetItem(_short(row["text"], LIST_PREVIEW_CHARS))
            item.setData(Qt.UserRole, row["id"])
            item.setToolTip(row["text"])
            self.entries.addItem(item)
        self.count_label.setText(f"{total} entries" + (f" (showing the first {len(rows)}; search to narrow)" if total > len(rows) else ""))
        if self.entries.count():
            first_real = 1 if self._none_label and rows else 0
            self.entries.setCurrentRow(0 if self._none_selected else first_real)
        else:
            self.detail.clear()
            self.ok_button.setEnabled(False)

    def _on_current(self, current, _previous):
        self.ok_button.setEnabled(current is not None)
        self.detail.setPlainText(current.toolTip() if current else "")

    def _accept(self):
        item = self.entries.currentItem()
        if item is not None:
            self.selected_id = item.data(Qt.UserRole)
            self.accept()


class PickRow(QWidget):
    """One line: label, the chosen text, and Lock / Choose / Reroll / Clear."""

    def __init__(self, key, label, on_choose, on_reroll, on_clear, on_change, parent=None):
        super().__init__(parent)
        self.key = key
        self.entry = None
        self.none = False
        self._notes = []
        self._warning = ""
        self._buttons = []
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 2, 0, 2)
        grid.setHorizontalSpacing(8)
        self.lock_box = QCheckBox("Lock")
        self.lock_box.setToolTip("Keep this pick when the wildcard runs")
        self.lock_box.toggled.connect(lambda _checked: on_change())
        grid.addWidget(self.lock_box, 0, 0)
        self.label = QLabel(label)
        self.label.setMinimumWidth(96)
        font = self.label.font()
        font.setBold(True)
        self.label.setFont(font)
        grid.addWidget(self.label, 0, 1)
        self.text = QLabel("")
        self.text.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        grid.addWidget(self.text, 0, 2)
        grid.setColumnStretch(2, 1)
        for column, (caption, callback) in enumerate((("Choose...", on_choose), ("Reroll", on_reroll), ("Clear", on_clear)), 3):
            button = QPushButton(caption)
            button.clicked.connect(lambda _checked=False, cb=callback, k=key: cb(k))
            grid.addWidget(button, 0, column)
            self._buttons.append(button)
        self.hint = QLabel("")
        self.hint.setStyleSheet("color: palette(mid); font-style: italic;")
        self.hint.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.hint.hide()
        grid.addWidget(self.hint, 1, 2, 1, 4)
        self.set_entry(None)

    def is_locked(self):
        return self.lock_box.isChecked()

    def set_none(self, flag):
        """Switch the row to None (left out of the prompt) or back to normal."""
        self.none = flag
        self.lock_box.setEnabled(not flag)
        self._buttons[1].setEnabled(not flag)   # Reroll; Choose (to change it) and Clear (to switch None off) stay usable
        if flag:
            self.entry = None
            self.text.setText(NONE_ROW_TEXT)
            self.text.setToolTip("")
            self._notes, self._warning = [], ""
            self._show_hint()
        else:
            self.set_entry(None)

    def set_warning(self, text):
        self._warning = text
        self._show_hint()

    def _show_hint(self):
        notes = self._notes + ([self._warning] if self._warning else [])
        self.hint.setText("; ".join(notes))
        self.hint.setVisible(bool(notes))

    def set_entry(self, entry):
        if self.none:
            return
        self.entry = entry
        self._warning = ""
        if entry is None:
            self.text.setText("—")
            self.text.setToolTip("")
            self._notes = []
            self._show_hint()
            return
        self.text.setText(_short(entry["text"], ROW_TEXT_CHARS))
        self.text.setToolTip(f"{entry['display_name']} ({db.TIER_LABELS[entry['tier']]})\n\n{entry['text']}")
        notes = []
        covers = [db.SECTION_LABELS[s] for s in entry["covers"] if s != entry["section"]]
        if entry["slot"] == wildcard.ADULT_SLOT:
            notes.append("Adult scene: describes the whole picture, so clothing is left out")
        elif covers:
            notes.append("Also describes: " + ", ".join(covers))
        self._notes = notes
        self._show_hint()


class BuilderTab(QWidget):
    saved_changed = Signal(int)   # id of the prompt that was just saved or updated (the Saved tab shows it)

    def __init__(self, conn, parent=None):
        super().__init__(parent)
        self.conn = conn
        self.loaded_saved = None   # {'id', 'name'} of the saved prompt this work came from
        self.rng = random.Random()
        self.rows = {}
        self._loading = True

        root = QVBoxLayout(self)
        root.addLayout(self._build_toolbar())
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_rows())
        splitter.addWidget(self._build_preview())
        splitter.setSizes([820, 640])
        root.addWidget(splitter, stretch=1)
        for key in NONE_ROWS:
            if db.get_setting(self.conn, "builder_none_" + key, "0") == "1":
                self.rows[key].set_none(True)
        self._loading = False
        self.refresh_preview()

    # --- construction -------------------------------------------------------

    def _build_toolbar(self):
        bar = QHBoxLayout()
        self.wildcard_btn = QPushButton("Wildcard")
        self.wildcard_btn.setToolTip("Fill every section that is not locked with a random, matching pick")
        font = self.wildcard_btn.font()
        font.setBold(True)
        font.setPointSize(font.pointSize() + 2)
        self.wildcard_btn.setFont(font)
        self.wildcard_btn.setMinimumHeight(38)
        self.wildcard_btn.setMinimumWidth(130)
        self.wildcard_btn.clicked.connect(self.run_wildcard)
        bar.addWidget(self.wildcard_btn)
        bar.addSpacing(12)

        bar.addWidget(QLabel("Detail:"))
        self.detail_combo = QComboBox()
        for name, _factor in DETAIL_LEVELS:
            self.detail_combo.addItem(name)
        self.detail_combo.setToolTip("How many optional subject details (hair style, makeup, tattoos...) the wildcard adds")
        self.detail_combo.setCurrentIndex(int(db.get_setting(self.conn, "builder_detail", "1")))
        self.detail_combo.currentIndexChanged.connect(self._save_options)
        bar.addWidget(self.detail_combo)
        bar.addSpacing(8)

        self.tier_boxes = {}
        for tier in ("basic", "detailed"):
            box = QCheckBox(db.TIER_LABELS[tier])
            box.setToolTip(db.TIER_HELP[tier])
            box.setChecked(db.get_setting(self.conn, f"builder_tier_{tier}", "1") == "1")
            box.toggled.connect(self._save_options)
            self.tier_boxes[tier] = box
            bar.addWidget(box)
        bar.addSpacing(8)

        self.scenes_box = QCheckBox("Whole-scene presets")
        self.scenes_box.setToolTip("Let the wildcard use presets that already describe several sections at once "
                                   "(movie posters, artistic shots, themed scenes). The paragraph structure then varies.")
        self.scenes_box.setChecked(db.get_setting(self.conn, "builder_scenes", "0") == "1")
        self.scenes_box.toggled.connect(self._save_options)
        bar.addWidget(self.scenes_box)
        bar.addSpacing(8)

        self.adult_box = QCheckBox("Adult content")
        self.adult_box.setToolTip("Allow the adult scenes list (off by default)")
        self.adult_box.setChecked(db.get_setting(self.conn, "builder_adult", "0") == "1")
        self.adult_box.toggled.connect(self._save_options)
        bar.addWidget(self.adult_box)
        self.adult_pct_label = QLabel("how often:")
        bar.addWidget(self.adult_pct_label)
        self.adult_pct = QSpinBox()
        self.adult_pct.setRange(0, 100)
        self.adult_pct.setSuffix(" %")
        self.adult_pct.setValue(int(db.get_setting(self.conn, "builder_adult_pct", "30")))
        self.adult_pct.setToolTip("Chance that the wildcard's action comes from the adult scenes list")
        self.adult_pct.valueChanged.connect(self._save_options)
        bar.addWidget(self.adult_pct)
        self._sync_adult_controls()

        bar.addStretch(1)
        unlock = QPushButton("Unlock all")
        unlock.clicked.connect(self.unlock_all)
        bar.addWidget(unlock)
        clear = QPushButton("Clear all")
        clear.setToolTip("Empty every row that is not locked")
        clear.clicked.connect(self.clear_all)
        bar.addWidget(clear)
        return bar

    def _build_rows(self):
        holder = QWidget()
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 6, 0)

        subject_box = QGroupBox(db.SECTION_LABELS["subject"])
        subject_layout = QVBoxLayout(subject_box)
        head = QHBoxLayout()
        head.addStretch(1)
        reroll_all = QPushButton("Reroll filled details")
        reroll_all.setToolTip("New picks for every unlocked subject detail that currently has one")
        reroll_all.clicked.connect(self._reroll_subject)
        head.addWidget(reroll_all)
        subject_layout.addLayout(head)
        for key, label, _slots, _chance in wildcard.SUBJECT_ROWS:
            self._add_row(subject_layout, "subject:" + key, label)
        layout.addWidget(subject_box)

        for section in BUILDER_SECTIONS:
            box = QGroupBox(db.SECTION_LABELS[section])
            box_layout = QVBoxLayout(box)
            self._add_row(box_layout, section, db.SECTION_LABELS[section], show_label=False)
            layout.addWidget(box)
        layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(holder)
        return scroll

    def _add_row(self, layout, key, label, show_label=True):
        row = PickRow(key, label, self.choose_row, self.reroll_row, self.clear_row, self.refresh_preview)
        row.label.setVisible(show_label)   # the group box already carries the section name
        self.rows[key] = row
        layout.addWidget(row)

    def _build_preview(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(6, 0, 0, 0)
        title = QLabel("Prompt")
        font = title.font()
        font.setBold(True)
        font.setPointSize(font.pointSize() + 2)
        title.setFont(font)
        layout.addWidget(title)
        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setPlaceholderText(EMPTY_PROMPT_HINT)
        layout.addWidget(self.preview, stretch=1)
        bottom = QHBoxLayout()
        self.copy_btn = QPushButton("Copy prompt")
        self.copy_btn.clicked.connect(self.copy_prompt)
        bottom.addWidget(self.copy_btn)
        self.save_btn = QPushButton("Save prompt...")
        self.save_btn.setToolTip("Keep this prompt and its picks in the Saved tab")
        self.save_btn.clicked.connect(self.save_prompt_dialog)
        bottom.addWidget(self.save_btn)
        self.update_btn = QPushButton("Update saved")
        self.update_btn.clicked.connect(self.update_saved)
        self.update_btn.hide()
        bottom.addWidget(self.update_btn)
        self.status = QLabel("")
        bottom.addWidget(self.status, stretch=1)
        layout.addLayout(bottom)
        return panel

    # --- options ------------------------------------------------------------

    def reset_to_defaults(self):
        """After Reset library: first-install options, no locks, no picks, no None rows (their saved settings are gone)."""
        self._loading = True
        self.detail_combo.setCurrentIndex(1)
        for box in self.tier_boxes.values():
            box.setChecked(True)
        self.scenes_box.setChecked(False)
        self.adult_box.setChecked(False)
        self.adult_pct.setValue(30)
        for row in self.rows.values():
            row.lock_box.setChecked(False)
            row.set_none(False)
            row.set_entry(None)
        self._loading = False
        self._sync_adult_controls()
        self.refresh_preview()

    def _sync_adult_controls(self):
        visible = self.adult_box.isChecked()
        self.adult_pct.setVisible(visible)
        self.adult_pct_label.setVisible(visible)

    def _save_options(self, *_args):
        self._sync_adult_controls()
        if self._loading:
            return
        db.set_setting(self.conn, "builder_detail", str(self.detail_combo.currentIndex()))
        for tier, box in self.tier_boxes.items():
            db.set_setting(self.conn, f"builder_tier_{tier}", "1" if box.isChecked() else "0")
        db.set_setting(self.conn, "builder_scenes", "1" if self.scenes_box.isChecked() else "0")
        db.set_setting(self.conn, "builder_adult", "1" if self.adult_box.isChecked() else "0")
        db.set_setting(self.conn, "builder_adult_pct", str(self.adult_pct.value()))

    def tiers(self):
        chosen = tuple(t for t, box in self.tier_boxes.items() if box.isChecked())
        return chosen or ("basic", "detailed")

    def skip_rows(self):
        """Rows set to None: the wildcard leaves them out and avoids anything that names them."""
        return {key for key, row in self.rows.items() if row.none}

    def _set_row_none(self, key, flag):
        self.rows[key].set_none(flag)
        db.set_setting(self.conn, "builder_none_" + key, "1" if flag else "0")
        self.refresh_preview()

    def _detail_factor(self):
        return DETAIL_LEVELS[self.detail_combo.currentIndex()][1]

    # --- picks <-> rows -----------------------------------------------------

    def current_picks(self, locked_only=False):
        """{section: [entries]} from the rows (only locked rows when locked_only)."""
        picks = {}
        for key, row in self.rows.items():
            if row.entry is None or (locked_only and not row.is_locked()):
                continue
            section = "subject" if key.startswith("subject:") else key
            picks.setdefault(section, []).append(row.entry)
        return picks

    def _apply(self, picks):
        """Show a wildcard result: unlocked rows take the new picks (or empty), locked rows stay as they are."""
        new = {}
        for section, entries in picks.items():
            for entry in entries:
                new[wildcard.row_key(entry)] = entry
        for key, row in self.rows.items():
            if not row.is_locked() and not row.none:
                row.set_entry(new.get(key))
        self.refresh_preview()

    # --- actions ------------------------------------------------------------

    def run_wildcard(self):
        picks = wildcard.wildcard_picks(
            self.conn, self.rng, tiers=self.tiers(), show_adult=self.adult_box.isChecked(),
            scenes=self.scenes_box.isChecked(), locked=self.current_picks(locked_only=True),
            detail=self._detail_factor(), adult_chance=self.adult_pct.value() / 100, skip_rows=self.skip_rows())
        self._apply(picks)

    def choose_row(self, key):
        section, slots = self._row_scope(key)
        label = self.rows[key].label.text()
        dialog = PickerDialog(self.conn, f"Choose {label.lower()}", section, slots, self.adult_box.isChecked(), self,
                              none_label=NONE_ROWS.get(key), none_selected=self.rows[key].none)
        if dialog.exec() == QDialog.Accepted and dialog.selected_id:
            self.apply_choice(key, dialog.selected_id)

    def apply_choice(self, key, entry_id):
        """Use a picked entry for a row; NONE_ID switches the row to None, any real entry switches None off."""
        row = self.rows[key]
        if entry_id == NONE_ID:
            self._set_row_none(key, True)
            return
        if row.none:
            self._set_row_none(key, False)
        row.set_entry(db.get_entry(self.conn, entry_id))
        self.refresh_preview()

    def reroll_row(self, key):
        entry = wildcard.reroll(self.conn, self.rng, key, self.current_picks(), self.tiers(),
                                self.adult_box.isChecked(), self.adult_pct.value() / 100, self.skip_rows())
        if entry is not None:
            self.rows[key].set_entry(entry)
            self.refresh_preview()

    def clear_row(self, key):
        if self.rows[key].none:
            self._set_row_none(key, False)   # Clear takes a None row back to a normal, empty one
            return
        self.rows[key].set_entry(None)
        self.refresh_preview()

    def _reroll_subject(self):
        for key, row in self.rows.items():
            if key.startswith("subject:") and row.entry is not None and not row.is_locked():
                entry = wildcard.reroll(self.conn, self.rng, key, self.current_picks(), self.tiers(), skip_rows=self.skip_rows())
                if entry is not None:
                    row.set_entry(entry)
        self.refresh_preview()

    def clear_all(self):
        for row in self.rows.values():
            if not row.is_locked():
                row.set_entry(None)
        self.refresh_preview()

    def unlock_all(self):
        for row in self.rows.values():
            row.lock_box.setChecked(False)

    def _row_scope(self, key):
        if key.startswith("subject:"):
            row_key = key.split(":", 1)[1]
            slots = next(s for k, _label, s, _chance in wildcard.SUBJECT_ROWS if k == row_key)
            return "subject", slots
        return key, None

    # --- prompt -------------------------------------------------------------

    def prompt_text(self):
        return composer.compose(self.current_picks())

    def _update_warnings(self):
        """Flag rows picked by hand that clash with something else: text that names an eye colour, tattoo or piercing
        while that row is None, a pose (or other detail) that names clothing while the Clothing row has its own pick,
        and a pose (or other detail) that names a bust size/shape or build while a Subject body/bust row has its own
        pick."""
        eye_none = self.rows["subject:eye colour"].none
        tattoos_none = self.rows["subject:tattoos"].none
        piercings_none = self.rows["subject:piercings"].none
        clothing_picked = self.rows["clothing"].entry is not None
        body_rows = ("subject:body", "subject:bust size", "subject:bust shape")
        body_shape_picked = any(self.rows[k].entry is not None for k in body_rows)
        for key, row in self.rows.items():
            warnings = []
            if row.entry is not None:
                if eye_none and composer.mentions_eye_colour(row.entry["text"]):
                    warnings.append("Names an eye colour although Eye colour is None")
                if tattoos_none and composer.mentions_tattoos(row.entry["text"]):
                    warnings.append("Names a tattoo although Tattoos is None")
                if piercings_none and composer.mentions_piercings(row.entry["text"]):
                    warnings.append("Names a piercing although Piercings is None")
                if clothing_picked and key != "clothing" and composer.entry_mentions_clothing(row.entry):
                    warnings.append("Names clothing, which may clash with the Clothing row")
                if body_shape_picked and key not in body_rows and composer.entry_mentions_body_shape(row.entry):
                    warnings.append("Names a bust size/shape or build, which may clash with the Subject row")
            row.set_warning("; ".join(warnings))

    def refresh_preview(self):
        self._update_warnings()
        text = self.prompt_text()
        self.preview.setPlainText(text)
        self.status.setText(f"{len(text.split())} words" if text else "")

    def copy_prompt(self):
        text = self.prompt_text()
        if text:
            QApplication.clipboard().setText(text)
            self.status.setText(f"Copied ({len(text.split())} words)")

    # --- saved prompts ------------------------------------------------------

    def _state(self):
        rows = {key: row.entry for key, row in self.rows.items() if row.entry is not None}
        locks = [key for key, row in self.rows.items() if row.is_locked() and row.entry is not None]
        return rows, locks, sorted(self.skip_rows())

    def _set_loaded(self, saved_id, name):
        self.loaded_saved = {"id": saved_id, "name": name} if saved_id else None
        self.update_btn.setVisible(bool(saved_id))
        if saved_id:
            self.update_btn.setToolTip(f"Replace the saved prompt \"{name}\" with what you have now")

    def save_prompt_dialog(self):
        if not self.prompt_text():
            QMessageBox.information(self, "Save prompt", "There is no prompt to save yet.")
            return
        default = self.loaded_saved["name"] + " (copy)" if self.loaded_saved else "Prompt " + time.strftime("%d %b %H:%M")
        name, ok = QInputDialog.getText(self, "Save prompt", "Name:", text=default)
        if ok and name.strip():
            self.save_prompt(name)

    def save_prompt(self, name, notes=""):
        """Save the current prompt and picks as a new saved prompt. Returns its id."""
        rows, locks, none_rows = self._state()
        saved_id = db.save_prompt(self.conn, name, self.prompt_text(), rows, locks, none_rows, notes)
        self._set_loaded(saved_id, " ".join(name.split()))
        self.status.setText(f"Saved as \"{self.loaded_saved['name']}\"")
        self.saved_changed.emit(saved_id)
        return saved_id

    def update_saved(self):
        if not self.loaded_saved:
            return False
        rows, locks, none_rows = self._state()
        try:
            done = db.update_saved_prompt(self.conn, self.loaded_saved["id"], self.prompt_text(), rows, locks, none_rows)
        except ValueError as error:
            QMessageBox.information(self, "Update saved", str(error))
            return False
        if not done:
            self._set_loaded(None, "")
            self.status.setText("That saved prompt no longer exists - use Save prompt...")
            return False
        self.status.setText(f"Updated \"{self.loaded_saved['name']}\"")
        self.saved_changed.emit(self.loaded_saved["id"])
        return True

    def load_saved(self, saved_id):
        """Put a saved prompt's picks back into the rows (locks and None rows too). Returns False if it is gone."""
        saved = db.get_saved_prompt(self.conn, saved_id)
        if saved is None:
            return False
        for key in NONE_ROWS:
            self._set_row_none(key, key in saved["none"])
        for key, row in self.rows.items():
            row.lock_box.setChecked(False)
            if not row.none:
                row.set_entry(saved["rows"].get(key))
        for key in saved["locks"]:
            if key in self.rows and self.rows[key].entry is not None:
                self.rows[key].lock_box.setChecked(True)
        self._set_loaded(saved["id"], saved["name"])
        self.refresh_preview()
        self.status.setText(f"Loaded \"{saved['name']}\"")
        return True

    def refresh_loaded_state(self):
        """After the Saved tab renamed or deleted things: keep the Update button honest."""
        if self.loaded_saved:
            saved = db.get_saved_prompt(self.conn, self.loaded_saved["id"])
            self._set_loaded(saved["id"], saved["name"]) if saved else self._set_loaded(None, "")
