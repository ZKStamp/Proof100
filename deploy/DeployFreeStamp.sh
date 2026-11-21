#!/bin/bash
# Deploy the free stamp_hash / check_stamp tools (21 Nov 2026).
# Run on the server as root:  bash DeployFreeStamp.sh
# Safe: stops if the server code differs from what this update expects,
# verifies every download, backs everything up, and rolls back if the API does not come back.
set -euo pipefail

APP=/root/proof100
WEB=/var/www/proof100/llms.txt
BACKUP=/root/Proof100Backup21Nov
RAW=https://raw.githubusercontent.com/ZKStamp/Proof100/freestamp

OLD_API=829f1ff221f1f9670caca2b4a201309b7c1341b5a2aee015747620645f16aa92
declare -A WANT=(
  [server/Proof100Api.py]=c39adc84aaf9f704fb86c9dafc56fd78e69ed9667b637e22018f5f9ed42f3a49
  [server/FreeStamp.py]=2c7ded2fb4566d40e79fa70e1e53e11d2b37e9d3a0c46307461bca6ae85199c3
  [server/FreeReport.py]=f65ae5ed49a9530b536514f8ac1383e6b93cae8ebfa7b0c4d714b3210a575889
  [deploy/llms.txt]=9cac7b4ab33f039486b9d86056ee90b54f1f7ae1514d3bed7cabd94b608e94eb
)

echo "== 1. Check the server runs the expected version"
HAVE=$(sha256sum "$APP/Proof100Api.py" | cut -d' ' -f1)
if [ "$HAVE" = "${WANT[server/Proof100Api.py]}" ]; then
  echo "Already updated. Nothing to do."; exit 0
fi
if [ "$HAVE" != "$OLD_API" ]; then
  echo "STOP: $APP/Proof100Api.py is not the version this update expects."
  echo "Nothing was changed. Send this line to Claude: $HAVE"; exit 1
fi

echo "== 2. Download and verify the new files"
TMP=$(mktemp -d)
for f in "${!WANT[@]}"; do
  curl -fsSL "$RAW/$f" -o "$TMP/$(basename "$f")"
  GOT=$(sha256sum "$TMP/$(basename "$f")" | cut -d' ' -f1)
  if [ "$GOT" != "${WANT[$f]}" ]; then
    echo "STOP: $f does not match (got $GOT). Nothing was changed."; exit 1
  fi
  echo "  ok $f"
done
python3 -m py_compile "$TMP/Proof100Api.py" "$TMP/FreeStamp.py" "$TMP/FreeReport.py"

echo "== 3. Backup to $BACKUP"
mkdir -p "$BACKUP"
cp -a "$APP/Proof100Api.py" "$APP/Proof100.db" "$BACKUP/"
[ -f "$WEB" ] && cp -a "$WEB" "$BACKUP/llms.txt"

echo "== 4. Install"
cp "$TMP/Proof100Api.py" "$TMP/FreeStamp.py" "$TMP/FreeReport.py" "$APP/"
cp "$TMP/llms.txt" "$WEB"
systemctl restart Proof100Api
sleep 4

echo "== 5. Test (costs nothing)"
LIST=$(curl -s -X POST http://127.0.0.1:5100/mcp -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' || true)
BAD=$(curl -s -X POST http://127.0.0.1:5100/v1/free/stamp -H "Content-Type: application/json" -d '{"sha256":"test"}' || true)
if echo "$LIST" | grep -q '"stamp_hash"' && echo "$BAD" | grep -q "64-character"; then
  ls -l "$APP/FreeSalt.txt" 2>/dev/null || true
  echo "DONE: stamp_hash and check_stamp are live. Backup: $BACKUP"
else
  echo "Test failed, rolling back..."
  cp -a "$BACKUP/Proof100Api.py" "$APP/"
  [ -f "$BACKUP/llms.txt" ] && cp -a "$BACKUP/llms.txt" "$WEB"
  systemctl restart Proof100Api
  echo "Rolled back. Send this to Claude:"; echo "$LIST" | head -c 300; echo; echo "$BAD" | head -c 300
  journalctl -u Proof100Api -n 20 --no-pager
  exit 1
fi
