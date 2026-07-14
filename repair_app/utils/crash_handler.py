"""Crash handler — global exception hook for unhandled exceptions.

Captures unhandled exceptions, logs them with full stack traces,
and optionally shows a user-friendly error dialog.

Usage:
    from repair_app.utils.crash_handler import install_crash_handler
    install_crash_handler()
"""

from __future__ import annotations
import sys
import os
import traceback
from datetime import datetime
from typing import Optional, Callable

try:
    from repair_app.utils.resource_path import get_data_dir
except ImportError:
    def get_data_dir():
        from pathlib import Path
        return Path(__file__).resolve().parent.parent.parent


def install_crash_handler(
    log_dir: Optional[str] = None,
    on_crash: Optional[Callable[[str], None]] = None,
) -> None:
    """Install a global exception hook for crash reporting.

    Args:
        log_dir: Directory for crash log files. Default: repair_app/utils/logs/
        on_crash: Optional callback invoked with the crash message.
    """
    if log_dir is None:
        log_dir = os.path.join(str(get_data_dir()), "logs")
    os.makedirs(log_dir, exist_ok=True)

    def _handler(exc_type, exc_value, exc_tb):
        # Format the traceback
        tb_lines = traceback.format_exception(exc_type, exc_value, exc_tb)
        tb_text = "".join(tb_lines)

        # Write crash log
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        crash_file = os.path.join(log_dir, f"crash_{timestamp}.log")
        try:
            with open(crash_file, "w", encoding="utf-8") as f:
                f.write(f"Crash Report - {datetime.now().isoformat()}\n")
                f.write("=" * 60 + "\n")
                f.write(f"Python: {sys.version}\n")
                f.write(f"Platform: {sys.platform}\n")
                f.write("-" * 60 + "\n")
                f.write(tb_text)
            print(f"[CrashHandler] Crash log saved: {crash_file}", file=sys.stderr)
        except Exception:
            print(f"[CrashHandler] Failed to write crash log: {crash_file}", file=sys.stderr)

        # Print to stderr
        print(tb_text, file=sys.stderr)

        # Invoke callback
        if on_crash:
            try:
                on_crash(tb_text)
            except Exception as cb_err:
                print(f"[CrashHandler] on_crash callback failed: {cb_err}", file=sys.stderr)

        # Call original excepthook
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = _handler