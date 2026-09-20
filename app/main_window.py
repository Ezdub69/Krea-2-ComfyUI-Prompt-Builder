from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QMainWindow, QTabWidget

from app.analyser_tab import AnalyserTab
from app.builder_tab import BuilderTab
from app.help_tab import HelpTab
from app.library_tab import LibraryBrowser
from app.saved_tab import SavedTab


class MainWindow(QMainWindow):
    def __init__(self, conn):
        super().__init__()
        self.conn = conn
        self.setWindowTitle("ComfyUI Prompt Builder V2")
        self.resize(1500, 900)
        self.tabs = QTabWidget()
        self.builder_tab = BuilderTab(conn)
        self.saved_tab = SavedTab(conn)
        self.library_tab = LibraryBrowser(conn)
        self.analyser_tab = AnalyserTab(conn)
        self.help_tab = HelpTab(conn)
        self.tabs.addTab(self.builder_tab, "Builder")
        self.tabs.addTab(self.saved_tab, "Saved")
        self.tabs.addTab(self.library_tab, "Library")
        self.tabs.addTab(self.analyser_tab, "Image Analyser")
        self.tabs.addTab(self.help_tab, "Help")
        self.setCentralWidget(self.tabs)

        self.library_tab.library_reset.connect(self.builder_tab.reset_to_defaults)
        self.library_tab.library_reset.connect(self.saved_tab.refresh)
        self.builder_tab.saved_changed.connect(self.saved_tab.select_prompt)
        self.saved_tab.load_requested.connect(self._load_saved)
        self.saved_tab.changed.connect(self.builder_tab.refresh_loaded_state)
        self.tabs.currentChanged.connect(self._tab_changed)
        QShortcut(QKeySequence("F1"), self, activated=self.show_help)

    def show_help(self):
        self.tabs.setCurrentWidget(self.help_tab)

    def _load_saved(self, saved_id):
        if self.builder_tab.load_saved(saved_id):
            self.tabs.setCurrentWidget(self.builder_tab)

    def _tab_changed(self, _index):
        if self.tabs.currentWidget() is self.saved_tab:
            self.saved_tab.refresh()   # picks up the Builder's Adult content switch

    def closeEvent(self, event):
        self.saved_tab.flush_notes()
        self.analyser_tab.shutdown()
        super().closeEvent(event)
