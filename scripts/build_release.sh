#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
NAME="SUPER_TRADING_BOT_1.2.0"
OUT="$ROOT/dist"
mkdir -p "$OUT"
cd "$(dirname "$ROOT")"
zip -qr "$OUT/${NAME}.zip" "$(basename "$ROOT")" \
  -x '*/.env' '*/backend/.env' '*/.bridge_token' '*/sent_positions.json' \
     '*/.venv/*' '*/__pycache__/*' '*/.pytest_cache/*' '*/tests/.test_data/*' '*/data/*.db' '*/data/*.sqlite3' '*/backups/*' '*/dist/*' '*.pyc'
sha256sum "$OUT/${NAME}.zip" > "$OUT/${NAME}.sha256"
echo "Release created: $OUT/${NAME}.zip"
