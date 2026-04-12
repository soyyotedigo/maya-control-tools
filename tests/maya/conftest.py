"""
mayapy session bootstrap for real Maya integration tests.

Run with:
    mayapy -m pytest tests/maya/ -v

Maya standalone is initialized once per session to avoid the overhead
of re-initializing for every test module.
"""
import maya.standalone

maya.standalone.initialize(name="python")

import pytest  # noqa: E402 — must come after standalone.initialize


@pytest.fixture(scope="session", autouse=True)
def maya_session():
    """Yield after standalone is initialized; uninitialize on teardown."""
    yield
    maya.standalone.uninitialize()


@pytest.fixture
def empty_scene():
    """Provide a clean Maya scene; reset before and after each test."""
    import maya.cmds as cmds
    cmds.file(new=True, force=True)
    yield
    cmds.file(new=True, force=True)
