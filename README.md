# automation

macOS 上で AI(Claude などのエージェント)を使った作業自動化のためのリポジトリ。

## ドキュメント

- [macOS × AI 自動化ツールカタログ](docs/macos-ai-tools.md) — AI から呼び出せる・Python から扱える macOS 向けツールの調査まとめ(MCP サーバー / OS 自動化 / ファイル・メディア処理 / LLM パイプライン、2026年7月調査)
- [AI 活用事例集](docs/ai-use-cases.md) — 外部 AI(Grok / OpenAI / Gemini / Perplexity)へのレポート作成委任、定期レポート・議事録・メール秘書・ファイル整理などの自動化レシピ、マルチ AI 使い分け戦略

## 実装済み自動化

- [ops-pulse 運用状態の収集](scripts/ops_pulse/) — 全プロジェクトと Mac の状態を AI なし・読み取り専用で集め、差分と異常をまとめる(運用ループ設計 [ops-loop-design.md](docs/ops-loop-design.md) の S1。launchd で毎日 06:30 と日曜 07:00 に実行)
- [毎朝6時の業界ニュースレポート](scripts/daily_report/) — マルチ AI 構成(Grok がニュース収集 → Ollama/grok-fast がサマリー → 週次で Perplexity 深掘り)で生成し、rclone で Google Drive に保存する launchd ジョブ。セットアップ手順は同ディレクトリの README を参照
