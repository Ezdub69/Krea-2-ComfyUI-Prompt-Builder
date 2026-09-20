"""Image Analyser: browse a folder tree of generated PNGs, see thumbnails for the selected folder, and click one for a
larger preview plus the generation data stored inside it (prompt, negative prompt, seed, model, LoRAs, sampler settings).

The data comes from the text chunks embedded in the PNG - see comfy_metadata.py for the parsing. Everything is read
locally from the files; nothing is uploaded. Deliberately small: no tagging, favourites or live folder watching.
"""
import os

from PySide6.QtCore import QDir, QSize, QSortFilterProxyModel, QThread, QTimer, Signal, Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QFileSystemModel, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QPlainTextEdit, QPushButton, QScrollArea, QSplitter, QTabWidget, QTreeView, QVBoxLayout, QWidget,
)

from app import comfy_metadata, db

THUMB_SIZE = 140
PREVIEW_MAX_SIZE = 360
BATCH_SIZE = 40
LAST_FOLDER_SETTING = "analyser_last_folder"
EMPTY_PREVIEW_TEXT = "Choose a folder of generated images (PNG),\nthen click an image to see its prompt and settings."
FIELD_ORDER = [
    ("prompt", "Prompt"), ("negative_prompt", "Negative Prompt"), ("model", "Model"), ("loras", "LoRAs"),
    ("seed", "Seed"), ("steps", "Steps"), ("cfg", "CFG"), ("sampler", "Sampler"), ("scheduler", "Scheduler"),
    ("denoise", "Denoise"),
]


