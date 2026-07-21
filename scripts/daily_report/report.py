#!/usr/bin/env python3
"""毎朝の業界ニュースレポート生成 → Google Drive 保存。

マルチ AI 構成:
  Grok(リアルタイム検索)→ Ollama/grok-fast(統合サマリー)→ Perplexity(週次深掘り)

使い方:
  python3 report.py                 # 通常実行(生成 + Drive アップロード + 通知)
  python3 report.py --dry-run      # Drive アップロードと通知をスキップ
  python3 report.py --config path/to/config.yaml
"""

from __future__ import annotations

import argparse
import datetime
import logging
import pathlib
import shutil
import subprocess
import sys
import time

import yaml

from providers import Router, ProviderError

log = logging.getLogger("daily_report")


def load_config(path: pathlib.Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def run_rclone_copy(local_file: pathlib.Path, remote: str) -> None:
    """rclone copy を指数バックオフ付きで最大4回リトライ。"""
    delays = [2, 4, 8, 16]
    for attempt, delay in enumerate([0] + delays):
        if delay:
            time.sleep(delay)
        result = subprocess.run(
            ["rclone", "copy", str(local_file), remote, "--no-traverse"],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            log.info("Drive にアップロード完了: %s -> %s", local_file.name, remote)
            return
        log.warning("rclone 失敗 (attempt %d): %s", attempt + 1, result.stderr.strip())
    raise RuntimeError(f"rclone copy が {len(delays) + 1} 回失敗しました")


def notify(title: str, message: str) -> None:
    if shutil.which("terminal-notifier"):
        subprocess.run(
            ["terminal-notifier", "-title", title, "-message", message],
            capture_output=True,
        )


def build_report(config: dict, today: datetime.date) -> str:
    language = config.get("language", "日本語")
    limits = config.get("limits", {})
    topics = config.get("topics", [])[: limits.get("max_topics", 5)]
    router = Router(config.get("providers", {}))

    sections: list[str] = []
    failures: list[str] = []

    for topic in topics:
        log.info("トピック収集中: %s", topic["name"])
        try:
            body = router.news_report(
                topic, language,
                max_output_tokens=limits.get("max_output_tokens", 8000),
            )
            sections.append(f"## {topic['name']}\n\n{body}")
        except Exception as e:
            log.error("トピック '%s' の収集に失敗: %s", topic["name"], e)
            failures.append(f"- {topic['name']}: {e}")

    if not sections:
        raise ProviderError("全トピックの収集に失敗しました。API キーとネットワークを確認してください。")

    combined = "\n\n---\n\n".join(sections)

    log.info("エグゼクティブサマリー生成中")
    try:
        summary = router.summarize(combined, language)
    except Exception as e:
        log.error("サマリー生成に失敗(サマリーなしで続行): %s", e)
        summary = "(サマリー生成に失敗しました)"

    parts = [
        f"# 業界ニュースレポート {today.isoformat()}",
        f"## エグゼクティブサマリー\n\n{summary}",
        combined,
    ]

    dr_cfg = config.get("providers", {}).get("deep_research", {})
    if dr_cfg.get("enabled") and today.weekday() == dr_cfg.get("weekday", 0):
        log.info("週次深掘りレポート生成中(Perplexity)")
        try:
            deep = router.deep_research(dr_cfg.get("query", ""), language)
            parts.append(f"## 週次深掘りレポート\n\n{deep}")
        except Exception as e:
            log.error("深掘りレポートに失敗(スキップ): %s", e)
            failures.append(f"- 週次深掘り: {e}")

    if failures:
        parts.append("## ⚠️ 生成時のエラー\n\n" + "\n".join(failures))

    log.info(
        "本日の推定コスト: $%.4f (input=%d output=%d tokens)",
        router.total_cost, router.total_input_tokens, router.total_output_tokens,
    )
    parts.append(
        f"*生成: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')} / "
        f"news={config['providers'].get('news_model')} "
        f"summary=ollama:{config['providers'].get('local_model')} or "
        f"{config['providers'].get('fast_model')} / "
        f"推定コスト ${router.total_cost:.4f}*"
    )
    return "\n\n".join(parts) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", type=pathlib.Path,
        default=pathlib.Path(__file__).parent / "config.yaml",
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Drive アップロードと通知をスキップ")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )

    config = load_config(args.config)
    today = datetime.date.today()

    report_md = build_report(config, today)

    out_cfg = config.get("output", {})
    local_dir = pathlib.Path(out_cfg.get("local_dir", "~/Reports/daily")).expanduser()
    local_dir.mkdir(parents=True, exist_ok=True)
    local_file = local_dir / f"{today.isoformat()}-daily-report.md"
    local_file.write_text(report_md, encoding="utf-8")
    log.info("ローカル保存: %s", local_file)

    if args.dry_run:
        log.info("--dry-run のためアップロードと通知をスキップ")
        return 0

    remote = out_cfg.get("rclone_remote")
    if remote:
        run_rclone_copy(local_file, remote)

    if config.get("notify", True):
        notify("業界ニュースレポート", f"{today.isoformat()} のレポートが完成しました ✅")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        log.error("レポート生成に失敗: %s", e)
        notify("業界ニュースレポート ❌", str(e))
        sys.exit(1)
