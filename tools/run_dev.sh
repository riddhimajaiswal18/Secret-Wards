#!/usr/bin/env bash
# One command per gate.  usage: tools/run_dev.sh [input_dir] [output_dir]
set -eu
here=$(cd "$(dirname "$0")/.." && pwd)
kit=${KIT:-/Users/saichaitu/secret-wards/kit}
inp=${1:-$kit/dev/input}
out=${2:-$here/build/out}
cd "$here"
echo "== contract =="    && python3 "$kit/validate_output.py" --input "$inp" --output "$out" | tail -8
echo "== determinism ==" && rm -rf "$out.2" && python3 main.py --input "$inp" --output "$out.2" --quiet \
  && { diff -r -x report.json -x records.jsonl "$out" "$out.2" >/dev/null && echo "DETERMINISM OK"; } \
  || { echo "DETERMINISM FAIL"; diff -r -x report.json -x records.jsonl "$out" "$out.2" | head -5; }
rm -rf "$out.2"
echo "== verify ==" && { python3 tools/verify.py "$inp" "$out" || { echo "RELEASE BLOCKED: verification failed"; exit 1; }; }
echo "== score ==" && python3 "$kit/check_dev.py" --output "$out" 2>&1 | head -26
