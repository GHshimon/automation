# 毎朝6時の業界ニュースレポート(マルチ AI 構成)

毎朝6時に業界ニュースレポートを自動生成し、Google Drive に保存する launchd ジョブ。

## マルチ AI ルーティング

| 処理 | 担当 AI | 理由 |
|---|---|---|
| ニュース収集 | **Grok** (`grok-4.20-0309-non-reasoning` + web_search/x_search) | X 込みのリアルタイム検索が可能。非推論モデルで推論トークンが出ずコストが低い(grok-4.5 比 約-70%) |
| 統合サマリー | **Ollama**(ローカル、あれば)→ なければ `grok-4.20-0309-non-reasoning` | 軽い処理は無料・ローカルで。データ非流出 |
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

## コスト目安と可視化

実測値(非推論モデル・1トピック集約・`max_output_tokens: 3000`):

- 1回あたり **約 $0.036**(収集 $0.033 + サマリー $0.003)。月額 **約 $1** 程度。
- 内訳の主因は**検索が注入する入力トークン**(1収集あたり 2〜7万トークン)。Live Search
  手数料($5/1,000回=1回$0.005)は誤差レベル。
- **実コストは毎回ログに出ます**: `コスト[model] input=… output=… 概算=$…`、および
  レポート末尾のフッターに「推定コスト $…」。`tail -f ~/Library/Logs/daily-report/daily-report.log`
  や n8n の実行履歴で確認可能。

コストを更に下げるレバー(いずれも `config.yaml`):

- `providers.news_model`: 非推論モデル(`grok-4.20-0309-non-reasoning`)が最安。`grok-4.5`
  は推論トークンで数倍高くなる。
- `topics`: 1トピック = 検索付き1回の API 呼び出し。分野を増やすと線形にコスト増。
- `limits.max_output_tokens`: 出力上限。小さいほど安い。
- 実行頻度: plist の `StartCalendarInterval` を平日のみ等にすれば実行回数を削減。
- サマリーは `ollama pull llama3.2` で Ollama 常駐にすれば**無料**(自動でローカルに切替)。
- 週次深掘り(任意): 週1回 $0.3〜1.3(`deep_research.enabled: true` 時のみ)。
