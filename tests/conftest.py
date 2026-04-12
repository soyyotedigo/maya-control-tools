from __future__ import annotations

import importlib.util
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    _MAYA_STANDALONE_SPEC = importlib.util.find_spec("maya.standalone")
except ModuleNotFoundError:
    _MAYA_STANDALONE_SPEC = None

if _MAYA_STANDALONE_SPEC is None:
    collect_ignore = ["maya"]


@pytest.fixture(scope="session")
def qapp():
    from app.compat import QtWidgets

    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app
