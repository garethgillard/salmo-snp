#!/usr/bin/env bash
# Cloud sessions (Claude Code on the web): .claude/settings.json runs this at session start; on a local machine it does
# nothing. It makes .venv (Python 3.12, through uv when the image has it) with the three folders installed editable,
# and puts .venv/bin first on the session's PATH, so the commands in AGENTS.md work as written. The tests need nothing
# else; the data for real use comes on demand: bash tools/get_data.sh (AGENTS.md "Cloud sessions").
set -euo pipefail
[ "${CLAUDE_CODE_REMOTE:-}" = "true" ] || exit 0
cd "${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
PACKAGES=(-e "snpscore[test]" -e snpdata -e snpportal)
if ! .venv/bin/python -c "import snpscore, snpdata, snpportal, django, pytest" 2>/dev/null; then
  if command -v uv >/dev/null; then
    uv venv -q --python 3.12 .venv && uv pip install -q --python .venv/bin/python "${PACKAGES[@]}"
  else
    python3 -m venv .venv && .venv/bin/pip install -q --upgrade pip && .venv/bin/pip install -q "${PACKAGES[@]}"
  fi
fi
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then echo "export PATH=\"$PWD/.venv/bin:\$PATH\"" >> "$CLAUDE_ENV_FILE"; fi
echo "cloud setup: $(.venv/bin/python --version) in .venv with snpscore, snpdata and salmo-snp (AGENTS.md \"Cloud sessions\")"
