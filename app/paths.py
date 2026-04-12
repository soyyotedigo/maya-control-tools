"""User-data directory for ControlMe.

Maya → ~/Documents/maya/controlme/  (Windows)
     → /home/<user>/maya/controlme/ (Linux)
     → ~/Library/Preferences/Autodesk/maya/controlme/ (macOS)
"""
import os


def get_user_data_dir() -> str:
    import maya.cmds as cmds
    base = os.path.join(cmds.internalVar(userAppDir=True), "controlme")
    os.makedirs(base, exist_ok=True)
    return base


def get_db_path() -> str:
    return os.path.join(get_user_data_dir(), "controlme.db")


def get_log_path() -> str:
    log_dir = os.path.join(get_user_data_dir(), "logs")
    os.makedirs(log_dir, exist_ok=True)
    return os.path.join(log_dir, "controlme.log")
