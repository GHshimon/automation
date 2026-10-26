"""ops-pulse の単体テスト。python3 -m unittest test_pulse（scripts/ops_pulse で実行）"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pulse

NOW = dt.datetime(2026, 10, 25, 12, 0, tzinfo=dt.timezone.utc)
LAUNCHCTL = "PID\tStatus\tLabel\n123\t0\tcom.shimon.web\n-\t143\tcom.shimon.dead\n-\t0\tcom.shimon.daily\n456\t0\tcom.apple.other\n"


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj), encoding="utf-8")


class Fixture(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "project"
        self.agents = self.tmp / "LaunchAgents"
        self.agents.mkdir(parents=True)
        (self.agents / "com.shimon.unloaded.plist").write_text("")
        # git リポジトリ（未コミット1件）
        repo = self.root / "alpha"
        repo.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
        (repo / "a.txt").write_text("a")
        subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@e", "add", "."], check=True)
        subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@e", "commit", "-qm", "init"], check=True)
        (repo / "b.txt").write_text("b")
        (repo / ".ai").mkdir()
        (repo / ".ai" / "decisions.jsonl").write_text(
            '{"id":"d0001","ts":"2026-10-20T00:00:00Z"}\n{"id":"d0002","ts":"2026-10-24T00:00:00Z"}\n')
        # ProjectPilot（期限内の承認待ち1件・期限切れ1件・カード2件）
        pp = self.root / "beta" / "_projectpilot"
        write_json(pp / "state" / "current.json", {"currentStageId": "S2", "revision": 3, "updatedAt": "2026-10-20T00:00:00Z"})
        write_json(pp / "transitions" / "t1.json", {"status": "pending", "createdAt": "2026-10-20T12:00:00Z", "expiresAt": "2026-11-01T00:00:00Z"})
        write_json(pp / "transitions" / "t2.json", {"status": "pending", "createdAt": "2026-10-01T00:00:00Z", "expiresAt": "2026-10-02T00:00:00Z"})
        write_json(pp / "cards" / "c1.json", {"status": "inbox", "createdAt": "2026-10-23T12:00:00Z"})
        write_json(pp / "cards" / "c2.json", {"status": "done", "createdAt": "2026-10-01T00:00:00Z"})
        (self.root / "plain").mkdir()
        self.cfg = {
            "root": str(self.root), "data_dir": str(self.tmp / "data"), "launch_agents_dir": str(self.agents),
            "launchd_prefixes": ["com.shimon."], "disk_path": "/", "brewfile": str(self.tmp / "none"),
            "claude_projects_dir": str(self.tmp / "claude"), "versions": {},
            "thresholds": {"disk_free_pct": 0, "disk_free_gb": 0, "pending_approval_days": 3, "unpushed_days": 3},
        }

    def collect(self, previous=None, launchctl=LAUNCHCTL):
        real_run = pulse.run

        def fake_run(cmd, timeout=20, cwd=None):
            return launchctl if cmd[:2] == ["launchctl", "list"] else real_run(cmd, timeout, cwd)

        with mock.patch.object(pulse, "run", side_effect=fake_run), mock.patch.object(pulse, "now_utc", return_value=NOW):
            return pulse.collect(self.cfg, "hash1", weekly=False, previous=previous)


class CollectTest(Fixture):
    def test_projects(self):
        snap = self.collect()
        self.assertEqual(snap["collection_status"], "complete", snap["failures"])
        alpha = snap["projects"]["alpha"]
        self.assertEqual(alpha["git"]["branch"], "main")
        self.assertEqual(alpha["git"]["dirty"], 2)  # b.txt と .ai/
        self.assertFalse(alpha["git"]["has_upstream"])
        self.assertEqual(alpha["decisions"], {"count": 2, "last": "2026-10-24T00:00:00Z"})
        beta = snap["projects"]["beta"]["projectpilot"]
        self.assertEqual(beta["pending_transitions"], 1)  # 期限切れは数えない
        self.assertEqual(beta["oldest_pending_days"], 5.0)
        self.assertEqual(beta["cards"], {"done": 1, "inbox": 1})
        self.assertEqual(beta["oldest_open_card_days"], 2.0)
        self.assertEqual(snap["projects"]["plain"], {"path": str(self.root / "plain")})

    def test_launchd_health_and_alerts_first(self):
        snap = self.collect()
        svc = snap["mac"]["launchd"]
        self.assertTrue(svc["com.shimon.web"]["healthy"])
        self.assertTrue(svc["com.shimon.daily"]["healthy"])  # 定時ジョブは pid なし・終了0 で正常
        self.assertFalse(svc["com.shimon.dead"]["healthy"])
        self.assertFalse(svc["com.shimon.unloaded"]["loaded"])
        self.assertNotIn("com.apple.other", svc)
        self.assertEqual(snap["alerts"][0]["level"], "error")
        subjects = {a["subject"] for a in snap["alerts"]}
        self.assertTrue({"com.shimon.dead", "com.shimon.unloaded", "beta"} <= subjects)

    def test_unhealthy_streak_counts_up(self):
        first = self.collect()
        second = self.collect(previous=first)
        self.assertEqual(second["mac"]["launchd"]["com.shimon.dead"]["unhealthy_streak"], 2)

    def test_partial_when_a_section_fails(self):
        snap = self.collect(launchctl=None)  # launchctl の出力が壊れている
        self.assertEqual(snap["collection_status"], "partial")
        self.assertEqual(snap["failures"][0]["section"], "launchd")
        self.assertEqual(snap["alerts"][0]["kind"], "collection")

    def test_repo_hooks_are_not_executed(self):
        repo = self.root / "alpha"
        marker = self.tmp / "pwned"
        subprocess.run(["git", "-C", str(repo), "config", "core.fsmonitor", f"touch {marker}; false"], check=True)
        self.collect()
        self.assertFalse(marker.exists())


class DiffTest(Fixture):
    def test_first_run_is_not_quiet(self):
        snap = self.collect()
        self.assertFalse(pulse.compute_diff(snap, None)["quiet"])

    def test_quiet_only_when_complete_same_scope_no_changes_no_alerts(self):
        self.cfg["launchd_prefixes"] = ["com.none."]
        (self.root / "beta" / "_projectpilot" / "transitions" / "t1.json").unlink()
        a = self.collect()
        b = self.collect(previous=a)
        self.assertEqual(b["alerts"], [])
        self.assertTrue(pulse.compute_diff(b, a)["quiet"])

        (self.root / "alpha" / "c.txt").write_text("c")
        c = self.collect(previous=b)
        d = pulse.compute_diff(c, b)
        self.assertFalse(d["quiet"])
        self.assertIn("projects.alpha.git.dirty", [x["key"] for x in d["changes"]])

    def test_partial_is_never_quiet(self):
        self.cfg["launchd_prefixes"] = ["com.none."]
        (self.root / "beta" / "_projectpilot" / "transitions" / "t1.json").unlink()
        a = self.collect()
        b = self.collect(previous=a, launchctl=None)
        d = pulse.compute_diff(b, a)
        self.assertFalse(d["quiet"])
        self.assertEqual(d["reason"], "収集が不完全")

    def test_scope_shrink_alerts(self):
        a = self.collect()
        (self.root / "plain").rmdir()
        b = self.collect(previous=a)
        self.assertIn("scope", [x["kind"] for x in b["alerts"]])
        self.assertFalse(pulse.compute_diff(b, a)["same_scope"])


class TokenTest(unittest.TestCase):
    def test_dedupes_streamed_message_ids(self):
        tmp = Path(tempfile.mkdtemp())
        f = tmp / "claude" / "-Users-x-project-foo" / "s.jsonl"
        f.parent.mkdir(parents=True)
        line = lambda out: json.dumps({"timestamp": "2026-10-25T01:00:00Z", "cwd": "/Users/x/project/foo/sub",
                                       "message": {"id": "m1", "model": "m", "usage": {"input_tokens": 10, "output_tokens": out}}})
        f.write_text(line(1) + "\n" + line(5) + "\n")
        r = pulse.collect_token_usage(tmp / "claude", tmp / "cache.json", dt.datetime.now(dt.timezone.utc))
        self.assertEqual(r["total_tokens"], 15)
        self.assertEqual(r["by_project_top"], {"foo": 15})
        again = pulse.collect_token_usage(tmp / "claude", tmp / "cache.json", dt.datetime.now(dt.timezone.utc))
        self.assertEqual(again["total_tokens"], 15)  # キャッシュ経由でも同じ


class DigestTest(Fixture):
    def test_alerts_section_comes_before_projects(self):
        snap = self.collect()
        md = pulse.render_digest(snap, pulse.compute_diff(snap, None))
        self.assertLess(md.index("## 異常・要確認"), md.index("## プロジェクト"))
        self.assertIn("com.shimon.dead", md)
        self.assertIn("plain", md)


if __name__ == "__main__":
    unittest.main()
