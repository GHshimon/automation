# ops-pulse — 運用ループ ① 収集 v0

`~/project` 配下の全プロジェクトとこのMacの状態を、**AIを使わず読み取り専用で**集める。設計は [ops-loop-design.md](../../docs/ops-loop-design.md)（§4.1、§8 S1）。Python 標準ライブラリのみ。

```bash
python3 pulse.py --print            # 毎日の収集
python3 pulse.py --weekly --print   # 週次の項目も集める
python3 -m unittest test_pulse      # テスト
```

## 集めるもの

| 頻度 | 項目 |
|---|---|
| 毎日 | git（ブランチ・未コミット数・上流との差分・最終コミット）、`.ai/decisions.jsonl` の件数と最終日、`_projectpilot` の段階・期限内の承認待ちと滞留日数・カードの状態、LaunchAgent（`com.shimon.` / `com.user.` / `com.cutsrt.`）の生死・終了コード・連続異常回数、ディスク空き |
| 週次 | `brew outdated`、Brewfile（`Mac環境/mac-setup/Brewfile`）との差分、主要ツールの版、自分の open PR（`gh search prs`）、Claude Code のトークン数（直近7日、プロジェクト別・モデル別。トランスクリプトをファイル単位で増分集計） |

週次でない日は、直近の週次結果を `weekly.collected_at` 付きで引き継ぐ。

## 出力（`data/`、Git 対象外）

- `snapshots/<日付>.json`, `latest.json` — state。`schema_version`、`collected_at`、`config_hash`、`collection_status`（complete / partial / error）、`failures`（節ごとの失敗理由）、`alerts`
- `diff.json` — 前回との差分。`quiet` が true になるのは、**今回と前回がともに complete、範囲が同じ、差分なし、異常なし**のときだけ。②の判断AIはこれが true なら起動しない
- `digest.md` — 人が読むまとめ。収集の失敗と異常が先頭

終了コード: 0 = complete、1 = partial、2 = error。

## 安全

- 書き込むのは `data/` だけ。収集対象には書かない。
- git は `core.fsmonitor` とフックを無効にして呼ぶ（収集対象のリポジトリの設定でコマンドが実行されないように）。
- 時間とともに必ず変わる値（滞留日数、ディスク空き）は差分に含めず、しきい値（`config.json` の `thresholds`）で異常として判定する。

## 定時実行（未登録）

`com.shimon.ops-pulse.plist.template` の `__DIR__` を置き換えて `~/Library/LaunchAgents/` に置き、`launchctl bootstrap gui/$(id -u) <plist>` で登録する。週次は同じものを `--weekly`・日曜で複製する。
