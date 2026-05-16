"""Optional integration with mGear Framework — detection + extract_controls.

mGear is a rigging framework for Maya. Its "Extract Controls" feature copies
the current shape of a selected control back into the matching guide, so the
next rig rebuild picks up the customized shape. Calling it is opt-in from the
Control Settings panel and only enabled when mGear is importable.
"""
from __future__ import annotations

from typing import Callable, Optional

_CACHED_FN: Optional[Callable[[], None]] | bool = None


def is_available() -> bool:
    """Return True if mGear's extract_controls is importable."""
    return _resolve() is not False


def extract_controls_on_selection() -> None:
    """Call mGear's Extract Controls on the current Maya selection.

    No-op when mGear is not installed. Any exception raised by mGear itself
    (e.g. selected control has no associated guide) is left to propagate so
    the surrounding undo chunk records it accurately.
    """
    fn = _resolve()
    if fn:
        fn()


def _resolve():
    global _CACHED_FN
    if _CACHED_FN is not None:
        return _CACHED_FN
    candidates = (
        ("mgear.shifter.guide_manager_gui", "extract_controls"),
        ("mgear.shifter.io", "extract_controls"),
        ("mgear.shifter.guide_manager", "extract_controls"),
    )
    for module_name, attr in candidates:
        try:
            mod = __import__(module_name, fromlist=[attr])
            fn = getattr(mod, attr)
        except (ImportError, AttributeError):
            continue
        _CACHED_FN = fn
        return fn
    _CACHED_FN = False
    return False
