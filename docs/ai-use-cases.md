# AI 活用事例集 — レポート委任と自動化レシピ(2026年7月調査)

[ツールカタログ](macos-ai-tools.md) のツール群を組み合わせた実践的な活用事例集。特に「**外部 AI(Grok など)に代わりにレポートを作成させる**」パターンを中心に、視野を広げた自動化レシピをまとめます。

API 仕様・モデル名・価格は **2026-07-15 時点で公式ドキュメントから検証済み** です(価格は概算、変動あり)。

---

## 1. 外部 AI にレポート作成を委任する

「調べて、まとめて、レポートにして」を丸ごと外部 AI に投げ、完成品だけ受け取るパターン。オーケストレーター(Claude Code / Python スクリプト)から API 経由で依頼し、返ってきたレポートを Google Drive に保存します。

### 使い分け早見表

| 目的 | 最適な選択(2026年7月) | 1レポートあたり概算 |
|---|---|---|
| X(Twitter)のリアルタイム動向込みのレポート | **Grok**(api.x.ai + x_search ツール) | トークン代 + 検索 $5/1000回 |
| ターンキーで最高品質の引用付きレポート | OpenAI `o3-deep-research` | $1.5〜8 |
| ターンキーでコスパ重視 | Gemini `deep-research-preview-04-2026` | $1〜3 |
| 最安の引用付きリサーチ | Perplexity `sonar-deep-research` | $0.3〜1.3 |
| ローカルファイルも読ませたい・制御重視 | Claude Agent SDK / Messages API + web search | 従量 |
| セルフホスト・プロバイダ非依存 | gpt-researcher(OSS) | モデル次第 |

### 1-1. Grok にレポートを書かせる

xAI API は OpenAI SDK 互換(`https://api.x.ai/v1`)。**X 投稿へのリアルタイムグラウンディング**が他社にない強みで、`web_search` / `x_search` のサーバーサイドツールを付けると Grok が自分で検索しながら書きます。

- 現行モデル: `grok-4.3`(旗艦、100万トークンコンテキスト)、`grok-4.5`、`grok-4.1-fast`(格安)。**grok-5 は存在しない**
- ツール課金: Web/X 検索 各 $5/1,000回(トークン代と別)

```python
import os
from openai import OpenAI

client = OpenAI(api_key=os.environ["XAI_API_KEY"], base_url="https://api.x.ai/v1")

response = client.responses.create(
    model="grok-4.5",
    input=[{"role": "user", "content": """
以下のテーマで日本語レポートを作成してください。
テーマ: 生成AI関連の今週の主要ニュースと X 上の反応
構成: 1) エグゼクティブサマリー 2) トピック別詳細 3) 注目の議論 4) 出典一覧
"""}],
    tools=[{"type": "web_search"}, {"type": "x_search"}],
)
open("report.md", "w").write(response.output_text)
```

これを rclone と組み合わせれば「**Grok がレポートを書いて Drive に置いておいてくれる**」が完成:

```bash
python grok_report.py && rclone copy report.md gdrive:Reports/$(date +%Y-%m-%d)/
```

> 注意: Grok には専用の「ディープリサーチモード」はありません。レポートの構成はプロンプト側で指定します(上の例のように章立てを明示するのがコツ)。

### 1-2. OpenAI Deep Research — 本物の「丸投げ」

`o3-deep-research` / `o4-mini-deep-research` は、自律的に数十回の Web 検索を行い、引用付きの長文レポートを返す専用モデル。実行に数十分かかるため `background=True` で投げて後で回収します。

```python
from openai import OpenAI
client = OpenAI(timeout=3600)

resp = client.responses.create(
    model="o4-mini-deep-research",   # コスパ版。最高品質は o3-deep-research
    input="2026年の全固体電池の市場動向について、引用付きの日本語レポートを作成",
    background=True,
    tools=[{"type": "web_search_preview"}],
)
# あとで client.responses.retrieve(resp.id) でポーリング → response.output_text
```

- 価格: o3 版 $10/$40 per M tokens(実質 $1.5〜8/本)、o4-mini 版 $2/$8(実質 $0.4〜2.5/本)
- 極端なクエリで $30 に達した実測報告もあるため、定期実行するなら予算キャップ推奨

### 1-3. Gemini Deep Research API(2026年4月に公開)

Gemini アプリの Deep Research が API から使えるようになりました。Gemini 3.1 Pro ベース、Interactions API 経由・バックグラウンド実行必須。

```python
import time
from google import genai

client = genai.Client()  # GEMINI_API_KEY

interaction = client.interactions.create(
    input="国内の電子帳簿保存法対応 SaaS の比較レポートを作成",
    agent="deep-research-preview-04-2026",   # Max 版: deep-research-max-preview-04-2026
    background=True,
)
while True:
    interaction = client.interactions.get(interaction.id)
    if interaction.status == "completed":
        report = interaction.steps[-1].content[0].text
        break
    time.sleep(10)
```

- 約80回検索(Max 版は約160回)、$1〜3/本。プレビュー段階なのでエージェント名は変わる可能性あり
- 公式ドキュメント自身が「Web + 私有ファイル両方を読ませる場合のプロンプトインジェクション」に警告あり

