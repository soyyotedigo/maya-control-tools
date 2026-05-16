#!/usr/bin/env bash
# Sync the dev repo to the public-facing repo, driven by sync-public.json.
#
# What/where to copy is configured in sync-public.json. Refuses to run if
# the dev repo path does not end in -dev. Requires: jq.
#
# Usage:
#   ./scripts/sync-public.sh
#   ./scripts/sync-public.sh --dry-run

set -euo pipefail

DRY_RUN=false
for arg in "$@"; do
  [[ "$arg" == "--dry-run" || "$arg" == "-n" ]] && DRY_RUN=true
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEV_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CONFIG_PATH="$SCRIPT_DIR/sync-public.json"

# Refuse to run outside a *-dev repo
if [[ "${DEV_ROOT%/}" != *-dev ]]; then
  echo "ERROR: must run from a *-dev repo. Current: $DEV_ROOT" >&2
  exit 1
fi

if [[ ! -f "$CONFIG_PATH" ]]; then
  echo "ERROR: config not found: $CONFIG_PATH" >&2
  exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
  echo "ERROR: jq is required (https://stedolan.github.io/jq/)" >&2
  exit 1
fi

# ── Load config ──────────────────────────────────────────────────────────────
# Strip trailing \r from every jq output so the script is robust to JSON files
# saved with CRLF line endings on Windows.
jq_str() { jq -r "$1"   "$CONFIG_PATH" | tr -d '\r'; }
jq_arr() { jq -r "$1[]" "$CONFIG_PATH" | tr -d '\r'; }

PUBLIC_ROOT="$(jq_str '.public_root')"
PUBLIC_ROOT="${PUBLIC_ROOT//\\//}"  # normalize Windows backslashes for bash

readarray -t COPY_DIRS        < <(jq_arr '.copy_dirs')
readarray -t COPY_FILES       < <(jq_arr '.copy_files')
readarray -t EXCLUDE_PATTERNS < <(jq_arr '.exclude_patterns')
readarray -t PRIVATE_PATHS    < <(jq_arr '.private_paths')

# ── Defense-in-depth: refuse to publish any private path ─────────────────────
for entry in "${COPY_DIRS[@]}" "${COPY_FILES[@]}"; do
  for p in "${PRIVATE_PATHS[@]}"; do
    if [[ "$entry" == "$p" ]]; then
      echo "ERROR: refusing to publish '$entry' — listed in private_paths" >&2
      exit 2
    fi
  done
done

echo "Source : $DEV_ROOT"
echo "Target : $PUBLIC_ROOT"
$DRY_RUN && echo "(dry run - no files written)"
echo

# Clean-slate: remove everything in the public repo except .git/ so stale
# files (no longer in sync-public.json) don't linger. Safety: refuses to
# wipe a folder that isn't an initialized git repo.
clear_public_root() {
  local root="$1"
  [[ -d "$root" ]] || return 0
  if [[ ! -d "$root/.git" ]]; then
    echo "ERROR: refusing to wipe '$root' - no .git/ found there." >&2
    exit 3
  fi
  echo "Clearing $root (preserving .git/)"
  while IFS= read -r -d '' entry; do
    local name
    name="$(basename "$entry")"
    [[ "$name" == ".git" ]] && continue
    if $DRY_RUN; then
      echo "  would remove: $name"
    else
      rm -rf "$entry"
    fi
  done < <(find "$root" -mindepth 1 -maxdepth 1 -print0)
  echo
}
clear_public_root "$PUBLIC_ROOT"

COPIED=()

is_excluded() {
  local p="$1"
  for pat in "${EXCLUDE_PATTERNS[@]}"; do
    [[ "$p" == *"$pat"* ]] && return 0
  done
  return 1
}

# Copy src tree into dst, honoring exclude_patterns. dst was already
# removed (along with everything else outside .git/) by clear_public_root
# above, so we just need to recreate it.
sync_tree() {
  local src="$1" dst="$2"
  [[ -d "$src" ]] || return 0
  if ! $DRY_RUN; then mkdir -p "$dst"; fi
  while IFS= read -r -d '' f; do
    is_excluded "$f" && continue
    local rel="${f#"$src/"}"
    local dest="$dst/$rel"
    COPIED+=("${dest#"$PUBLIC_ROOT/"}")
    if ! $DRY_RUN; then
      mkdir -p "$(dirname "$dest")"
      cp -p "$f" "$dest"
    fi
  done < <(find "$src" -type f -print0)
}

# ── Main ─────────────────────────────────────────────────────────────────────
$DRY_RUN || mkdir -p "$PUBLIC_ROOT"

# 1. copy_dirs
for d in "${COPY_DIRS[@]}"; do
  sync_tree "$DEV_ROOT/$d" "$PUBLIC_ROOT/$d"
done

# 2. copy_files (supports nested paths like .github/workflows/foo.yml)
for f in "${COPY_FILES[@]}"; do
  if [[ -f "$DEV_ROOT/$f" ]]; then
    COPIED+=("$f")
    if ! $DRY_RUN; then
      mkdir -p "$PUBLIC_ROOT/$(dirname "$f")"
      cp -p "$DEV_ROOT/$f" "$PUBLIC_ROOT/$f"
    fi
  fi
done

echo "Copied ${#COPIED[@]} file(s):"
printf '%s\n' "${COPIED[@]}" | sort | sed 's/^/  /'

if ! $DRY_RUN; then
  echo
  echo "Done. Review changes in $PUBLIC_ROOT before committing."
fi
