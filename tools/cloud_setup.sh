#!/usr/bin/env bash
# Cloud sessions (Claude Code on the web): .claude/settings.json runs this at session start; on a local machine it does
# nothing. It makes .venv with the Python and the versions CI's tests job pins (Python 3.8, Django 4.2, DuckDB 1.2.2;
# uv downloads that Python) and the three folders installed editable, and puts .venv/bin first on the session's PATH,
# so the commands in AGENTS.md work as written and test what CI tests. If uv can't get that Python it falls back to
# the system python3 with the newest allowed versions (CI then is the only check on 3.8). The tests need nothing else;
# the data for real use comes on demand: bash tools/get_data.sh (AGENTS.md "Cloud sessions").
set -euo pipefail
[ "${CLAUDE_CODE_REMOTE:-}" = "true" ] || exit 0
cd "${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
PYTHON=3.8  # .github/workflows/tests.yml's python-version: change both together (AGENTS.md "Rules")
PACKAGES=(-e "snpscore[test]" -e snpdata -e snpportal)
PINS=("django>=4.2,<5" "duckdb==1.2.2")  # as the tests job and the NREC demo
works() { .venv/bin/python -c "import snpscore, snpdata, snpportal, django, pytest" 2>/dev/null; }
wanted() { [ "$(.venv/bin/python -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null)" = "$PYTHON" ]; }
if command -v uv >/dev/null && ! { works && wanted; }; then
  if uv venv -q --clear --python "$PYTHON" .venv 2>/dev/null; then
    uv pip install -q --python .venv/bin/python "${PACKAGES[@]}" "${PINS[@]}"
  else
    echo "cloud setup: uv could not get Python $PYTHON, using $(python3 --version)" >&2
    uv venv -q --clear --python python3 .venv && uv pip install -q --python .venv/bin/python "${PACKAGES[@]}"
  fi
elif ! works; then
  python3 -m venv --clear .venv && .venv/bin/pip install -q --upgrade pip && .venv/bin/pip install -q "${PACKAGES[@]}"
fi
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then echo "export PATH=\"$PWD/.venv/bin:\$PATH\"" >> "$CLAUDE_ENV_FILE"; fi
echo "cloud setup: $(.venv/bin/python --version) in .venv with snpscore, snpdata and salmo-snp (AGENTS.md \"Cloud sessions\")"