### 1-4. Perplexity — 最安の引用付きリサーチ

OpenAI 互換エンドポイント(`https://api.perplexity.ai`)。`sonar-deep-research` は複数検索を回して [1][2] 形式の引用付きレポートを返します。1本 $0.3〜1.3 程度と最安クラス。

```python
from openai import OpenAI
client = OpenAI(api_key=PPLX_KEY, base_url="https://api.perplexity.ai", timeout=1800)

resp = client.chat.completions.create(
    model="sonar-deep-research",
    messages=[{"role": "user", "content": "EU AI Act の2026年の執行状況レポート"}],
)
print(resp.choices[0].message.content)
```

### 1-5. Claude — 制御重視・ローカルファイル込みのパイプライン

- **Messages API + web search ツール**(検索 $10/1,000回、引用付き): 検索回数 `max_uses` で深さを自分で制御
- **Claude Agent SDK**: `query("Xを調査して report.md に書いて")` でファイル操作込みのエージェントループをローカル実行。「Drive の手元資料 + Web 検索」を混ぜたレポートに最適

### 1-6. OSS でセルフホスト: gpt-researcher

https://github.com/assafelovic/gpt-researcher — 自律的にプラン→検索→執筆する定番 OSS。任意の LLM(Ollama のローカルモデル含む)で動かせるため、**API 課金ゼロの深掘りリサーチ**も可能。LangChain 版 [open_deep_research](https://github.com/langchain-ai/open_deep_research) も選択肢。

```python
from gpt_researcher import GPTResearcher
researcher = GPTResearcher(query="量子コンピュータ業界の2026年動向", report_type="research_report")
await researcher.conduct_research()
report = await researcher.write_report()
```

> **NotebookLM について**: 一般向け API は未提供(2026年7月時点)。Google Cloud のエンタープライズ版 API(アルファ)のみ。非公式クライアントは規約グレーなので非推奨。

---

## 2. 定期レポートの完全自動化(スケジューリング)

上のどれかを **macOS の定期実行に載せる** と「毎朝レポートが Drive に届いている」状態になります。

### レシピ A: 毎朝の業界ニュースダイジェスト

```
launchd (毎朝6時)
  → Python: Grok (x_search) で「昨日の業界動向」レポート生成
  → rclone copy で gdrive:Reports/daily/ に保存
  → terminal-notifier で「今朝のレポート準備完了」通知
  → (オプション) Slack MCP でチームチャンネルに要約投稿
```

macOS でのスケジューリング手段:
- **launchd**(標準・堅牢): `~/Library/LaunchAgents/com.user.dailyreport.plist` に定義
- **Shortcuts.app のオートメーション**: 時刻・Wi-Fi 接続・充電開始などをトリガーに `shortcuts run` 相当を GUI で設定
- **Hammerspoon**: `hs.timer.doAt("06:00", ...)` で Lua から。条件分岐が柔軟

### レシピ B: 週次の競合モニタリングレポート

```
launchd (毎週月曜)
  → Perplexity sonar-deep-research で競合3社の週次動向を各社1本($1未満/週)
  → llm CLI でローカル統合: cat reports/*.md | llm -s "3社を比較する統合サマリーを冒頭に追加"
  → pandoc で docx 化(上司向け)+ rclone で Drive 共有フォルダへ
```

### レシピ C: 「調べておいて」を音声で投げる

```
ショートカット.app「リサーチ依頼」(Siri から起動可)
  → 音声入力をテキスト化
  → shortcuts → シェル → OpenAI Deep Research に background=True で投入
  → ジョブ ID を保存、完了ポーリングは launchd の10分おきジョブが担当
  → 完成したら Drive 保存 + 通知
```

---

## 3. 会議・音声・動画の知識化パイプライン

### レシピ D: 会議録音 → 議事録 → 共有(全ローカル処理も可)

```bash
# 1. 録音ファイル(Drive の Recordings フォルダを監視)
rclone copy gdrive:Recordings ~/work/rec --max-age 1d
# 2. 前処理 + ローカル文字起こし(API 課金ゼロ)
ffmpeg -i meeting.m4a -ar 16000 -ac 1 tmp.wav
whisper-cli -m ggml-large-v3.bin -f tmp.wav -l ja -otxt
# 3. 議事録化(ローカル LLM なら完全オフライン)
cat tmp.txt | llm -s "決定事項・TODO・担当者を抽出して議事録形式に" > minutes.md
# 4. 書き戻し + Notion 保存(Notion MCP 経由なら Claude に頼むだけ)
rclone copy minutes.md gdrive:Minutes/
```

機密度の高い会議はステップ3を `ollama run` に差し替えれば**音声データが一切外に出ない**構成にできます。

### レシピ E: YouTube/ポッドキャスト → 知見データベース

```bash
yt-dlp -x --audio-format mp3 "$URL" -o talk.mp3      # または --write-auto-subs で字幕だけ取得
whisper-cli -m ggml-base.bin -f talk.wav -otxt
cat talk.txt | fabric -p extract_wisdom > wisdom.md   # fabric の定番パターン
rclone copy wisdom.md gdrive:Knowledge/
```

