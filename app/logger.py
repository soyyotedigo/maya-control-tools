"""
Centralised logging for ControlMe.

Call ``setup()`` once at startup (standalone.py / main.py).
Then import ``log`` anywhere in the app:

    from app.logger import log
    log.info("something happened")

Log file location:  <user-data-dir>/logs/controlme.log
"""

import logging
import os
import sys
import traceback
from logging.handlers import RotatingFileHandler

from app.config import LOG_MAX_BYTES, LOG_BACKUP_COUNT, LOG_FILE_LEVEL, LOG_CONSOLE_LEVEL

# Public logger — use this everywhere.
log = logging.getLogger("controlme")


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

def setup(level: int = logging.DEBUG) -> str:
    """Initialise file + console handlers.

    Safe to call multiple times — re-evaluates the log path on every call so
    hot-reloads always write to the correct user-data directory.
    Returns the absolute path to the log file.
    """
    from app.paths import get_log_path
    log_file = get_log_path()

    # Close and remove any existing file handler pointing to the wrong path.
    for h in list(log.handlers):
        if isinstance(h, RotatingFileHandler):
            if os.path.normcase(h.baseFilename) != os.path.normcase(log_file):
                h.close()
                log.removeHandler(h)

    # If a correct file handler already exists, nothing more to do.
    if any(isinstance(h, RotatingFileHandler) for h in log.handlers):
        return log_file

    log.setLevel(level)

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)-8s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Rotating file — configurable size and backup count.
    fh = RotatingFileHandler(
        log_file, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT, encoding="utf-8"
    )
    fh.setLevel(getattr(logging, LOG_FILE_LEVEL, logging.DEBUG))
    fh.setFormatter(fmt)
    log.addHandler(fh)

    # Console (INFO and above so Maya's Script Editor stays clean).
    if not any(isinstance(h, logging.StreamHandler) and not isinstance(h, RotatingFileHandler)
               for h in log.handlers):
        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(getattr(logging, LOG_CONSOLE_LEVEL, logging.INFO))
        ch.setFormatter(fmt)
        log.addHandler(ch)

    # Catch unhandled exceptions and write them to the log before Qt can
    # silently swallow them or crash without a trace.
    _orig_excepthook = sys.excepthook

    def _excepthook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            _orig_excepthook(exc_type, exc_value, exc_tb)
            return
        log.critical(
            "UNHANDLED EXCEPTION — this may have caused the tool to close",
            exc_info=(exc_type, exc_value, exc_tb),
        )
        # Also flush so the line is on disk even if the process dies next.
        for h in log.handlers:
            h.flush()
        _orig_excepthook(exc_type, exc_value, exc_tb)

    sys.excepthook = _excepthook

    log.info("=" * 60)
    log.info("ControlMe — logging started")
    log.info("Log file: %s", log_file)
    log.info("Python: %s", sys.version.split()[0])
    log.info("Platform: %s", sys.platform)

    return log_file
