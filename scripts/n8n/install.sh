#!/bin/bash
# n8n を macOS にローカル導入する(npm ローカル隔離 + launchd 常駐)。
# 実行内容: node@22 確認 → n8n をローカル prefix へインストール →
#           launchd 常駐ジョブ登録 → 起動確認。
#
# システムの node(v26 など)は n8n 非対応の可能性があるため触らず、
# Homebrew の node@22(keg-only)を専用ランタイムとして使う。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$HOME/Library/Logs/n8n"
PLIST_LABEL="com.user.n8n"
PLIST_DEST="$HOME/Library/LaunchAgents/$PLIST_LABEL.plist"
RUNTIME_PREFIX="$SCRIPT_DIR/.n8n-runtime"

echo "==> 1/4 Node ランタイム(node@22)"
if ! brew list --versions node@22 >/dev/null 2>&1; then
  echo "  node@22 をインストールします..."
  brew install node@22
fi
NODE22_BIN="$(brew --prefix node@22)/bin"
echo "  ✅ node@22: $("$NODE22_BIN/node" -v)"

echo "==> 2/4 n8n インストール(ローカル隔離: $RUNTIME_PREFIX)"
if [ -x "$RUNTIME_PREFIX/bin/n8n" ]; then
  echo "  既にインストール済み: $("$RUNTIME_PREFIX/bin/n8n" --version 2>/dev/null || echo '?')"
  echo "  更新する場合: PATH=\"$NODE22_BIN:\$PATH\" npm install -g --prefix \"$RUNTIME_PREFIX\" n8n@latest"
else
  mkdir -p "$RUNTIME_PREFIX"
  PATH="$NODE22_BIN:$PATH" npm install -g --prefix "$RUNTIME_PREFIX" n8n
  echo "  ✅ n8n: $("$RUNTIME_PREFIX/bin/n8n" --version 2>/dev/null || echo installed)"
fi

echo "==> 3/4 launchd 常駐ジョブ登録"
mkdir -p "$LOG_DIR" "$HOME/Library/LaunchAgents"
sed -e "s|__SCRIPT_DIR__|$SCRIPT_DIR|g" -e "s|__LOG_DIR__|$LOG_DIR|g" \
  "$SCRIPT_DIR/com.user.n8n.plist.template" > "$PLIST_DEST"
launchctl bootout "gui/$(id -u)/$PLIST_LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST_DEST"
echo "  ✅ 登録完了: $PLIST_DEST(ログイン中は常駐・自動再起動)"

echo "==> 4/4 起動確認"
echo -n "  n8n の起動を待機中"
for i in $(seq 1 30); do
  if curl -sf -o /dev/null "http://127.0.0.1:5678/healthz" 2>/dev/null; then
    echo " ✅"
    echo "  エディタ: http://localhost:5678  (ブラウザで開いて初回のオーナー登録)"
    echo
    echo "次の手順:"
    echo "  1. http://localhost:5678 を開き、オーナーアカウントを作成(ローカル保存のみ)"
    echo "  2. 右上メニュー → Import from File で workflows/daily-report.json を読み込み"
    echo "  3. ワークフローを Active にする(毎朝6時に自動実行)"
    echo "  4. 旧 launchd ジョブを停止(重複防止):"
    echo "       launchctl bootout gui/\$(id -u)/com.user.daily-report"
    echo
    echo "運用: ログ=tail -f $LOG_DIR/n8n.log / 停止=launchctl bootout gui/\$(id -u)/$PLIST_LABEL"
    exit 0
  fi
  sleep 2; echo -n "."
done
echo
echo "  ⚠️  30秒以内に起動を確認できませんでした。ログを確認してください:"
echo "      tail -50 $LOG_DIR/n8n.log"
exit 1
