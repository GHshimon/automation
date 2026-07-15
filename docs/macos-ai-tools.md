# macOS × AI 自動化ツールカタログ(2026年7月調査)

PC 作業の効率化のために、**AI(Claude などのエージェント)が呼び出せる・Python から扱える・CLI で完結する** ことを基準に、GitHub 上の macOS 向けツールを調査してまとめたカタログです。

**想定ユースケース**(このリポジトリ "automation" の前提として推測):

> AI をオーケストレーターとして、macOS 上のアプリ操作・ファイル処理・情報収集・要約などの一連の処理を自動化する。ストレージは Google Drive を活用する。

すべてのスター数・メンテナンス状況は **2026-07-15 時点で GitHub API により検証済み** です。

---

## 全体アーキテクチャ

```
┌──────────────────────────────────────────────┐
│  AI オーケストレーター                          │
│  (Claude Code / Claude Agent SDK / Python)    │
└──────┬───────────────┬───────────────┬───────┘
       │ MCP           │ CLI(subprocess)│ Python API
       ▼               ▼               ▼
┌────────────┐  ┌─────────────┐  ┌────────────┐
│ Mac 操作    │  │ ファイル/    │  │ ローカル LLM │
│ Peekaboo   │  │ メディア処理  │  │ Ollama     │
│ automator  │  │ rclone      │  │ whisper.cpp│
│ playwright │  │ pandoc など  │  │ llm CLI    │
└────────────┘  └──────┬──────┘  └────────────┘
                       ▼
                 Google Drive
```

---

## 1. AI から Mac を直接操作する(MCP サーバー)

Claude Desktop / Claude Code に設定するだけで、AI が Mac のアプリや画面を直接操作できるようになるツール群。**このカテゴリが「AI に処理させる」構想の中核** です。

### Peekaboo — AI の「目」と「手」 ★イチオシ
- https://github.com/openclaw/Peekaboo(約4.9k ★、非常に活発)
- ScreenCaptureKit による高速スクリーンショット + UI 要素検出 + クリック/入力/ドラッグ/メニュー操作。「OS 版 Playwright」と呼ばれる存在で、CLI・MCP・ネイティブアプリの3形態で使える。
- 導入: `brew install steipete/tap/peekaboo`、MCP は `npx -y @steipete/peekaboo`
- 必要権限: 画面収録 + アクセシビリティ

### macos-automator-mcp — AppleScript/JXA の万能エスケープハッチ
- https://github.com/steipete/macos-automator-mcp(約850 ★、活発)
- AI が任意の AppleScript / JXA を実行できる。200以上の自動化レシピの知識ベース付き。Finder・Mail・カレンダー等、スクリプタブルなアプリなら何でも操作可能。
- 導入: `npx -y --package @steipete/macos-automator-mcp macos-automator-mcp`

### playwright-mcp — ブラウザ操作の標準
- https://github.com/microsoft/playwright-mcp(約35.1k ★、Microsoft 公式)
- アクセシビリティスナップショット方式(視覚モデル不要でトークン効率が良い)でブラウザを操作。フォーム入力、タブ、ネットワーク検査まで。
- 導入: `npx @playwright/mcp@latest`

### google_workspace_mcp — Google Drive/Gmail/Docs を AI から
- https://github.com/taylorwilsdon/google_workspace_mcp(約2.8k ★、非常に活発)
- Gmail・Drive・Calendar・Docs・Sheets・Slides・Tasks など Google Workspace 全域をカバー。**公式の gdrive MCP は2025年5月にアーカイブ済み** のため、現在はこれが最有力。
- 導入: `uvx workspace-mcp --tool-tier core`(Google Cloud の OAuth クライアント設定が必要)

