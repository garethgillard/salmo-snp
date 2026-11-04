#!/usr/bin/env bash
# What CI's tests job runs (.github/workflows/tests.yml calls this): pyflakes on the code (the tests' pytest fixtures
# look unused to it, so tests are left out), then the four test suites. Run it before pushing: about 4 minutes, and it
# needs no network and no data.
#   bash tools/check.sh
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHONPATH=tools/pyflakes-3.4.0-py2.py3-none-any.whl python -m pyflakes snpscore/src snpdata/src snpdata/prep \
  snpportal/snpsite $(ls -d snpportal/snpportal/*.py snpportal/snpportal/*/ | grep -v -e /tests -e /static/ -e /templates/ -e /__pycache__/)
(cd snpscore && python -m pytest -q)
(cd snpdata && python -m pytest -q)
(cd snpportal && python -m pytest -q tests && SNPPORTAL_WORKERS=0 python manage.py test snpportal)
echo "check: all passed ($(python --version))"
