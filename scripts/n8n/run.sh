#!/bin/bash
# launchd から呼ばれる n8n 起動ラッパー。
# launchd はシェルプロファイルを読まないため、ここで PATH・Node ランタイム・
# n8n の環境変数を明示的に設定する。
#
# Node は node@22(Homebrew, keg-only)を使う。システムの node(v26 など n8n 非対応)
# には触れず、n8n は $SCRIPT_DIR/.n8n-runtime にローカル隔離インストールしている。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- Node ランタイム(node@22)と n8n バイナリを PATH に通す ---
NODE22_BIN="$(brew --prefix node@22 2>/dev/null)/bin"
RUNTIME_BIN="$SCRIPT_DIR/.n8n-runtime/bin"
export PATH="$NODE22_BIN:$RUNTIME_BIN:/opt/homebrew/bin:/usr/local/bin:$PATH"

if ! command -v n8n >/dev/null; then
  echo "n8n が見つかりません。先に install.sh を実行してください。" >&2
  exit 1
fi

# --- n8n 設定(localhost 個人利用向け) ---
# データ(ワークフロー・認証情報・暗号鍵)は $N8N_USER_FOLDER/.n8n に作られる。
# ベースをホームにすると ~/.n8n に永続化される($HOME/.n8n を指定すると
# ~/.n8n/.n8n と入れ子になるので注意)。
export N8N_USER_FOLDER="${N8N_USER_FOLDER:-$HOME}"
export N8N_HOST="127.0.0.1"
export N8N_PORT="5678"
export N8N_PROTOCOL="http"
export N8N_LISTEN_ADDRESS="127.0.0.1"   # ローカルのみ待受(外部公開しない)
export N8N_SECURE_COOKIE="false"        # http://localhost アクセスを許可
export N8N_RUNNERS_ENABLED="true"       # 新しいタスクランナー方式(将来の既定)
export N8N_DIAGNOSTICS_ENABLED="false"  # テレメトリ無効
export N8N_PERSONALIZATION_ENABLED="false"

# Execute Command ノードの再有効化。
# n8n 2.0 以降、executeCommand と localFileTrigger は既定の除外リスト
# (NODES_EXCLUDE)でブロックされる(任意のシェル実行はセキュリティリスクのため)。
# 本ワークフローは Execute Command で run.sh を呼ぶため、除外リストを上書きして
# executeCommand を許可する(localFileTrigger は引き続き除外)。
# ⚠️ これでワークフロー編集権限を持つ者は任意のシェルコマンドを実行できる。
#    本構成は 127.0.0.1 限定・単一オーナーのローカル運用のため許容。
#    公開・複数ユーザーで使う場合はこの行を外すこと。
export NODES_EXCLUDE='["n8n-nodes-base.localFileTrigger"]'
export GENERIC_TIMEZONE="Asia/Tokyo"
export TZ="Asia/Tokyo"

# Execute Command ノードから既存スクリプト(daily_report/run.sh)や
# rclone / security(キーチェーン)/ terminal-notifier を呼べるようにしておく。
exec n8n start
