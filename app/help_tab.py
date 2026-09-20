"""The Help tab: a topic list on the left, the guide on the right."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QListWidget, QSplitter, QTextBrowser, QVBoxLayout, QWidget

from app import db
from app.help_text import topics


class HelpTab(QWidget):
    def __init__(self, conn, parent=None):
        super().__init__(parent)
        file = db._db_file(conn)
        self.topics = topics(file or "(in memory)", db.backup_folder(conn) or "", db.STAGING_DIR)
        root = QVBoxLayout(self)
        splitter = QSplitter(Qt.Horizontal)
        self.topic_list = QListWidget()
        self.topic_list.setMinimumWidth(200)
        self.topic_list.setMaximumWidth(280)
        for title, _html in self.topics:
            self.topic_list.addItem(title)
        self.topic_list.currentRowChanged.connect(self._show)
        splitter.addWidget(self.topic_list)
        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(False)
        splitter.addWidget(self.browser)
        splitter.setSizes([220, 1200])
        root.addWidget(splitter)
        self.topic_list.setCurrentRow(0)

    def _show(self, row):
        if 0 <= row < len(self.topics):
            self.browser.setHtml(self.topics[row][1])

    def show_topic(self, title):
        for row, (name, _html) in enumerate(self.topics):
            if name == title:
                self.topic_list.setCurrentRow(row)
                return True
        return False
