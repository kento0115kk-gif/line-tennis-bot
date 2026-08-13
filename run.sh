#!/bin/bash
# 定期実行用のラッパー。launchd から呼ばれる。
# 手動実行も可能: ./run.sh

set -u

DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$DIR/logs"
LOG="$LOG_DIR/notify.log"

mkdir -p "$LOG_DIR"

# ログが 5MB を超えたら 1 世代だけ残して切り詰める。
if [ -f "$LOG" ] && [ "$(stat -f%z "$LOG")" -gt 5242880 ]; then
  mv "$LOG" "$LOG.1"
fi

echo "===== $(date '+%Y-%m-%d %H:%M:%S') 開始 =====" >>"$LOG"
"$DIR/.venv/bin/python" "$DIR/main.py" --weeks 2 >>"$LOG" 2>&1
CODE=$?
echo "----- 終了 (exit=$CODE) -----" >>"$LOG"
exit $CODE
