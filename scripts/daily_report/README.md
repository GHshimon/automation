# 毎朝6時の業界ニュースレポート(マルチ AI 構成)

毎朝6時に業界ニュースレポートを自動生成し、Google Drive に保存する launchd ジョブ。

## マルチ AI ルーティング

| 処理 | 担当 AI | 理由 |
|---|---|---|
| ニュース収集 | **Grok** (`grok-4.5` + web_search/x_search) | X 込みのリアルタイム検索ができる唯一の選択肢 |
| 統合サマリー | **Ollama**(ローカル、あれば)→ なければ `grok-4.1-fast` | 軽い処理は無料・ローカルで。データ非流出 |
| 週次深掘り(任意) | **Perplexity** `sonar-deep-research` | 引用付き深掘りが最安($0.3〜1.3/本) |

処理フロー:

```
6:00 launchd → run.sh → report.py
  ├─ トピックごとに Grok がニュースセクションを執筆(検索付き)
  ├─ Ollama(または grok-fast)がエグゼクティブサマリーを生成
  ├─ 月曜のみ: Perplexity が週次深掘りを追加(enabled 時)
  ├─ ~/Reports/daily/YYYY-MM-DD-daily-report.md に保存
  ├─ rclone copy で gdrive:Reports/daily/ へアップロード(4回リトライ)
  └─ terminal-notifier で完了通知(失敗時は ❌ 通知)
```

## セットアップ(Mac 上で)

```bash
# 0. 前提ツール
brew install rclone terminal-notifier   # terminal-notifier は任意
rclone config    # → "gdrive" という名前で Google Drive リモートを作成

# 1. API キーをキーチェーンに登録(平文ファイルに置かない)
security add-generic-password -s xai-api-key -a "$USER" -w '<YOUR_XAI_API_KEY>'
# Perplexity を使う場合(任意):
security add-generic-password -s perplexity-api-key -a "$USER" -w '<YOUR_PPLX_KEY>'

# 2. トピックを自分の業界に合わせて編集
$EDITOR config.yaml

# 3. インストール(venv 作成 + launchd 登録 + 事前チェック)
./install.sh

# 4. まず手動テスト(Drive アップロードなし)
./run.sh --dry-run
cat ~/Reports/daily/$(date +%F)-daily-report.md
```

## 運用コマンド

```bash
launchctl kickstart gui/$(id -u)/com.user.daily-report   # 今すぐ本番実行
tail -f ~/Library/Logs/daily-report/daily-report.log      # ログ確認
launchctl bootout gui/$(id -u)/com.user.daily-report      # 停止(アンインストール)
```

## カスタマイズ

- **時刻変更**: `com.user.daily-report.plist.template` の `Hour`/`Minute` を編集して `./install.sh` を再実行
- **Mac がスリープ中だった場合**: launchd はスリープ中の実行をスキップします。「起床後に必ず実行」したい場合は plist の `RunAtLoad` を `true` に(ログイン時にも走る点に注意)。確実に6時に走らせたいなら `sudo pmset repeat wakeorpoweron MTWRFSU 05:55:00` で自動ウェイクを設定
- **ローカル要約を使う**: `ollama pull llama3.2` して Ollama を常駐させれば、サマリー生成が自動的にローカル処理に切り替わります(コード変更不要)
- **週次深掘り**: `config.yaml` の `deep_research.enabled: true` + Perplexity キー登録

## コスト目安

- Grok ニュース収集: トピック3個で1日あたり数円〜数十円(トークン + 検索 $5/1,000回)
- サマリー: Ollama 使用時は無料
- 週次深掘り(任意): 週1回 $0.3〜1.3
- 月額の目安: **数百円〜千円台**(深掘りなし・トピック3個の場合)

`config.yaml` の `limits` で上限を調整できます。
