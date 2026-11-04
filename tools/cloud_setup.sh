#!/usr/bin/env bash
# Cloud sessions (Claude Code on the web): .claude/settings.json runs this at session start; on a local machine it does
# nothing. It makes .venv with CI's Python (3.12; uv downloads it if the image lacks it) and the three folders
# installed editable with the newest versions their pyproject.toml files allow, as CI and deploys get them, and puts
# .venv/bin first on the session's PATH, so the commands in AGENTS.md work as written. The tests need nothing else;
# the data for real use comes on demand: bash tools/get_data.sh (AGENTS.md "Cloud sessions").
set -euo pipefail
[ "${CLAUDE_CODE_REMOTE:-}" = "true" ] || exit 0
cd "${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
PYTHON=3.12  # .github/workflows/tests.yml's python-version: change both together
PACKAGES=(-e "snpscore[test]" -e snpdata -e snpportal)
works() { .venv/bin/python -c "import snpscore, snpdata, snpportal, django, pytest" 2>/dev/null; }
wanted() { [ "$(.venv/bin/python -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null)" = "$PYTHON" ]; }
if command -v uv >/dev/null && ! { works && wanted; }; then
  uv venv -q --clear --python "$PYTHON" .venv || uv venv -q --clear --python python3 .venv
  uv pip install -q --python .venv/bin/python "${PACKAGES[@]}"
elif ! works; then
  python3 -m venv --clear .venv && .venv/bin/pip install -q --upgrade pip && .venv/bin/pip install -q "${PACKAGES[@]}"
fi
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then echo "export PATH=\"$PWD/.venv/bin:\$PATH\"" >> "$CLAUDE_ENV_FILE"; fi
echo "cloud setup: $(.venv/bin/python --version) in .venv with snpscore, snpdata and salmo-snp (AGENTS.md \"Cloud sessions\")"
