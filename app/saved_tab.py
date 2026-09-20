"""The Saved tab: prompts you kept from the Builder, with their notes. Load one back to keep working on it."""
from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QPlainTextEdit, QPushButton, QSplitter, QTextEdit, QVBoxLayout, QWidget,
)

from app import db

NOTES_SAVE_DELAY_MS = 600


class SavedTab(QWidget):
    load_requested = Signal(int)   # the user wants this saved prompt back in the Builder
    changed = Signal()             # a saved prompt was renamed or deleted

    def __init__(self, conn, parent=None):
        super().__init__(parent)
        self.conn = conn
        self._current = None        # id of the saved prompt shown on the right
        self._notes_dirty = False

        root = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search names, prompts and notes...")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(lambda _text: self.refresh())
        bar.addWidget(self.search_edit, stretch=1)
        self.hidden_label = QLabel("")
        bar.addWidget(self.hidden_label)
        self.export_btn = QPushButton("Export all...")
        self.export_btn.setToolTip("Write the prompts shown here to a text file")
        self.export_btn.clicked.connect(self.export_dialog)
        bar.addWidget(self.export_btn)
        root.addLayout(bar)

        splitter = QSplitter(Qt.Horizontal)
        self.list = QListWidget()
        self.list.setMinimumWidth(300)
        self.list.currentItemChanged.connect(self._on_selection)
        self.list.itemDoubleClicked.connect(lambda _item: self._load())
        splitter.addWidget(self.list)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(6, 0, 0, 0)
        self.title = QLabel("")
        font = self.title.font()
        font.setBold(True)
        font.setPointSize(font.pointSize() + 2)
        self.title.setFont(font)
        right_layout.addWidget(self.title)
        self.meta = QLabel("")
        self.meta.setStyleSheet("color: palette(mid);")
        right_layout.addWidget(self.meta)
        self.prompt = QTextEdit()
        self.prompt.setReadOnly(True)
        right_layout.addWidget(self.prompt, stretch=3)
        right_layout.addWidget(QLabel("Notes"))
        self.notes = QPlainTextEdit()
        self.notes.setPlaceholderText("Anything worth remembering: the model, LoRA, seed, what you liked...")
        self.notes.setMaximumHeight(110)
        self.notes.textChanged.connect(self._notes_edited)
        right_layout.addWidget(self.notes)
        buttons = QHBoxLayout()
        self.load_btn = QPushButton("Load into Builder")
        self.load_btn.clicked.connect(self._load)
        buttons.addWidget(self.load_btn)
        self.copy_btn = QPushButton("Copy prompt")
        self.copy_btn.clicked.connect(self._copy)
        buttons.addWidget(self.copy_btn)
        self.rename_btn = QPushButton("Rename...")
        self.rename_btn.clicked.connect(self.rename_dialog)
        buttons.addWidget(self.rename_btn)
        self.delete_btn = QPushButton("Delete")
        self.delete_btn.clicked.connect(self.delete_dialog)
        buttons.addWidget(self.delete_btn)
        buttons.addStretch(1)
        right_layout.addLayout(buttons)
        self.status = QLabel("")
        right_layout.addWidget(self.status)
        splitter.addWidget(right)
        splitter.setSizes([380, 900])
        root.addWidget(splitter, stretch=1)

        self._notes_timer = QTimer(self)
        self._notes_timer.setSingleShot(True)
        self._notes_timer.setInterval(NOTES_SAVE_DELAY_MS)
        self._notes_timer.timeout.connect(self.flush_notes)
        self.refresh()

    # --- list ---------------------------------------------------------------

    def _include_adult(self):
        return db.get_setting(self.conn, "builder_adult", "0") == "1"

    def refresh(self):
        """Reload the list (keeping the selection when the prompt is still there)."""
        self.flush_notes()
        keep = self._current
        shown, hidden = db.list_saved_prompts(self.conn, self.search_edit.text().strip(), self._include_adult())
        self.list.blockSignals(True)
        self.list.clear()
        for row in shown:
            item = QListWidgetItem(f"{row['name']}\n{row['updated_at'][:16]}")
            item.setData(Qt.UserRole, row["id"])
            item.setToolTip(row["prompt_text"][:600])
            self.list.addItem(item)
        self.list.blockSignals(False)
        self.hidden_label.setText(f"{hidden} adult prompt{'s' if hidden != 1 else ''} hidden (turn on Adult content in the Builder)"
                                  if hidden else "")
        target = next((i for i in range(self.list.count()) if self.list.item(i).data(Qt.UserRole) == keep), 0)
        if self.list.count():
            self.list.setCurrentRow(target)
            self._show(self.list.item(target).data(Qt.UserRole))
        else:
            self._show(None)
        self.export_btn.setEnabled(bool(shown))

    def select_prompt(self, saved_id):
        """Refresh and show one prompt (used right after saving it in the Builder)."""
        self.flush_notes()
        if self.search_edit.text():
            self.search_edit.blockSignals(True)
            self.search_edit.clear()
            self.search_edit.blockSignals(False)
        self._current = saved_id
        self.refresh()

    def _on_selection(self, current, _previous):
        self.flush_notes()
        self._show(current.data(Qt.UserRole) if current is not None else None)

    def _show(self, saved_id):
        self._current = saved_id
        saved = db.get_saved_prompt(self.conn, saved_id) if saved_id else None
        for widget in (self.load_btn, self.copy_btn, self.rename_btn, self.delete_btn, self.notes):
            widget.setEnabled(saved is not None)
        self.notes.blockSignals(True)
        self._notes_dirty = False
        if saved is None:
            self.title.setText("")
            self.meta.setText("Nothing saved yet. Build a prompt and press Save prompt... in the Builder." if not self.list.count() else "")
            self.prompt.clear()
            self.notes.clear()
        else:
            self.title.setText(saved["name"])
            words = len(saved["prompt_text"].split())
            self.meta.setText(f"Saved {saved['created_at'][:16]}  ·  changed {saved['updated_at'][:16]}  ·  {words} words"
                              + ("  ·  contains adult content" if saved["adult"] else ""))
            self.prompt.setPlainText(saved["prompt_text"])
            self.notes.setPlainText(saved["notes"])
        self.notes.blockSignals(False)

    # --- notes --------------------------------------------------------------

    def _notes_edited(self):
        self._notes_dirty = True
        self._notes_timer.start()

    def flush_notes(self):
        """Write pending note edits to the database."""
        self._notes_timer.stop()
        if self._notes_dirty and self._current:
            db.set_saved_notes(self.conn, self._current, self.notes.toPlainText())
        self._notes_dirty = False

    # --- actions ------------------------------------------------------------

    def _load(self):
        if self._current:
            self.flush_notes()
            self.load_requested.emit(self._current)

    def _copy(self):
        if self._current:
            QApplication.clipboard().setText(self.prompt.toPlainText())
            self.status.setText("Copied")

    def rename_dialog(self):
        saved = db.get_saved_prompt(self.conn, self._current) if self._current else None
        if saved is None:
            return
        name, ok = QInputDialog.getText(self, "Rename", "Name:", text=saved["name"])
        if ok and name.strip():
            self.rename(saved["id"], name)

    def rename(self, saved_id, name):
        db.rename_saved_prompt(self.conn, saved_id, name)
        self.refresh()
        self.changed.emit()

    def delete_dialog(self):
        saved = db.get_saved_prompt(self.conn, self._current) if self._current else None
        if saved is None:
            return
        if QMessageBox.question(self, "Delete saved prompt", f"Delete \"{saved['name']}\"?") == QMessageBox.Yes:
            self.delete(saved["id"])

    def delete(self, saved_id):
        db.delete_saved_prompt(self.conn, saved_id)
        self._current = None
        self.refresh()
        self.changed.emit()

    # --- export -------------------------------------------------------------

    def export_text(self):
        """The prompts currently shown, as plain text (newest first)."""
        shown, _hidden = db.list_saved_prompts(self.conn, self.search_edit.text().strip(), self._include_adult())
        blocks = []
        for row in shown:
            block = [f"=== {row['name']} ===", f"Saved {row['created_at'][:16]}", "", row["prompt_text"]]
            if row["notes"].strip():
                block += ["", "Notes: " + row["notes"].strip()]
            blocks.append("\n".join(block))
        return "\n\n\n".join(blocks) + ("\n" if blocks else "")

    def export_dialog(self):
        name, _ = QFileDialog.getSaveFileName(self, "Export saved prompts", "saved-prompts.txt", "Text files (*.txt)")
        if name:
            self.export_to(name)

    def export_to(self, path):
        text = self.export_text()
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        self.status.setText(f"Exported to {path}")
        return path
