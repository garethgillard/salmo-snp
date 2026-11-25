#!/usr/bin/env bash
# What CI's tests job runs (.github/workflows/tests.yml calls this): pyflakes on the code (the tests' pytest fixtures
# look unused to it, so tests are left out), then the four test suites side by side, the page tests on every core
# (manage.py test --parallel). Run it before pushing: about 2 minutes on 4 cores (8 one after the other, until
# 2026-11-25), and it needs no network and no data. A suite that fails prints all it wrote; one suite alone: AGENTS.md
# "Development".
#   bash tools/check.sh
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHONPATH=tools/pyflakes-4.1.0-py2.py3-none-any.whl python -m pyflakes snpscore/src snpdata/src snpdata/prep \
  snpportal/snpsite $(ls -d snpportal/snpportal/*.py snpportal/snpportal/*/ | grep -v -e /tests -e /static/ -e /templates/ -e /__pycache__/)
logs=$(mktemp -d)
trap 'kill $(jobs -p) 2>/dev/null || true; rm -rf "$logs"' EXIT
names=() pids=()
suite() {  # <name> <folder> <command ...>: started now, its output kept until every suite is done
  names+=("$1")
  (cd "$2" && shift 2 && exec "$@") > "$logs/$1" 2>&1 &
  pids+=($!)
}
suite snpscore snpscore python -m pytest -q
suite snpdata snpdata python -m pytest -q
suite "snpportal lib" snpportal python -m pytest -q tests
suite "snpportal pages" snpportal env SNPPORTAL_WORKERS=0 python manage.py test snpportal --parallel
failed=()
for i in "${!pids[@]}"; do
  if wait "${pids[$i]}"; then
    echo "${names[$i]}: $(grep -E '^(Ran [0-9]+ tests? in|OK|[0-9]+ passed)' "$logs/${names[$i]}" | tail -n 2 | paste -sd' ' -)"
  else
    failed+=("${names[$i]}")
    echo "==== ${names[$i]}: FAILED ===="
    cat "$logs/${names[$i]}"
  fi
done
[ ${#failed[@]} -eq 0 ] || { echo "check: failed: ${failed[*]}"; exit 1; }
echo "check: all passed ($(python --version))"