### Screenpipe — 24時間の画面・音声メモリ
- https://github.com/mediar-ai/screenpipe(約20k ★、非常に活発)
- 画面と音声をローカルに常時記録し、OCR・文字起こし・話者識別して自然言語で検索できる。「昨日見たあの資料どこ?」に AI が答えられるようになる。REST API(localhost:3030)+ MCP あり。
- 導入: `claude mcp add screenpipe -- npx -y screenpipe-mcp@latest`

### Filesystem MCP — ファイル操作の公式リファレンス
- https://github.com/modelcontextprotocol/servers の `src/filesystem`(モノレポ約88.5k ★)
- 許可したディレクトリ内に限定した安全なファイル読み書き・検索。
- 導入: `npx -y @modelcontextprotocol/server-filesystem /path/to/allowed`

### その他
| ツール | URL | 備考 |
|---|---|---|
| applescript-mcp | https://github.com/peakmojo/applescript-mcp | 軽量な AppleScript 実行サーバー(約460 ★) |
| macOS-use | https://github.com/browser-use/macOS-use | browser-use の Mac 全体版。Python エージェント(約2k ★、開発途上) |
| browser-use | https://github.com/browser-use/browser-use | Python でブラウザ AI エージェント(約105k ★) |
| safari-mcp | https://github.com/achiya-automation/safari-mcp | ネイティブ Safari を操作、実ログイン状態を継承。Apple 自身も Safari Technology Preview 247(2026年7月)で公式 Safari MCP を出荷開始 |

