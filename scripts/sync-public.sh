#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
# sync-public.sh
#
# Syncs curated content from maya-control-tools-dev (private)
# to maya-control-tools (public) for recruiter/user visibility.
#
# Usage:
#   bash scripts/sync-public.sh [commit message]
#
# The public repo must already exist at ../maya-control-tools
# Works on Windows (Git Bash) and Linux/macOS.
# ──────────────────────────────────────────────────────────────

set -euo pipefail

SRC="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$(cd "$SRC/.." && pwd)/maya-control-tools"

if [ ! -d "$DEST/.git" ]; then
    echo "ERROR: Public repo not found at $DEST"
    echo "Clone or init it first:"
    echo "  gh repo create maya-control-tools --public --clone"
    exit 1
fi

echo "==> Syncing from $SRC to $DEST"

# ── 1. Clean destination (keep .git) ──
find "$DEST" -mindepth 1 -maxdepth 1 ! -name '.git' -exec rm -rf {} +

# ── 2. Copy project structure ──
cp -r "$SRC/app"    "$DEST/"
cp -r "$SRC/tests"  "$DEST/"
cp -r "$SRC/module" "$DEST/"
cp -r "$SRC/scripts" "$DEST/"
mkdir -p "$DEST/docs"
cp -r "$SRC/docs/screenshots" "$DEST/docs/"

# docs — skip internal AI notes and evaluations
for f in "$SRC/docs/"*.md; do
    fname="$(basename "$f")"
    case "$fname" in
        GEMINI.md) ;;          # skip — internal AI prompt
        *) cp "$f" "$DEST/docs/" 2>/dev/null || true ;;
    esac
done
# evaluations folder is intentionally excluded

# CI — only the test workflow, not the sync workflow itself
mkdir -p "$DEST/.github/workflows"
cp "$SRC/.github/workflows/test-maya-versions.yml" "$DEST/.github/workflows/" 2>/dev/null || true

# Top-level files
for f in main.py install.py install_module.py config.toml pyproject.toml \
          README.md LICENSE .gitignore; do
    cp "$SRC/$f" "$DEST/" 2>/dev/null || true
done

# ── 3. Clean artifacts ──
find "$DEST" -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true
find "$DEST" -type d -name '.pytest_cache' -exec rm -rf {} + 2>/dev/null || true
find "$DEST" -type d -name '.ruff_cache' -exec rm -rf {} + 2>/dev/null || true
rm -f "$DEST/.coverage" "$DEST/coverage.xml" 2>/dev/null || true

echo "==> Files synced"

# ── 4. Commit and push if there are changes ──
cd "$DEST"

MSG="${1:-sync: update from dev $(date +%Y-%m-%d)}"

if git diff --quiet && git diff --cached --quiet && [ -z "$(git ls-files --others --exclude-standard)" ]; then
    echo "==> No changes to commit"
else
    git add -A
    git commit -m "$MSG"
    echo "==> Committed: $MSG"
    echo ""
    echo "To push:  cd $DEST && git push"
fi
