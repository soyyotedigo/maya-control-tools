"""
ControlMe — entry point for Maya's Script Editor.

Paste this into Maya's Script Editor (Python tab) and run it.
Run again at any time to hot-reload code changes — no Maya restart needed.
"""

import sys
from pathlib import Path

REPO_PATH = str(Path(__file__).parent)
if REPO_PATH not in sys.path:
    sys.path.insert(0, REPO_PATH)

# Hot-reload: purge every cached app.* module so the next import
# picks up any file changes made since the last run.
for _k in [k for k in sys.modules if k == "app" or k.startswith("app.")]:
    del sys.modules[_k]

# Initialise logging (safe to call multiple times — no-op after first call).
from app.logger import setup as _setup_log, log as _log
_setup_log()
_log.info("Maya launch via main.py (hot-reload)")

from app.views.main_view import show_as_workspace_control
show_as_workspace_control(install_dir=REPO_PATH, force_reload=True)
