#!/bin/bash
# Run ControlMe Maya integration tests via mayapy.
# Works on Windows (Git Bash / WSL) and Linux with a single command.
# Usage:
#   ./run_maya_tests.sh               -- run all Maya tests
#   ./run_maya_tests.sh -k test_name  -- run a specific test
#   ./run_maya_tests.sh --tb=short    -- shorter tracebacks

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

case "$(uname -s)" in
    MINGW*|MSYS*|CYGWIN*)
        MAYAPY="/c/Program Files/Autodesk/Maya2026/bin/mayapy.exe"
        ;;
    *)
        MAYAPY="/usr/autodesk/maya2026/bin/mayapy"
        ;;
esac

"$MAYAPY" -m pytest "$REPO_ROOT/tests/maya" -v "$@"
