#!/usr/bin/env python3
"""
run_app.py — 冷喷涂缺陷修复软件启动入口
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication
from repair_app.ui.main_window import MainWindow
from repair_app.utils.logger_config import setup_logging
from repair_app.utils.crash_handler import install_crash_handler


def main():
    """Main entry point."""
    setup_logging()
    install_crash_handler()

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
