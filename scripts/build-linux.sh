#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if ! python3 -m venv --help >/dev/null 2>&1; then
  echo "[ERROR] python3-venv is not installed."
  echo "Install: sudo apt update && sudo apt install -y python3-venv"
  exit 1
fi

if [ ! -d ".venv-build" ]; then
  python3 -m venv .venv-build
fi

.venv-build/bin/python -m pip install -U pip
.venv-build/bin/python -m pip install -r requirements-dev.txt
.venv-build/bin/python -m pip install -e .
.venv-build/bin/python scripts/build-cli.py
.venv-build/bin/python scripts/build-desktop.py
.venv-build/bin/python scripts/package-linux.py

echo "[OK] Built PackeTech Linux packages in dist/release"
