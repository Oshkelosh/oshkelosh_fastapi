#!/usr/bin/env bash
# Commit and push each nested addon git repo under app/addons/<category>/<name>/.
#
# Usage:
#   ./scripts/commit_push_addons.sh -m "Shipping quote fixes"
#   ./scripts/commit_push_addons.sh -m "…" --dry-run
#   ./scripts/commit_push_addons.sh -m "…" --no-push
#
# Skips clean trees and trees that only have __pycache__ / *.py[cod] noise.
# Continues on per-addon errors; exits non-zero if any failed.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

MSG=""
DRY_RUN=0
NO_PUSH=0
ASSUME_YES=0

usage() {
  cat <<'EOF'
Usage: ./scripts/commit_push_addons.sh -m "message" [--dry-run] [--no-push] [--yes]

Commit and push each nested addon repo under app/addons/*/*/.

Options:
  -m MESSAGE   Commit message (required; same for every addon that commits)
  --dry-run    Print what would happen; no git writes
  --no-push    Commit only; do not push
  --yes        Skip the interactive confirmation (for CI/automation)
  -h, --help   Show this help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -m)
      [[ $# -ge 2 ]] || { echo "error: -m requires a message" >&2; exit 2; }
      MSG="$2"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --no-push)
      NO_PUSH=1
      shift
      ;;
    --yes)
      ASSUME_YES=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "error: unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "$MSG" ]]; then
  echo "error: -m MESSAGE is required" >&2
  usage >&2
  exit 2
fi

# Return 0 if every porcelain path is __pycache__ / bytecode noise.
is_pycache_only() {
  local dir="$1" line path
  while IFS= read -r line; do
    [[ -n "$line" ]] || continue
    path="${line:3}"
    # renames: "R  old -> new" — treat as real work
    if [[ "$path" == *" -> "* ]]; then
      return 1
    fi
    case "$path" in
      *__pycache__*|*.pyc|*.pyo|*.pyd|*\$py.class) ;;
      *) return 1 ;;
    esac
  done < <(git -C "$dir" status --porcelain)
  return 0
}

committed=0
pushed=0
skipped=0
failed=0

shopt -s nullglob
addons=(app/addons/*/*/)
shopt -u nullglob

# Mass `git add -A` + commit + push across many repos is destructive if run
# by accident — require an explicit yes unless --dry-run/--yes.
if [[ "$DRY_RUN" -eq 0 && "$ASSUME_YES" -eq 0 ]]; then
  action="commit"
  [[ "$NO_PUSH" -eq 0 ]] && action="commit AND PUSH"
  echo "This will ${action} every dirty addon repo under app/addons/*/*/ with message: \"$MSG\""
  read -r -p "Proceed? [y/N] " answer
  case "$answer" in
    y|Y|yes|YES) ;;
    *) echo "Aborted."; exit 0 ;;
  esac
fi

for addon_dir in "${addons[@]}"; do
  addon_dir="${addon_dir%/}"
  [[ -e "$addon_dir/.git" ]] || continue

  rel="${addon_dir#app/addons/}"

  if [[ -z "$(git -C "$addon_dir" status --porcelain)" ]]; then
    echo "skip: clean  $rel"
    skipped=$((skipped + 1))
    continue
  fi

  if is_pycache_only "$addon_dir"; then
    echo "skip: pycache only  $rel"
    skipped=$((skipped + 1))
    continue
  fi

  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "would commit+push  $rel"
    if [[ "$NO_PUSH" -eq 1 ]]; then
      echo "  (no-push: commit only)"
    fi
    git -C "$addon_dir" status --short | sed 's/^/  /'
    committed=$((committed + 1))
    if [[ "$NO_PUSH" -eq 0 ]]; then
      pushed=$((pushed + 1))
    fi
    continue
  fi

  echo "commit  $rel"
  if ! git -C "$addon_dir" add -A; then
    echo "fail: add  $rel" >&2
    failed=$((failed + 1))
    continue
  fi
  if ! git -C "$addon_dir" commit -m "$MSG"; then
    echo "fail: commit  $rel" >&2
    failed=$((failed + 1))
    continue
  fi
  committed=$((committed + 1))

  if [[ "$NO_PUSH" -eq 1 ]]; then
    continue
  fi

  echo "push  $rel"
  if ! git -C "$addon_dir" push; then
    echo "fail: push  $rel" >&2
    failed=$((failed + 1))
    continue
  fi
  pushed=$((pushed + 1))
done

echo ""
echo "summary: committed=$committed pushed=$pushed skipped=$skipped failed=$failed"

if [[ "$failed" -gt 0 ]]; then
  exit 1
fi
