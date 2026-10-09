#!/usr/bin/env bash
# Stop: run unit tests for packages with uncommitted Python changes. Blocks the stop on failure once.
input=$(cat)
if printf '%s' "$input" | grep -q '"stop_hook_active": *true'; then exit 0; fi
cd "$CLAUDE_PROJECT_DIR" || exit 0
changed=$(git status --porcelain -- '*.py' 2>/dev/null | awk '{print $2}')
[[ -z "$changed" ]] && exit 0
dirs=()
for f in $changed; do
  case "$f" in
    packages/claimpilot_core/*) dirs+=(tests/core) ;;
    services/worker/*) dirs+=(tests/worker) ;;
    services/api/*) dirs+=(tests/api) ;;
    services/core_mock/*) dirs+=(tests/core_mock) ;;
    data/generator/*) dirs+=(tests/datagen) ;;
    evals/*) dirs+=(tests/evals) ;;
    tests/*) dirs+=("$(dirname "$f")") ;;
  esac
done
[[ ${#dirs[@]} -eq 0 ]] && exit 0
uniq_dirs=$(printf '%s\n' "${dirs[@]}" | sort -u | while read -r d; do [[ -d "$d" ]] && echo "$d"; done)
[[ -z "$uniq_dirs" ]] && exit 0
if ! out=$(uv run --quiet --no-sync pytest -q -x $uniq_dirs 2>&1); then
  printf 'Tests failing in %s:\n%s\n' "$(echo $uniq_dirs)" "$(printf '%s' "$out" | tail -25)" >&2
  exit 2
fi
exit 0
