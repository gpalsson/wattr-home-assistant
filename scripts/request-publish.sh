#!/usr/bin/env bash
# Check, commit and push this standalone HACS repository as one action.
set -euo pipefail
cd "$(dirname "$0")/.."
subject=${1:?Usage: bash scripts/request-publish.sh "What changed and why"}
[[ $(git branch --show-current) != main ]] || { echo 'Use a feature branch and PR.' >&2; exit 1; }
ha_test_python=${HA_TEST_PYTHON:-python3}
"$ha_test_python" -m ruff check .
"$ha_test_python" -m pytest -q
git diff --check
git add brand custom_components tests scripts .github .gitignore README.md LICENSE hacs.json pyproject.toml requirements-test.txt
if git diff --cached --name-only | grep -q '^\.local/'; then
    echo 'Refusing to commit private files.' >&2; exit 1
fi
git commit -m "$subject"
git push -u origin HEAD
