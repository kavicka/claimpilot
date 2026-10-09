#!/usr/bin/env bash
# PostToolUse: ruff on the Python file that was just edited; pyright errors are reported back.
input=$(cat)
file=$(printf '%s' "$input" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("tool_input",{}).get("file_path",""))')
[[ "$file" == *.py && -f "$file" ]] || exit 0
cd "$CLAUDE_PROJECT_DIR" || exit 0
uv run --quiet --no-sync ruff format "$file" >/dev/null 2>&1
uv run --quiet --no-sync ruff check --fix "$file" >/dev/null 2>&1
out=$(uv run --quiet --no-sync pyright "$file" 2>&1 | grep -E "error:" | head -10)
if [[ -n "$out" ]]; then
  printf 'pyright errors in %s:\n%s\n' "$file" "$out" >&2
  exit 2
fi
exit 0
