"""Dialogs for your own presets: add entries to a list, or create a new list."""
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)

from app import db

LINES_PLACEHOLDER = ("One entry per line.\nBullets and numbering are removed, and lines that are already in the list "
                     "are skipped.\nYou can also load a text file.")
TIER_TEXT = {
    "basic": "Basic - short, everyday phrases",
    "detailed": "Detailed - richer, more specific descriptions",
    "scene": "Scene - entries that already describe other sections too",
}


def parse_lines(text):
    """The non-empty lines of a block of text, cleaned the way entries are stored."""
    return [t for t in (db.normalise_entry_text(line) for line in text.splitlines()) if t]


class LinesEditor(QWidget):
    """A multi-line box for entries, a 'load from file' button, and a running count."""

    def __init__(self, existing_keys=None, on_change=None, parent=None):
        super().__init__(parent)
        self._existing = existing_keys or set()
        self._on_change = on_change
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.edit = QPlainTextEdit()
        self.edit.setPlaceholderText(LINES_PLACEHOLDER)
        self.edit.setMinimumHeight(220)
        layout.addWidget(self.edit, stretch=1)
        bottom = QHBoxLayout()
        load = QPushButton("Load from file...")
        load.clicked.connect(self.load_file)
        bottom.addWidget(load)
        self.count_label = QLabel("")
        bottom.addWidget(self.count_label, stretch=1)
        layout.addLayout(bottom)
        self._update_label()
        self.edit.textChanged.connect(self._changed)

    def lines(self):
        return parse_lines(self.edit.toPlainText())

    def new_lines(self):
        """Lines that would actually be added: not already in the list and not repeated in the box."""
        seen, out = set(self._existing), []
        for line in self.lines():
            key = db._entry_key(line)
            if key not in seen:
                seen.add(key)
                out.append(line)
        return out

    def load_file(self):
        name, _ = QFileDialog.getOpenFileName(self, "Load entries from a text file", "", "Text files (*.txt);;All files (*)")
        if not name:
            return
        text = Path(name).read_text(encoding="utf-8-sig", errors="replace")
        current = self.edit.toPlainText()
        self.edit.setPlainText((current.rstrip("\n") + "\n" if current.strip() else "") + text)

    def _update_label(self):
        lines, fresh = self.lines(), self.new_lines()
        skipped = len(lines) - len(fresh)
        self.count_label.setText(f"{len(fresh)} new entries" + (f"  -  {skipped} skipped (already there)" if skipped else ""))

    def _changed(self):
        self._update_label()
        if self._on_change:
            self._on_change()


class AddEntriesDialog(QDialog):
    def __init__(self, conn, collection, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add entries")
        self.resize(720, 460)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Add entries to:  <b>{collection['display_name']}</b>  "
                                f"({db.SECTION_LABELS[collection['section']]}, {db.TIER_LABELS[collection['tier']]})"))
        existing = {db._entry_key(r["text"]) for r in conn.execute("SELECT text FROM entries WHERE collection_id = ?", (collection["id"],))}
        self.editor = LinesEditor(existing, self._refresh_buttons)
        layout.addWidget(self.editor, stretch=1)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText("Add")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self._refresh_buttons()

    def _refresh_buttons(self):
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(bool(self.editor.new_lines()))

    def lines(self):
        return self.editor.lines()


class NewListDialog(QDialog):
    def __init__(self, conn, parent=None, section="subject"):
        super().__init__(parent)
        self.conn = conn
        self.setWindowTitle("New list")
        self.resize(720, 640)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("For example: My hair colours")
        self.name_edit.textChanged.connect(self._refresh)
        form.addRow("Name", self.name_edit)

        self.section_combo = QComboBox()
        for key in db.SECTION_ORDER:
            self.section_combo.addItem(db.SECTION_LABELS[key], key)
        self.section_combo.setCurrentIndex(max(0, self.section_combo.findData(section)))
        self.section_combo.currentIndexChanged.connect(self._section_changed)
        form.addRow("Section", self.section_combo)

        self.slot_combo = QComboBox()
        form.addRow("Used for", self.slot_combo)
        self.tier_combo = QComboBox()
        for tier in db.TIERS:
            self.tier_combo.addItem(TIER_TEXT[tier], tier)
        self.tier_combo.currentIndexChanged.connect(self._refresh)
        form.addRow("Level", self.tier_combo)

        self.covers_box = QWidget()
        covers_layout = QHBoxLayout(self.covers_box)
        covers_layout.setContentsMargins(0, 0, 0, 0)
        self.cover_checks = {}
        for key in db.SECTION_ORDER:
            box = QCheckBox(db.SECTION_LABELS[key])
            self.cover_checks[key] = box
            covers_layout.addWidget(box)
        covers_layout.addStretch(1)
        self.covers_label = QLabel("Also describes")
        form.addRow(self.covers_label, self.covers_box)

        self.group_combo = QComboBox()
        self.group_combo.setEditable(True)
        form.addRow("Group", self.group_combo)
        self.content_combo = QComboBox()
        self.content_combo.addItem("General", "general")
        self.content_combo.addItem("Adult (only used when Adult content is on)", "explicit")
        form.addRow("Content", self.content_combo)
        layout.addLayout(form)

        self.editor = LinesEditor(on_change=self._refresh)
        layout.addWidget(self.editor, stretch=1)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText("Create list")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self._section_changed()

    def _section_changed(self, *_args):
        section = self.section_combo.currentData()
        self.slot_combo.clear()
        for slot in db.SECTION_SLOTS[section]:
            self.slot_combo.addItem(db.slot_label(slot), slot)
        self.group_combo.clear()
        for group in db.groups_for_section(self.conn, section):
            self.group_combo.addItem(group)
        self.group_combo.setCurrentText(db.USER_GROUP)
        for key, box in self.cover_checks.items():
            box.setVisible(key != section)
            box.setChecked(False)
        adult_ok = section == "action"
        self.content_combo.setEnabled(adult_ok)
        if not adult_ok:
            self.content_combo.setCurrentIndex(0)
        self._refresh()

    def _refresh(self, *_args):
        scene = self.tier_combo.currentData() == "scene"
        self.covers_box.setVisible(scene)
        self.covers_label.setVisible(scene)
        ok = bool(self.name_edit.text().strip()) and bool(self.editor.lines())
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(ok)

    def spec(self):
        """Everything db.create_user_collection needs."""
        section = self.section_combo.currentData()
        return {
            "name": self.name_edit.text().strip(), "section": section, "slot": self.slot_combo.currentData(),
            "tier": self.tier_combo.currentData(), "texts": self.editor.lines(),
            "grp": self.group_combo.currentText().strip() or db.USER_GROUP,
            "content_level": self.content_combo.currentData(),
            "covers": [k for k, box in self.cover_checks.items() if box.isChecked() and k != section],
        }
