"""Tests for ``module/installer.py`` — the shared installer helpers."""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest

# Make ``module.installer`` importable when running pytest from the repo root.
_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from module import installer


# ---------------------------------------------------------------------------
# maya_app_dir + modules_dir
# ---------------------------------------------------------------------------

def test_maya_app_dir_honors_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("MAYA_APP_DIR", str(tmp_path))
    assert installer.maya_app_dir() == str(tmp_path)


def test_maya_app_dir_default_per_platform(monkeypatch):
    monkeypatch.delenv("MAYA_APP_DIR", raising=False)
    result = installer.maya_app_dir()
    if sys.platform == "win32":
        assert result.endswith(os.path.join("Documents", "maya"))
    else:
        assert result.endswith("maya")


def test_modules_dir_composes_path(monkeypatch, tmp_path):
    monkeypatch.setenv("MAYA_APP_DIR", str(tmp_path))
    assert installer.modules_dir("2025") == str(tmp_path / "2025" / "modules")


# ---------------------------------------------------------------------------
# find_maya_versions
# ---------------------------------------------------------------------------

def test_find_maya_versions_filters_and_sorts(monkeypatch, tmp_path):
    monkeypatch.setenv("MAYA_APP_DIR", str(tmp_path))
    (tmp_path / "2024").mkdir()
    (tmp_path / "2025").mkdir()
    (tmp_path / "2023").mkdir()
    (tmp_path / "projects").mkdir()       # non-year folder — must be ignored
    (tmp_path / "2025-beta").mkdir()      # not a 4-digit year — must be ignored
    (tmp_path / "2025.txt").write_text("")  # file, not folder

    assert installer.find_maya_versions() == ["2023", "2024", "2025"]


def test_find_maya_versions_empty_when_dir_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("MAYA_APP_DIR", str(tmp_path / "does-not-exist"))
    assert installer.find_maya_versions() == []


# ---------------------------------------------------------------------------
# read_app_version
# ---------------------------------------------------------------------------

def test_read_app_version_reads_toml(tmp_path):
    (tmp_path / "config.toml").write_text(
        '[app]\nversion = "9.9.9"\n', encoding="utf-8"
    )
    assert installer.read_app_version(str(tmp_path)) == "9.9.9"


def test_read_app_version_falls_back_when_missing(tmp_path):
    assert installer.read_app_version(str(tmp_path)) == "0.0.0"


# ---------------------------------------------------------------------------
# copy_package — regression: config.toml must end up in install_dir
# ---------------------------------------------------------------------------

