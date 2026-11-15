#!/bin/sh
# Run every automated test: Python data tests, then the in-game tests (headless Godot).
# Usage: tools/run_tests.sh [path-to-godot]     (or set GODOT=...)
# Exit code is non-zero if anything failed. Results: tests/out/results.json
REPO="$(cd "$(dirname "$0")/.." && pwd)"
GODOT="${1:-${GODOT:-godot}}"
cd "$REPO"
mkdir -p tests/out
python3 tests/test_data.py; DATA=$?
"$GODOT" --headless --path . --import >/dev/null 2>&1
# 1) every script must compile (a parse error otherwise hangs the game instead of failing)
COMPILE=0
for f in $(find scripts tests -name "*.gd"); do
  out=$(timeout 60 "$GODOT" --headless --path . --check-only --script "$f" 2>&1 | grep -E "SCRIPT ERROR|Parse Error")
  if [ -n "$out" ]; then echo "[compile] FAIL $f"; echo "$out" | head -3; COMPILE=$((COMPILE+1)); else echo "[compile] PASS $f"; fi
done
[ "$COMPILE" = "0" ] || { echo "== $COMPILE scripts failed to compile; skipping game tests"; exit 1; }
rm -f tests/out/results.json
timeout 600 "$GODOT" --headless --path . -- --test=res://tests/out/results.json 2>&1 | grep -E "^\[test\]|SCRIPT ERROR|ERROR:.*res://" ; GAME=$(python3 -c "import json;print(json.load(open('tests/out/results.json'))['failed'])" 2>/dev/null || echo 99)
echo "== data tests failed: $DATA   game tests failed: $GAME"
[ "$DATA" = "0" ] && [ "$GAME" = "0" ]
