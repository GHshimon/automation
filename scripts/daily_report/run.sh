#!/bin/bash
# launchd から呼ばれるラッパー。launchd はシェルプロファイルを読まないため、
# ここで PATH(Homebrew)と venv を明示的に設定する。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

VENV="$SCRIPT_DIR/.venv"
if [ ! -x "$VENV/bin/python3" ]; then
  echo "venv が見つかりません。先に install.sh を実行してください。" >&2
  exit 1
fi

exec "$VENV/bin/python3" "$SCRIPT_DIR/report.py" "$@"