class _RootVisibleProxyModel(QSortFilterProxyModel):
    """QTreeView.setRootIndex() hides that index's own row, so once you have navigated into a folder there would be no
    way to click back to the chosen root folder itself. This proxy sits in front of QFileSystemModel so the tree's real
    Qt root can be the chosen folder's *parent* (making the chosen folder a visible, selectable row) while filtering out
    everything else at that level - the chosen folder's siblings never appear, only itself and its own descendants."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scope_parent_path = None
        self._scope_folder_path = None

    def set_scope(self, folder_path):
        if folder_path is None:
            self._scope_folder_path = None
            self._scope_parent_path = None
        else:
            self._scope_folder_path = os.path.normcase(os.path.normpath(folder_path))
            self._scope_parent_path = os.path.normcase(os.path.normpath(os.path.dirname(folder_path)))
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row, source_parent):
        if self._scope_folder_path is None:
            return True
        source_model = self.sourceModel()
        parent_path = os.path.normcase(os.path.normpath(source_model.filePath(source_parent)))
        if parent_path != self._scope_parent_path:
            return True   # not at the filtered level - let descendants through freely
        index = source_model.index(source_row, 0, source_parent)
        row_path = os.path.normcase(os.path.normpath(source_model.filePath(index)))
        return row_path == self._scope_folder_path


class _ScanWorker(QThread):
    """Lists the PNGs directly inside one folder (subfolders are what the tree is for) and makes thumbnails off the
    interface thread. Decoding and scaling a QImage is thread-safe; only turning it into a QPixmap needs the main thread."""

    found_batch = Signal(list)    # [(path, QImage thumbnail), ...]
    finished_scan = Signal(int)   # total PNGs found in this folder

    def __init__(self, folder, parent=None):
        super().__init__(parent)
        self._folder = folder
        self._abort = False

    def request_abort(self):
        self._abort = True

    def run(self):
        try:
            names = os.listdir(self._folder)
        except OSError:
            self.finished_scan.emit(0)
            return
        paths = [os.path.join(self._folder, n) for n in names if n.lower().endswith(".png")]
        paths.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        batch, loaded = [], 0
        for path in paths:
            if self._abort:
                return
            img = QImage(path)
            if img.isNull():
                continue   # not a readable image: neither shown nor counted
            loaded += 1
            batch.append((path, img.scaled(THUMB_SIZE, THUMB_SIZE, Qt.KeepAspectRatio, Qt.SmoothTransformation)))
            if len(batch) >= BATCH_SIZE:
                self.found_batch.emit(batch)
                batch = []
        if batch:
            self.found_batch.emit(batch)
        self.finished_scan.emit(loaded)


class AnalyserTab(QWidget):
    def __init__(self, conn, parent=None):
        super().__init__(parent)
        self.conn = conn
        self._scan_worker = None
        self._found_count = 0
        self._current_folder = None
        self._current_prompt = ""

        root = QVBoxLayout(self)

        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel("Root folder:"))
        self.folder_edit = QLineEdit(db.get_setting(conn, LAST_FOLDER_SETTING, ""))
        self.folder_edit.setPlaceholderText("Type or paste a folder and press Enter, or use Browse...")
        self.folder_edit.returnPressed.connect(lambda: self._set_root_folder(self.folder_edit.text().strip()))
        folder_row.addWidget(self.folder_edit, stretch=1)
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self.browse_folder)
        folder_row.addWidget(browse_btn)
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setToolTip("Scan the selected folder again")
        self.refresh_btn.clicked.connect(self.refresh_current_folder)
        folder_row.addWidget(self.refresh_btn)
        self.status_label = QLabel("")
        folder_row.addWidget(self.status_label)
        root.addLayout(folder_row)

        splitter = QSplitter(Qt.Horizontal)

        self.fs_model = QFileSystemModel()
        self.fs_model.setFilter(QDir.Dirs | QDir.NoDotAndDotDot)
        self.tree_proxy = _RootVisibleProxyModel()
        self.tree_proxy.setSourceModel(self.fs_model)
        self.tree_view = QTreeView()
        self.tree_view.setModel(self.tree_proxy)
        self.tree_view.setHeaderHidden(True)
        for col in range(1, 4):
            self.tree_view.hideColumn(col)
        self.tree_view.clicked.connect(self._on_tree_clicked)
        splitter.addWidget(self.tree_view)

        self.thumb_list = QListWidget()
        self.thumb_list.setViewMode(QListWidget.IconMode)
        self.thumb_list.setIconSize(QPixmap(THUMB_SIZE, THUMB_SIZE).size())
        self.thumb_list.setResizeMode(QListWidget.Adjust)
        self.thumb_list.setWrapping(True)
        self.thumb_list.setSpacing(6)
        self.thumb_list.setMovement(QListWidget.Static)
        self.thumb_list.currentItemChanged.connect(self._on_selection_changed)
        # the default icon-mode selection highlight is nearly invisible on a thumbnail: a clear border makes it obvious
        self.thumb_list.setStyleSheet(
            "QListWidget::item:selected { border: 3px solid #16a34a; background: #bbf7d0; border-radius: 4px; } "
            "QListWidget::item:selected:!active { border: 3px solid #16a34a; background: #bbf7d0; }")
        splitter.addWidget(self.thumb_list)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        self.preview_label = QLabel(EMPTY_PREVIEW_TEXT)
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumHeight(PREVIEW_MAX_SIZE)
        right_layout.addWidget(self.preview_label)

        self.meta_tabs = QTabWidget()
        meta_widget = QWidget()
        self.meta_form = QFormLayout(meta_widget)
        # a bare QWidget clips overflow instead of scrolling (a long prompt would be cut off): the scroll area gives the
        # Metadata tab the same vertical scrollbar the Raw tab's text box has
        meta_scroll = QScrollArea()
        meta_scroll.setWidgetResizable(True)
        meta_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        meta_scroll.setFrameShape(QScrollArea.NoFrame)
        meta_scroll.setWidget(meta_widget)
        self.meta_tabs.addTab(meta_scroll, "Metadata")
        self.raw_edit = QPlainTextEdit()
        self.raw_edit.setReadOnly(True)
        self.meta_tabs.addTab(self.raw_edit, "Raw")
        self.copy_prompt_btn = QPushButton("Copy prompt")
        self.copy_prompt_btn.setEnabled(False)
        self.copy_prompt_btn.clicked.connect(self._copy_prompt)
        self.meta_tabs.setCornerWidget(self.copy_prompt_btn, Qt.TopRightCorner)
        right_layout.addWidget(self.meta_tabs, stretch=1)
        splitter.addWidget(right)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        splitter.setStretchFactor(2, 2)
        root.addWidget(splitter, stretch=1)

        if self.folder_edit.text().strip():
            self._set_root_folder(self.folder_edit.text().strip())

    # --- folder tree ----------------------------------------------------------

    def browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Choose root folder", self.folder_edit.text())
        if folder:
            self.folder_edit.setText(folder)
            self._set_root_folder(folder)

    def _set_root_folder(self, folder):
        if not folder or not os.path.isdir(folder):
            self.status_label.setText("Choose a valid folder first.")
            return
        db.set_setting(self.conn, LAST_FOLDER_SETTING, folder)
        folder = os.path.normpath(folder)
        parent = os.path.dirname(folder)
        if not parent or os.path.normcase(parent) == os.path.normcase(folder):
            # a drive root has no real parent to anchor on: fall back to a hidden-root tree
            self.tree_proxy.set_scope(None)
            self.fs_model.setRootPath(folder)
            self.tree_view.setRootIndex(self.tree_proxy.mapFromSource(self.fs_model.index(folder)))
        else:
            self.fs_model.setRootPath(parent)
            self.tree_proxy.set_scope(folder)
            self.tree_view.setRootIndex(self.tree_proxy.mapFromSource(self.fs_model.index(parent)))
            target_index = self.tree_proxy.mapFromSource(self.fs_model.index(folder))
            self.tree_view.setCurrentIndex(target_index)
            self.tree_view.expand(target_index)
        self._scan_folder(folder)

    def _on_tree_clicked(self, index):
        self._scan_folder(self.fs_model.filePath(self.tree_proxy.mapToSource(index)))

    def refresh_current_folder(self):
        if self._current_folder:
            self._scan_folder(self._current_folder)

    # --- scanning -------------------------------------------------------------

    def _scan_folder(self, folder):
        self._current_folder = folder
        self._stop_scan()
        self.thumb_list.clear()
        self._clear_details()
        self._found_count = 0
        self.status_label.setText("Scanning...")
        self.refresh_btn.setEnabled(False)
        self._scan_worker = _ScanWorker(folder)
        self._scan_worker.found_batch.connect(self._on_found_batch)
        self._scan_worker.finished_scan.connect(self._on_scan_finished)
        self._scan_worker.start()

    def _stop_scan(self):
        worker = self._scan_worker
        if worker is not None and worker.isRunning():
            worker.request_abort()
            worker.wait(3000)

    def is_scanning(self):
        return self._scan_worker is not None and self._scan_worker.isRunning()

    def shutdown(self):
        """Stop the background scan (called when the app closes)."""
        self._stop_scan()

    def _on_found_batch(self, batch):
        for path, qimage in batch:
            item = QListWidgetItem(QPixmap.fromImage(qimage), "")
            # no text is set, but the item would still reserve a label line under the icon (a blank strip under every
            # thumbnail): pinning the size hint to the icon removes it
            item.setSizeHint(QSize(THUMB_SIZE, THUMB_SIZE))
            item.setData(Qt.UserRole, path)
            item.setToolTip(os.path.basename(path))
            self.thumb_list.addItem(item)
        self._found_count += len(batch)
        self.status_label.setText(f"{self._found_count} found...")

    def _on_scan_finished(self, total):
        self.refresh_btn.setEnabled(True)
        self.status_label.setText(f"{total} image(s) in this folder")

    # --- selection and metadata -----------------------------------------------

    def _on_selection_changed(self, current, _previous):
        if current is None:
            return
        path = current.data(Qt.UserRole)
        self._show_preview(path)
        self._show_metadata(path)

    def _clear_details(self):
        self.preview_label.setPixmap(QPixmap())
        self.preview_label.setText(EMPTY_PREVIEW_TEXT)
        self._current_prompt = ""
        self.copy_prompt_btn.setEnabled(False)
        while self.meta_form.rowCount():
            self.meta_form.removeRow(0)
        self.raw_edit.setPlainText("")

    def _show_preview(self, path):
        pix = QPixmap(path)
        if pix.isNull():
            self.preview_label.setPixmap(QPixmap())
            self.preview_label.setText("(failed to load)")
            return
        self.preview_label.setPixmap(pix.scaled(PREVIEW_MAX_SIZE, PREVIEW_MAX_SIZE, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def _copy_prompt(self):
        if not self._current_prompt:
            return
        QApplication.clipboard().setText(self._current_prompt)
        self.copy_prompt_btn.setText("Copied!")
        QTimer.singleShot(1500, lambda: self.copy_prompt_btn.setText("Copy prompt"))

    def _show_metadata(self, path):
        while self.meta_form.rowCount():
            self.meta_form.removeRow(0)
        structured, raw, source = comfy_metadata.extract_metadata(path)
        self._current_prompt = str(structured.get("prompt", "")) if source else ""
        self.copy_prompt_btn.setEnabled(bool(self._current_prompt))
        if source is None:
            self.meta_form.addRow(QLabel("No recognizable generation metadata found in this file."))
            self.raw_edit.setPlainText("")
            return
        for key, label in FIELD_ORDER:
            if key not in structured:
                continue
            value = structured[key]
            text = ", ".join(str(v) for v in value) if isinstance(value, list) else str(value)
            value_label = QLabel(text)
            value_label.setWordWrap(True)
            value_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.meta_form.addRow(QLabel(f"{label}:"), value_label)
        self.meta_form.addRow(QLabel("Source:"), QLabel(source))
        self.raw_edit.setPlainText(raw)
