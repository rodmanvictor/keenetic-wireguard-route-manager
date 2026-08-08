#!/usr/bin/env bash
set -euo pipefail

if [ $# -lt 1 ]; then
  echo "Usage: $0 <chrome_extension_id> [python_bin]"
  echo "Example: $0 abcdefghijklmnopqrstuvwxyzabcdef"
  exit 1
fi

EXT_ID="$1"
PY_BIN_INPUT="${2:-$(command -v python3)}"

if [[ ! "$EXT_ID" =~ ^[a-p]{32}$ ]]; then
  echo "[ERROR] Extension ID must be 32 chars in [a-p]."
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
HOST_SCRIPT="$ROOT_DIR/integrations/chrome/native_host/host.py"
TEMPLATE="$ROOT_DIR/integrations/chrome/native_host/manifest.json"

if [[ "$PY_BIN_INPUT" = /* ]]; then
  PY_BIN="$PY_BIN_INPUT"
else
  PY_BIN="$ROOT_DIR/$PY_BIN_INPUT"
fi

if [ ! -x "$PY_BIN" ]; then
  echo "[ERROR] Python executable not found: $PY_BIN"
  exit 1
fi

if [ ! -x "$HOST_SCRIPT" ]; then
  echo "[ERROR] Host script not found or not executable: $HOST_SCRIPT"
  exit 1
fi

if [ ! -f "$TEMPLATE" ]; then
  echo "[ERROR] Template not found: $TEMPLATE"
  exit 1
fi

TARGET_DIR="$HOME/.config/google-chrome/NativeMessagingHosts"
mkdir -p "$TARGET_DIR"
TARGET_JSON="$TARGET_DIR/com.keenetic.router.host.json"
WRAPPER_DIR="$HOME/.local/bin"
WRAPPER_PATH="$WRAPPER_DIR/keenetic-native-host"

mkdir -p "$WRAPPER_DIR"
cat > "$WRAPPER_PATH" <<WRAP
#!/usr/bin/env bash
exec "$PY_BIN" "$HOST_SCRIPT"
WRAP
chmod +x "$WRAPPER_PATH"

sed \
  -e "s|__HOST_PATH__|$WRAPPER_PATH|g" \
  -e "s|__EXTENSION_ID__|$EXT_ID|g" \
  "$TEMPLATE" > "$TARGET_JSON"

chmod 644 "$TARGET_JSON"

echo "[OK] Installed native host manifest: $TARGET_JSON"
echo "[INFO] Host wrapper: $WRAPPER_PATH"
echo "[INFO] Allowed extension: chrome-extension://$EXT_ID/"
echo "[INFO] Open chrome://extensions/?id=$EXT_ID and turn the extension switch on."
echo "[INFO] The Reload button does not enable an extension whose switch is off."