これを「後で見る」プレイリストに対して launchd で毎晩回すと、**寝ている間に動画が知見メモに変換されて Drive に溜まっていく**。

---

## 4. メール・コミュニケーションの自動化

### レシピ F: 朝のメール秘書

Claude Code(+ Gmail MCP)に定期タスクとして依頼:

```
毎朝7時: 「未読メールを重要度で分類し、要返信のものは返信ドラフトを作成、
全体サマリーを1通のメモにまとめて Drive の Inbox/ に置いて」
```

ポイントは **送信はさせずドラフト止まり** にすること。人間は朝ドラフトを確認して送信ボタンを押すだけになります。

### レシピ G: Slack の「見てない間のまとめ」

Slack MCP + Claude で「昨日以降の重要チャンネルの議論を要約、自分宛メンションと決定事項を先頭に」→ 毎朝 Drive or DM に。長期の休暇明けに特に効きます。

---

## 5. Mac 操作・ファイル整理の自動化

### レシピ H: Drive の「受信箱」フォルダを AI が自動整理

```
launchd (1時間おき)
  → rclone lsjson gdrive:Inbox で新着確認
  → 各ファイル: docling で内容を Markdown 化 → llm で「書類種別・日付・取引先」を JSON 抽出
  → 判定結果に従い rclone moveto で gdrive:Documents/2026/請求書/ 等へ振り分け+リネーム
```

### レシピ I: レシート・領収書の経費処理

```bash
fd -e jpg -e png . ~/GoogleDrive/Receipts --changed-within 30d \
  -x sh -c 'tesseract "$1" - -l jpn | llm -s "日付・金額・店名を CSV 1行で" >> expenses.csv' _ {}
```

OCR 精度が足りない場合は tesseract を「画像ごと Claude/Gemini の vision に渡す」に差し替え。

### レシピ J: 画面操作の代行(GUI しかないアプリの自動化)

API のない社内システムや古いアプリは Peekaboo + Claude で:

```
「経費精算アプリを開いて、expenses.csv の内容を1行ずつ入力フォームに転記して。
 各行の登録後にスクリーンショットで確認して」
```

Peekaboo が画面を見ながらクリック・入力し、macos-automator-mcp が AppleScript でアプリ起動やメニュー操作を担当。**「人間がやるには退屈すぎる転記作業」の最終兵器**です。

### レシピ K: 操作マニュアルの自動生成

Screenpipe を常時起動しておくと画面履歴が全部ローカル DB に入るので、「さっき私がやった経費申請の手順を、スクリーンショット付き手順書にまとめて」が可能になります。

---

## 6. マルチ AI 戦略 — 適材適所で「AI が AI を呼ぶ」

単一 AI に全部やらせるより、**Claude Code をオーケストレーターにして各 AI を工具のように使い分ける** のが2026年時点の最適解です。

```
Claude Code(司令塔: 計画・ツール実行・品質チェック・Drive 保存)
 ├── Grok        … X のリアルタイム動向、速報系レポート
 ├── OpenAI/Gemini Deep Research … 時間をかけた深掘りレポート(投げて忘れる)
 ├── Perplexity  … 安価な引用付きファクト確認
 └── Ollama(ローカル)… 分類・タグ付け・下書きなど大量の前処理(課金ゼロ・データ非流出)
```

実装は2通り:

1. **llm CLI + プラグイン**(llm-grok / llm-gemini / llm-perplexity): シェルパイプで手軽に。ただしディープリサーチ系のバックグラウンド API は非対応なので、その部分は各社 SDK を直接叩く
2. **LiteLLM**: 100+ プロバイダを OpenAI 形式に統一 + コスト追跡。複数 AI を本格運用するならこちら

コスト管理の実践則:
- 大量・低難度(分類、タグ付け、1次要約)→ ローカル(Ollama/MLX)か `grok-4.1-fast`・Haiku 級
- 少量・高難度(統合レポート、意思決定資料)→ Deep Research 系や旗艦モデル
- 全呼び出しを `llm` の SQLite ログや LiteLLM のコスト追跡で可視化しておく

---

## セキュリティと運用の注意

- **API キー管理**: macOS キーチェーンに保存し `security find-generic-password -w -s xai-api-key` で取得。平文の `.env` を Drive に同期しないこと
- **プロンプトインジェクション**: Web を読む AI に私有ファイルへのアクセスも与える構成(Gemini Deep Research + MCP 等)は、悪意ある Web ページ経由の情報流出リスクがある(Google 公式も警告)。読み取り範囲は最小限に
- **送信系は必ずドラフト止まり**: メール送信・Slack 投稿・SNS 投稿は人間の承認を挟む
- **定期ジョブには予算キャップ**: Deep Research 系は1本数ドル。暴走防止に月次上限とアラートを設定
- **機密データはローカル LLM へ**: Ollama / MLX / whisper.cpp で処理すれば外部送信ゼロ

---

*調査日: 2026-07-15。API 仕様・価格は各社公式ドキュメントで最新を確認してください。*
