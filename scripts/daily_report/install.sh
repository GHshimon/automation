#!/bin/bash
# 毎朝6時の業界ニュースレポートをセットアップする。
# 実行内容: venv 作成 → 依存インストール → launchd ジョブ登録 → 事前チェック
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$HOME/Library/Logs/daily-report"
PLIST_LABEL="com.user.daily-report"
PLIST_DEST="$HOME/Library/LaunchAgents/$PLIST_LABEL.plist"

echo "==> 1/4 Python venv と依存パッケージ"
if [ ! -d "$SCRIPT_DIR/.venv" ]; then
  python3 -m venv "$SCRIPT_DIR/.venv"
fi
"$SCRIPT_DIR/.venv/bin/pip" install -q -r "$SCRIPT_DIR/requirements.txt"

echo "==> 2/4 事前チェック"
warn=0
if ! command -v rclone >/dev/null; then
  echo "  ⚠️  rclone が未インストールです: brew install rclone" ; warn=1
elif ! rclone listremotes 2>/dev/null | grep -q "^gdrive:"; then
  echo "  ⚠️  rclone に 'gdrive' リモートがありません: rclone config で作成してください" ; warn=1
fi
if ! security find-generic-password -s xai-api-key >/dev/null 2>&1 && [ -z "${XAI_API_KEY:-}" ]; then
  echo "  ⚠️  xAI API キーが未設定です:"
  echo "      security add-generic-password -s xai-api-key -a \"\$USER\" -w '<YOUR_XAI_KEY>'"
  warn=1
fi
if ! command -v terminal-notifier >/dev/null; then
  echo "  ℹ️  terminal-notifier がないため通知はスキップされます(brew install terminal-notifier)"
fi
[ "$warn" -eq 0 ] && echo "  ✅ 必須要件 OK"

echo "==> 3/4 launchd ジョブ登録(毎朝6時)"
mkdir -p "$LOG_DIR" "$HOME/Library/LaunchAgents"
sed -e "s|__SCRIPT_DIR__|$SCRIPT_DIR|g" -e "s|__LOG_DIR__|$LOG_DIR|g" \
  "$SCRIPT_DIR/com.user.daily-report.plist.template" > "$PLIST_DEST"
launchctl bootout "gui/$(id -u)/$PLIST_LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST_DEST"
echo "  ✅ 登録完了: $PLIST_DEST"

echo "==> 4/4 動作確認コマンド"
echo "  手動テスト(アップロードなし): $SCRIPT_DIR/run.sh --dry-run"
echo "  本番と同じ実行:               launchctl kickstart gui/\$(id -u)/$PLIST_LABEL"
echo "  ログ確認:                     tail -f $LOG_DIR/daily-report.log"
echo "  停止:                         launchctl bootout gui/\$(id -u)/$PLIST_LABEL"
