#!/usr/bin/env bash
# Chanakya verification entrypoint. Run before starting work and before claiming a task done.
#   ./init.sh                 Python tests, Ruff, frontend lint and tests
#   FULL=1 ./init.sh          also the frontend production build
#   SKIP_INSTALL=1 ./init.sh  never install dependencies
#   NEURAL=1 ./init.sh        also the neural brain: encoder libraries, model download, checks with the real model
set -euo pipefail

APP_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$APP_ROOT"
echo "=== Chanakya verification ==="

# Take the first interpreter that actually runs: on Windows, python3 can be a Microsoft Store stub.
PYTHON=()
for candidate in "python3.12" "py -3.12" "python3" "python" "py -3"; do
  read -r -a cmd <<< "$candidate"
  if command -v "${cmd[0]}" >/dev/null 2>&1 \
      && "${cmd[@]}" -c 'import sys; assert sys.version_info >= (3, 12)' >/dev/null 2>&1; then
    PYTHON=("${cmd[@]}")
    break
  fi
done
VENV="$APP_ROOT/.venv"
# Windows virtualenvs keep the interpreter in Scripts/, POSIX ones in bin/.
venv_python() {
  if [ -x "$VENV/Scripts/python.exe" ]; then echo "$VENV/Scripts/python.exe"; else echo "$VENV/bin/python"; fi
}
# 3.11's asyncio.wait_for can swallow cancellation, which hangs voice session teardown tests.
# An existing 3.12 virtualenv is enough when no 3.12 interpreter is on PATH.
[ ${#PYTHON[@]} -gt 0 ] || "$(venv_python)" -c 'import sys; assert sys.version_info >= (3, 12)' >/dev/null 2>&1 \
  || { echo "Python 3.12+ required (see pyproject.toml)"; exit 1; }
if [ ! -x "$(venv_python)" ]; then
  [ -n "${SKIP_INSTALL:-}" ] && { echo "No virtualenv at $VENV and SKIP_INSTALL is set"; exit 1; }
  echo "--- Creating virtualenv with $("${PYTHON[@]}" --version) and installing locked dependencies"
  "${PYTHON[@]}" -m venv "$VENV"
  "$(venv_python)" -m pip install -q --upgrade pip
  "$(venv_python)" -m pip install -q -r "$APP_ROOT/requirements.lock.txt"
fi
PY="$(venv_python)"
if [ -z "${SKIP_INSTALL:-}" ] && ! "$PY" -c 'import pytest, ruff' 2>/dev/null; then
  "$PY" -m pip install -q pytest ruff
fi

echo "--- Inherited unit tests: agent"
"$PY" -m unittest discover -s agent -t . -q
echo "--- Inherited unit tests: backend"
"$PY" -m unittest discover -s backend -t . -q

if [ -d chanakya ] || [ -d tests ]; then
  echo "--- pytest"
  "$PY" -m pytest
fi

if [ -f pyproject.toml ] && grep -q '\[tool.ruff' pyproject.toml; then
  echo "--- Ruff lint"
  "$PY" -m ruff check .
fi

if [ -n "${NEURAL:-}" ]; then
  echo "--- Neural brain (real encoder)"
  if [ -z "${SKIP_INSTALL:-}" ]; then
    "$PY" -m pip install -q -r "$APP_ROOT/requirements-neural.txt"
    "$PY" -m chanakya.neural.encoder --download
  else
    "$PY" -m chanakya.neural.encoder
  fi
  "$PY" -m chanakya.neural.human_set
  # The same tests again, now that the model is present: the ones that skip without it run here.
  "$PY" -m pytest -q chanakya/neural chanakya/brain/tests/test_belief.py
fi

FRONTEND="$APP_ROOT/frontend"
if [ -f "$FRONTEND/package.json" ]; then
  if [ ! -d "$FRONTEND/node_modules" ]; then
    [ -n "${SKIP_INSTALL:-}" ] && { echo "No node_modules and SKIP_INSTALL is set"; exit 1; }
    echo "--- Installing frontend dependencies"
    (cd "$FRONTEND" && npm ci --no-audit --no-fund --silent)
  fi
  echo "--- Frontend tests and lint"
  (cd "$FRONTEND" && npm test --silent && npm run lint --silent)
  if [ -n "${FULL:-}" ]; then
    echo "--- Frontend build"
    (cd "$FRONTEND" && npm run build --silent)
  fi
fi

echo ""
echo "=== Verification passed ==="
echo "Next steps:"
echo "1. Open feature_list.json and take the first not-started task in your track whose dependencies are done"
echo "2. Read its spec in docs/TASKS.md; work only in the directories it owns"
echo "3. Re-run ./init.sh and record evidence before marking it done"