def _make_fake_src(root: Path) -> Path:
    """Build a minimal repo layout in ``root`` that copy_package expects."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "app").mkdir()
    (root / "app" / "__init__.py").write_text("", encoding="utf-8")
    (root / "app" / "icons").mkdir()
    (root / "app" / "icons" / "controls_tool.png").write_bytes(b"\x89PNG\r\n")
    (root / "module").mkdir()
    (root / "module" / "scripts").mkdir()
    (root / "module" / "scripts" / "userSetup.py").write_text(
        "# fake userSetup\n", encoding="utf-8"
    )
    (root / "config.toml").write_text(
        '[app]\nversion = "1.2.3"\n', encoding="utf-8"
    )
    return root


def test_copy_package_produces_expected_layout(tmp_path):
    src = _make_fake_src(tmp_path / "src")
    dst = tmp_path / "install" / "ControlMe"

    installer.copy_package(str(src), str(dst))

    assert (dst / "app" / "__init__.py").is_file()
    assert (dst / "scripts" / "userSetup.py").is_file()
    assert (dst / "icons" / "controls_tool.png").is_file()
    # Regression: the bug fix — config.toml must be at the install root.
    assert (dst / "config.toml").is_file()


def test_copy_package_is_idempotent(tmp_path):
    src = _make_fake_src(tmp_path / "src")
    dst = tmp_path / "install" / "ControlMe"
    installer.copy_package(str(src), str(dst))
    installer.copy_package(str(src), str(dst))  # second run must not raise
    assert (dst / "config.toml").is_file()


# ---------------------------------------------------------------------------
# write_mod_file
# ---------------------------------------------------------------------------

def test_write_mod_file_substitutes_placeholders(tmp_path):
    install_dir = tmp_path / "modules" / "ControlMe"
    install_dir.mkdir(parents=True)
    modules = tmp_path / "modules"

    mod_path = installer.write_mod_file(str(install_dir), str(modules), "1.2.3")

    content = Path(mod_path).read_text(encoding="utf-8")
    assert "<INSTALL_DIR>" not in content
    assert "<VERSION>" not in content
    assert "1.2.3" in content
    # Maya prefers forward-slash paths in .mod files.
    assert str(install_dir).replace("\\", "/") in content


def test_write_mod_file_creates_modules_dir(tmp_path):
    install_dir = tmp_path / "ControlMe"
    modules = tmp_path / "freshly-made" / "modules"
    # modules dir does not exist yet — write_mod_file must create it.
    installer.write_mod_file(str(install_dir), str(modules), "1.0.0")
    assert (modules / "ControlMe.mod").is_file()


# ---------------------------------------------------------------------------
# remove_module — idempotency
# ---------------------------------------------------------------------------

def test_remove_module_removes_files(tmp_path):
    install_dir = tmp_path / "ControlMe"
    install_dir.mkdir()
    (install_dir / "marker.txt").write_text("x", encoding="utf-8")
    mod_file = tmp_path / "ControlMe.mod"
    mod_file.write_text("+ ControlMe 1.0.0 ...", encoding="utf-8")

    installer.remove_module(str(install_dir), str(mod_file))

    assert not install_dir.exists()
    assert not mod_file.exists()


def test_remove_module_is_idempotent(tmp_path):
    install_dir = tmp_path / "ControlMe"
    mod_file = tmp_path / "ControlMe.mod"
    # Neither exists — call must not raise.
    installer.remove_module(str(install_dir), str(mod_file))


# ---------------------------------------------------------------------------
# Real .mod template — guards against accidental edits to module/ControlMe.mod
# ---------------------------------------------------------------------------

def test_real_mod_template_substitutes_correctly(tmp_path):
    """Substitution against the real template must preserve all the
    directives Maya needs (PYTHONPATH, scripts, XBMLANGPATH)."""
    install_dir = tmp_path / "ControlMe"
    install_dir.mkdir()
    modules = tmp_path / "modules"

    mod_path = installer.write_mod_file(str(install_dir), str(modules), "7.7.7")
    content = Path(mod_path).read_text(encoding="utf-8")

    assert content.startswith("+ ControlMe 7.7.7 ")
    assert "PYTHONPATH+:=." in content
    assert "scripts: scripts" in content
    assert "XBMLANGPATH+:=icons" in content


# ---------------------------------------------------------------------------
# install_module.install() — end-to-end orchestration test
# ---------------------------------------------------------------------------

def test_install_module_end_to_end(monkeypatch, tmp_path):
    """install() should auto-detect the Maya version, copy the package,
    write a valid .mod file, and produce the expected layout."""
    # Pretend Maya 2025 is installed under tmp_path.
    monkeypatch.setenv("MAYA_APP_DIR", str(tmp_path))
    (tmp_path / "2025").mkdir()

    src = _make_fake_src(tmp_path / "src")

    import install_module
    install_module.install(src_dir=str(src))

    modules = tmp_path / "2025" / "modules"
    install_dir = modules / "ControlMe"
    assert (install_dir / "app" / "__init__.py").is_file()
    assert (install_dir / "scripts" / "userSetup.py").is_file()
    assert (install_dir / "icons" / "controls_tool.png").is_file()
    assert (install_dir / "config.toml").is_file()

    mod_file = modules / "ControlMe.mod"
    assert mod_file.is_file()
    content = mod_file.read_text(encoding="utf-8")
    # Real version from the fake src's config.toml.
    assert "1.2.3" in content
    assert str(install_dir).replace("\\", "/") in content