> ⚠️ **apple-mcp**(https://github.com/supermemoryai/apple-mcp、約3.1k ★)は Notes/Messages/Mail 操作の定番だったが **2026年1月にアーカイブ済み**。まだ動作するが、新規採用なら macos-automator-mcp で代替するのが安全。

---

## 2. OS レベルの自動化ツール(CLI/スクリプトから呼べる)

シェル経由で AI からも Python からも呼び出せる、Mac 本体の操作ツール。

### Hammerspoon — macOS 自動化の最強 OSS ★イチオシ
- https://github.com/Hammerspoon/hammerspoon(約15.7k ★、MIT、活発)
- ウィンドウ・アプリ・キーボード/マウスイベント・Wi-Fi・USB・通知・スクリーンなど macOS のシステム API を Lua で扱える常駐デーモン。
- `hs.ipc.cliInstall()` で `hs` CLI を入れると外部から呼び出せる:
  ```bash
  hs -c 'hs.window.focusedWindow():maximize()'
  ```

### 組み込みコマンド(インストール不要)
- **`shortcuts` CLI**(macOS 12+): ショートカット.app のワークフローをシェルから実行。`shortcuts run "画像リサイズ" -i in.png -o out.png`
- **`osascript`**: AppleScript / JXA の実行。あらゆるスクリプタブルアプリの操作、UI スクリプティング、ダイアログ表示。`osascript -e 'tell app "Safari" to make new document'`

### ウィンドウ管理
| ツール | URL | 特徴 |
|---|---|---|
| AeroSpace | https://github.com/nikitabobko/AeroSpace | i3 風タイル型 WM。**SIP 無効化不要**。`aerospace list-windows --all --json` で JSON が返るため AI 連携に最適(約21.8k ★) |
| yabai | https://github.com/koekeishiya/yabai | タイル型 WM の定番。`yabai -m query --windows` で JSON。一部機能に SIP 部分無効化が必要(約29.3k ★) |
| Rectangle | https://github.com/rxhanson/Rectangle | ウィンドウスナップ。`open -g "rectangle://execute-action?name=left-half"` の URL スキームで外部から操作可(約29.5k ★) |

### 入力・キーボード
| ツール | URL | 特徴 |
|---|---|---|
| cliclick | https://github.com/BlueM/cliclick | CLI からマウス/キーボードイベントを合成。`cliclick c:100,200 t:"hello" kp:return`。AI エージェントの「手」として最軽量(約2k ★) |
| Karabiner-Elements | https://github.com/pqrs-org/Karabiner-Elements | ドライバレベルのキーボードカスタマイズ。設定は JSON でスクリプトから書き換え可、キーからシェルコマンド実行も可(約22.5k ★) |
| espanso | https://github.com/espanso/espanso | Rust 製テキストエキスパンダー。YAML 定義、シェル出力の動的展開、`espanso match exec --trigger ":greet"` で外部起動可(約14.1k ★) |
| pyobjc | https://github.com/ronaldoussoren/pyobjc | Python から macOS 全フレームワークを直接叩く土台。`pip install pyobjc`(活発、canonical) |

### その他
- **terminal-notifier**(https://github.com/julienXX/terminal-notifier): スクリプトから macOS 通知を送る定番。2021年以降更新なしだが現役で動作。`brew install terminal-notifier`
- **Raycast**(https://github.com/raycast/script-commands): ランチャー本体はクローズドソースのフリーミアムだが、Script Commands(Bash/Python/Node のスクリプト)と拡張は OSS。`raycast://` ディープリンクで外部からコマンド起動可。
- **Maccy**(https://github.com/p0deje/Maccy): OSS クリップボード履歴。プログラム制御は弱いが定番スタック要素(約20.7k ★)。

> 有料だが強力: **Keyboard Maestro**(約$36、`osascript` からマクロ実行可)、**BetterTouchTool**(HTTP API 内蔵)。まずは無料 OSS で組むのが推奨。

---

## 3. ファイル・ドキュメント・メディア処理 CLI(Google Drive 連携)

「Drive のファイルを AI に処理させてまとめさせる」パイプラインの部品。すべて Python の `subprocess` から呼べます。

### rclone — Google Drive 連携の主役 ★イチオシ
- https://github.com/rclone/rclone(約58.3k ★、非常に活発)
- 「クラウドストレージ版 rsync」。Google Drive を含む70以上のバックエンドに対応し、OAuth・リトライ・レート制限・Google ドキュメントの形式変換(Docs→docx 等)まで自動処理。
  ```bash
  rclone config                                # 初回: "gdrive" リモートを対話設定
  rclone copy gdrive:Reports ~/work/reports    # ダウンロード
  rclone bisync gdrive:Notes ~/notes           # 双方向同期
  rclone mount gdrive: ~/GoogleDrive --vfs-cache-mode full &   # ローカルフォルダ化(要 macFUSE)
  rclone lsjson gdrive:Reports | jq '.'        # JSON で一覧 → AI が読める
  ```
- 注意: デフォルトの共有クライアント ID はスロットリングされるため、本格運用では自分の Google API client_id を作成する。

### ドキュメント → LLM 向けテキスト変換
| ツール | URL | 用途 |
|---|---|---|
| Docling (IBM) | https://github.com/docling-project/docling | PDF/DOCX/XLSX/PPTX → 構造化 Markdown/JSON。表・見出し・読み順を ML で保持。**「雑多な文書を LLM 用に整える」現在の定番**(約63.2k ★)。`pip install docling` |
| pandoc | https://github.com/jgm/pandoc | 約50形式の万能文書変換。`pandoc report.docx -t gfm -o report.md`。Python は pypandoc(約45.4k ★) |
| marker | https://github.com/datalab-to/marker | 学術系・複雑レイアウト PDF → Markdown の最高精度クラス。数式 LaTeX 対応(約37.5k ★、商用はライセンス要確認) |
| pdftotext (poppler) | https://gitlab.freedesktop.org/poppler/poppler | デジタル PDF の最速テキスト抽出。`brew install poppler` |
| OCRmyPDF | https://github.com/ocrmypdf/OCRmyPDF | スキャン PDF に検索可能なテキスト層を追加。`ocrmypdf -l eng+jpn in.pdf out.pdf`。**日本語 OCR 対応**(約34.2k ★) |
| tesseract | https://github.com/tesseract-ocr/tesseract | OCR エンジン本体。100+ 言語。Python は pytesseract(約75.4k ★) |

### メディア処理
| ツール | URL | 用途 |
|---|---|---|
| ffmpeg | https://github.com/FFmpeg/FFmpeg | 音声・動画の万能変換。文字起こし前処理: `ffmpeg -i meeting.mp4 -ar 16000 -ac 1 meeting.wav`(約62.1k ★) |
| whisper.cpp | https://github.com/ggml-org/whisper.cpp | ローカル文字起こし。Apple Silicon の Metal/Core ML 加速で Mac 最速。`brew install whisper-cpp`(約51.8k ★) |
| faster-whisper | https://github.com/SYSTRAN/faster-whisper | Python パイプラインなら whisper.cpp よりこちら。`pip install faster-whisper`(約24.3k ★) |
| yt-dlp | https://github.com/yt-dlp/yt-dlp | 約1,800サイトからの動画/音声/字幕取得。Python ライブラリとしても使える(約178.1k ★) |
| ImageMagick | https://github.com/ImageMagick/ImageMagick | 画像一括変換。`magick input.heic output.jpg`(約16.9k ★) |
| ExifTool | https://github.com/exiftool/exiftool | メタデータ読み書き。撮影日でリネーム、GPS 除去など。`-json` 出力で AI と好相性(約4.9k ★) |

### 検索・グルー(接着剤)
| ツール | URL | 用途 |
|---|---|---|
| ripgrep | https://github.com/BurntSushi/ripgrep | 超高速全文検索。`rg -i "請求書" ~/GoogleDrive --glob '*.md' --json`(約66.1k ★) |
| fd | https://github.com/sharkdp/fd | 高速ファイル検索 + 並列実行。`fd -e pdf --changed-within 7d . ~/GoogleDrive -x ocrmypdf {} {.}_ocr.pdf`(約43.7k ★) |
| jq | https://github.com/jqlang/jq | JSON 加工。rclone/exiftool/yt-dlp の出力整形に(約35.2k ★) |
| fzf | https://github.com/junegunn/fzf | あいまい検索。`--filter` で非対話でも使える(約81.7k ★) |
| monolith | https://github.com/Y2Z/monolith | Web ページを単一 HTML に保存 → Drive にアーカイブ(約15.3k ★) |

---

## 4. AI / LLM パイプラインツール

「AI が AI を呼ぶ」「ローカルで完結させる」ための部品。

### Ollama — ローカル LLM の標準
- https://github.com/ollama/ollama(約176.1k ★、非常に活発)
- ローカルモデルをワンコマンドで実行、`localhost:11434` の REST API + 公式 Python ライブラリ。API 課金なしで下ごしらえ(分類・要約の前処理)をローカルで回せる。
  ```bash
  cat notes.txt | ollama run llama3.2 "Summarize this:"
  ```

### llm (Simon Willison) — 最高のグルー CLI ★イチオシ
- https://github.com/simonw/llm(約12.2k ★、活発)
- CLI 兼 Python ライブラリ。stdin パイプ、JSON スキーマでの構造化抽出、埋め込み、全プロンプト/応答の SQLite 自動記録。プラグインで OpenAI/Anthropic/Gemini/Ollama すべてに対応。
  ```bash
  git diff | llm -s "コミットメッセージを書いて"
  ```

### fabric — プロンプトパターン集 CLI
- https://github.com/danielmiessler/Fabric(約43.1k ★、活発)
- summarize / extract_wisdom など約200のクラウドソース済みプロンプトパターンを Unix パイプで使える。`brew install fabric`
  ```bash
  cat notes.txt | fabric -p summarize
  ```

### Claude Agent SDK (Python) — エージェントのオーケストレーション
- https://github.com/anthropics/claude-agent-sdk-python(約7.6k ★、非常に活発)
- ファイル編集・bash・Web・MCP・サブエージェントを備えた Claude Code のエージェント基盤を Python から使う公式 SDK。ヘッドレスなら `claude -p "..."` だけでも可。
  ```python
  from claude_agent_sdk import query
  async for msg in query(prompt="utils.py をリファクタしてテストを実行して"):
      print(msg)
  ```

### その他
| ツール | URL | 備考 |
|---|---|---|
| MLX / mlx-lm | https://github.com/ml-explore/mlx-lm | Apple 公式。M 系チップでの最速ネイティブ推論。OpenAI 互換サーバー内蔵(約27.6k/6.3k ★) |
| LM Studio CLI (lms) | https://github.com/lmstudio-ai/lms | GUI + ヘッドレス制御の両立。`lms server start` で OpenAI 互換 API(CLI は MIT、約5.1k ★) |
| shell-gpt | https://github.com/TheR1D/shell_gpt | `sgpt --code` でコードのみ出力などスクリプト向き(約12.2k ★) |
| aichat | https://github.com/sigoden/aichat | オールインワン CLI。RAG・関数呼び出し内蔵(約10.2k ★、更新ペース低下中) |
| gptme | https://github.com/gptme/gptme | 軽量な OSS ターミナルエージェント。非対話モードあり(約4.4k ★、活発) |

### ⚠️ 2026年時点の要注意情報
- **mods**(charmbracelet)は 2026-03 にアーカイブ → 後継は `crush run`
- **Open Interpreter** は Rust で全面書き換え。旧 Python API(`interpreter.chat()`)はコミュニティフォークへ
- **aider** は 2025年半ばからメンテナンスモード

---

## おすすめスターターセット

まずこれだけ入れれば「AI が Mac を操作し、Drive のファイルを処理してまとめる」パイプラインが組めます。

```bash
# Homebrew で入るもの
brew install rclone pandoc ffmpeg ripgrep fd jq \
             whisper-cpp ocrmypdf imagemagick exiftool \
             terminal-notifier fabric ollama
brew install --cask hammerspoon

# pip で入るもの
pip install llm docling yt-dlp faster-whisper pyobjc claude-agent-sdk

# MCP(Claude Code に追加)
claude mcp add peekaboo -- npx -y @steipete/peekaboo
claude mcp add macos-automator -- npx -y --package @steipete/macos-automator-mcp macos-automator-mcp
claude mcp add playwright -- npx @playwright/mcp@latest
claude mcp add filesystem -- npx -y @modelcontextprotocol/server-filesystem ~/GoogleDrive

# Google Drive の初期設定
rclone config   # → "gdrive" という名前で Google Drive リモートを作成
```

### パイプライン例: Drive の今週の PDF を要約して Drive に書き戻す

```bash
rclone copy gdrive:Inbox ~/work/inbox --max-age 7d          # 1. 今週のファイルを取得
fd -e pdf . ~/work/inbox -x docling {} --to md --output ~/work/md/   # 2. Markdown 化
cat ~/work/md/*.md | llm -s "重要ポイントを日本語で箇条書きに" > ~/work/summary.md  # 3. AI 要約
rclone copy ~/work/summary.md gdrive:Processed/             # 4. Drive に書き戻し
terminal-notifier -title "自動化" -message "要約完了 ✅"      # 5. 通知
```

---

## macOS 権限(TCC)の早見表

AI に Mac を操作させるツールは、初回にシステム設定 → プライバシーとセキュリティでの許可が必要です。

| 権限 | 必要とするツール |
|---|---|
| アクセシビリティ | Peekaboo(操作)、cliclick、Hammerspoon、yabai、macOS-use |
| 画面収録 | Peekaboo(撮影)、Screenpipe |
| オートメーション(アプリごと) | osascript / AppleScript 系 MCP 全般 |
| フルディスクアクセス | メッセージ DB を読むツール(apple-mcp 系) |

---

*調査日: 2026-07-15。スター数は概数。各ツールの最新状況は GitHub リポジトリを確認してください。*
