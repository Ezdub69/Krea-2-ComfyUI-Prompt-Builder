# ComfyUI Prompt Builder V2
# Copyright (C) 2026 Ezdub69
#
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public
# License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later
# version. It is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License (the LICENSE file)
# for more details.
import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from app import db
from app.main_window import MainWindow


def run():
    conn = db.get_connection()
    db.initialize_db(conn)
    app = QApplication(sys.argv)

    # first start, a newer version of the presets, or --rebuild-library: (re)build the library from the shipped data
    if db.ensure_library(conn, force="--rebuild-library" in sys.argv) == "missing":
        QMessageBox.critical(None, "Library missing",
                             f"No preset library was found.\n\nExpected the preset data in:\n{db.STAGING_DIR}\n\n"
                             "Extract the whole app folder again rather than moving single files.")
        return 1

    window = MainWindow(conn)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run())
