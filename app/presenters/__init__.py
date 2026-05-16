"""Presenter layer — bridges views and core/services.

A Presenter owns transient state (selection mirrors, in-flight drag
sessions, CV snapshots) and the lazy imports of Maya operations, so the
Qt views stay declarative: build widgets, wire signals, delegate.
"""
