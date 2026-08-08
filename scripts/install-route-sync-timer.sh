#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TEMPLATE_DIR="$PROJECT_ROOT/integrations/systemd/user"
TARGET_DIR="$HOME/.config/systemd/user"

mkdir -p "$TARGET_DIR"
for unit in keenetic-route-sync.service keenetic-route-sync.timer; do
  sed "s|__PROJECT_ROOT__|$PROJECT_ROOT|g" "$TEMPLATE_DIR/$unit" > "$TARGET_DIR/$unit"
done

systemctl --user daemon-reload
systemctl --user enable --now keenetic-route-sync.timer
loginctl enable-linger "$USER" 2>/dev/null || true

systemctl --user status keenetic-route-sync.timer --no-pager
