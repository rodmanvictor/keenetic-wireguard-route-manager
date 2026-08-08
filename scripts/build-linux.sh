#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if ! command -v clang++ >/dev/null 2>&1 || ! pkg-config --exists gtk+-3.0; then
  echo "[ERROR] Linux desktop build toolchain is incomplete."
  echo "Install: sudo apt-get install -y clang cmake ninja-build pkg-config libgtk-3-dev liblzma-dev"
  exit 1
fi

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
.venv-build/bin/flet build linux . \
  --module-name desktop_app \
  --project keenetic-router \
  --artifact keenetic-router \
  --product "Keenetic Routes" \
  --org ru.rodman \
  --description "Управление доменами и маршрутами WireGuard на Keenetic" \
  --output dist/desktop \
  --yes

echo "[OK] Built artifact: dist/desktop"
