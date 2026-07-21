# n8n(ワークフロー自動化)ローカル導入

macOS 上に n8n をローカル導入し、launchd で常駐させる。最初のワークフローとして
既存の「毎朝6時の業界ニュースレポート」を n8n 化する。

## 設計方針

実績のある Python パイプライン(Grok 収集 → Ollama/grok 要約 → Perplexity 週次深掘り →
rclone アップロード → キーチェーン連携)は**そのまま活かし**、n8n を

- **スケジューラ**(毎朝6時トリガー)
- **オーケストレータ**(成否で分岐、通知、将来 Slack/Gmail などへ拡張)
- **可観測性レイヤ**(実行履歴・ログ・手動再実行が GUI で見える)

として被せる。全部を n8n ネイティブノードに書き直すとテスト済みロジックと
キーチェーン連携を失うため、まずはこの「ラッパー方式」から始める。

```
Schedule Trigger(0 6 * * *)
  └─ Execute Command: daily_report/run.sh(生成 + Drive アップロード)
       └─ IF(exitCode == 0)
            ├─ true  → 完了通知(terminal-notifier ✅)
            └─ false → 失敗通知(terminal-notifier ❌)
```

## Node ランタイムについて

このリポジトリを動かす Mac のシステム Node は **v26**(n8n の公式サポート外)。
そのため n8n 専用に **Homebrew の `node@22`(keg-only)** を使い、n8n 本体は
`scripts/n8n/.n8n-runtime/`(git 管理外)へ**ローカル隔離インストール**する。
システムの node には一切触れない。

## セットアップ

```bash
cd scripts/n8n

# 1. インストール(node@22 確認 → n8n ローカル導入 → launchd 常駐登録 → 起動確認)
./install.sh
```

`install.sh` が成功すると `http://localhost:5678` で n8n が常駐する。続けて:

```
2. ブラウザで http://localhost:5678 を開き、オーナーアカウントを作成
   (ローカル保存のみ。外部には送信されない)

3. 右上メニュー → "Import from File" で workflows/daily-report.json を読み込む

4. 通知の二重送信を防ぐため、Python 側の通知をオフにする:
   scripts/daily_report/config.yaml の `notify: true` を `notify: false` に
   (通知は n8n のノードが担当するため)

5. ワークフロー右上のトグルを Active にする(毎朝6時に自動実行)

6. 旧 launchd ジョブを停止(スケジューラが n8n に移るため重複防止):
   launchctl bootout gui/$(id -u)/com.user.daily-report
```

## 前提

既存の日次レポートが動く状態(= `scripts/daily_report/` のセットアップ済み:
xAI キーをキーチェーンに登録、rclone の `gdrive` リモート作成、`./install.sh` 実行済み)。
まだの場合は先に [../daily_report/README.md](../daily_report/README.md) を実施する。

## 運用コマンド

```bash
# ログ確認(n8n サーバー本体)
tail -f ~/Library/Logs/n8n/n8n.log

# 手動でワークフローを試す
#   → エディタ上で対象ワークフローを開き "Execute workflow" を押す
#   → または Execute Command ノード単体を実行して stdout/exitCode を確認

# 常駐の停止(アンインストール)
launchctl bootout gui/$(id -u)/com.user.n8n

# 再起動(設定変更後など)
launchctl kickstart -k gui/$(id -u)/com.user.n8n

# n8n の更新
PATH="$(brew --prefix node@22)/bin:$PATH" \
  npm install -g --prefix .n8n-runtime n8n@latest
launchctl kickstart -k gui/$(id -u)/com.user.n8n
```

## データの保管場所

- ワークフロー・認証情報・暗号鍵: `~/.n8n/`(SQLite)。**バックアップ対象**。
- n8n 本体バイナリ: `scripts/n8n/.n8n-runtime/`(git 管理外。再インストール可)。

## セキュリティ

- 待受は `127.0.0.1:5678` のみ(ローカル限定、外部公開なし)。
- 認証情報は `~/.n8n` 内で暗号鍵により暗号化される。この鍵と DB を無くすと
  保存済み認証情報は復号できなくなるため、`~/.n8n` はバックアップしておく。
- ネットに公開したい場合は、リバースプロキシ + Basic 認証/HTTPS/`N8N_SECURE_COOKIE=true`
  を別途構成すること(このローカル構成のままでは公開しない)。

## 次のステップ(n8n を活かす)

- **Slack/Gmail 連携**: 完了通知を terminal-notifier から Slack/Gmail ノードへ差し替え。
- **Web フックで即時起動**: Schedule Trigger に加えて Webhook トリガーを足せば
  手動・外部イベントからも同じレポートを起動できる。
- **段階的にネイティブ化**: まず要約ステップだけ n8n の AI ノードに置き換える等、
  リスクの低い部分から徐々に Python → n8n ノードへ移せる。
