#!/usr/bin/env python3
"""運用ループ ① 収集 ops-pulse v0。AIを使わず、読み取り専用で状態を集める。

設計: automation/docs/ops-loop-design.md（§4.1 state 形式、§8 S1）

使い方:
  python3 pulse.py              # 毎日の収集（git / decisions / ProjectPilot / launchd / ディスク）
  python3 pulse.py --weekly     # 週次の収集も行う（brew / Brewfile / ツールの版 / open PR / トークン集計）
  python3 pulse.py --print      # 結果のダイジェストを標準出力にも出す

出力（data/ 以下、Git 対象外）:
  snapshots/<date>.json  その日の state
  latest.json            最新の state（週次の結果は直近のものを引き継ぐ）
  diff.json              前回との差分と quiet 判定
  digest.md              人が読むまとめ（異常が先頭）

終了コード: 0 = complete, 1 = partial, 2 = error
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path

SCHEMA_VERSION = 1
HERE = Path(__file__).resolve().parent
DEFAULT_CONFIG = HERE / "config.json"
# 収集対象のリポジトリに置かれた設定（fsmonitor・フック）を実行させない
GIT_SAFE = ["git", "-c", "core.fsmonitor=", "-c", "core.hooksPath=/dev/null"]


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso(t: dt.datetime) -> str:
    return t.astimezone(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_ts(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def age_days(value: str | None, now: dt.datetime) -> float | None:
    t = parse_ts(value)
    return None if t is None else round((now - t).total_seconds() / 86400, 1)


def tool_env() -> dict:
    """launchd はシェルのプロファイルを読まないため、Homebrew と ~/.local/bin を PATH に足す。"""
    extra = ["/opt/homebrew/bin", "/usr/local/bin", str(Path.home() / ".local" / "bin")]
    return dict(os.environ, PATH=":".join(extra + [os.environ.get("PATH", "/usr/bin:/bin")]),
                GIT_TERMINAL_PROMPT="0", HOMEBREW_NO_AUTO_UPDATE="1")


def run(cmd: list[str], timeout: int = 20, cwd: Path | None = None) -> str:
    """コマンドを実行して stdout を返す。失敗時は RuntimeError（呼び出し側で失敗理由として記録）。"""
    env = tool_env()
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd, env=env)
    except FileNotFoundError as e:
        raise RuntimeError(f"not found: {cmd[0]}") from e
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"timeout {timeout}s: {' '.join(cmd[:3])}") from e
    if p.returncode != 0:
        raise RuntimeError(f"exit {p.returncode}: {' '.join(cmd[:4])}: {p.stderr.strip()[:200]}")
    return p.stdout


class Collector:
    """節ごとの失敗を集め、全体の collection_status を決める。"""

    def __init__(self) -> None:
        self.failures: list[dict] = []
        self.attempted = 0

    def guard(self, section: str, fn, *args, default=None):
        self.attempted += 1
        try:
            return fn(*args)
        except Exception as e:  # noqa: BLE001 — 収集は止めず、失敗理由を残す
            self.failures.append({"section": section, "error": f"{type(e).__name__}: {e}"[:300]})
            return default

    def status(self) -> str:
        if not self.failures:
            return "complete"
        return "error" if len(self.failures) >= self.attempted else "partial"


# ---------------------------------------------------------------- projects

def git_info(repo: Path) -> dict:
    g = GIT_SAFE + ["-C", str(repo)]
    branch = subprocess.run(g + ["symbolic-ref", "--short", "-q", "HEAD"],
                            capture_output=True, text=True, timeout=10).stdout.strip() or "(detached)"
    porcelain = run(g + ["status", "--porcelain=v1", "--untracked-files=normal"], timeout=30)
    last = run(g + ["log", "-1", "--format=%cI"]).strip() if run(g + ["rev-list", "-n1", "--all"]).strip() else None
    ahead = behind = None
    lr = subprocess.run(g + ["rev-list", "--left-right", "--count", "@{u}...HEAD"],
                        capture_output=True, text=True, timeout=10)
    if lr.returncode == 0 and lr.stdout.split():
        behind, ahead = (int(x) for x in lr.stdout.split())
    remote = subprocess.run(g + ["remote"], capture_output=True, text=True, timeout=10).stdout.split()
    return {
        "branch": branch,
        "dirty": len([ln for ln in porcelain.splitlines() if ln.strip()]),
        "ahead": ahead,
        "behind": behind,
        "has_upstream": ahead is not None,
        "has_remote": bool(remote),
        "last_commit": iso(parse_ts(last)) if last else None,
    }


def decisions_info(path: Path) -> dict:
    count, last = 0, None
    with path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            count += 1
            try:
                last = json.loads(line).get("ts") or last
            except json.JSONDecodeError:
                pass
    return {"count": count, "last": last}


def projectpilot_info(pp: Path, now: dt.datetime) -> dict:
    state = json.loads((pp / "state" / "current.json").read_text(encoding="utf-8"))
    pending, oldest = 0, None
    for f in sorted((pp / "transitions").glob("*.json")) if (pp / "transitions").is_dir() else []:
        t = json.loads(f.read_text(encoding="utf-8"))
        exp = parse_ts(t.get("expiresAt"))
        if t.get("status") == "pending" and (exp is None or exp > now):
            pending += 1
            oldest = max(oldest or 0, age_days(t.get("createdAt"), now) or 0)
    cards: dict[str, int] = defaultdict(int)
    oldest_open = None
    for f in (pp / "cards").glob("*.json") if (pp / "cards").is_dir() else []:
        c = json.loads(f.read_text(encoding="utf-8"))
        cards[c.get("status", "unknown")] += 1
        if c.get("status") not in ("done", "archived", "cancelled"):
            oldest_open = max(oldest_open or 0, age_days(c.get("createdAt"), now) or 0)
    return {
        "stage": state.get("currentStageId"),
        "revision": state.get("revision"),
        "updated": state.get("updatedAt"),
        "pending_transitions": pending,
        "oldest_pending_days": oldest,
        "cards": dict(sorted(cards.items())),
        "oldest_open_card_days": oldest_open,
    }


def collect_projects(root: Path, col: Collector, now: dt.datetime) -> dict:
    projects = {}
    for d in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")):
        name = d.name
        entry: dict = {"path": str(d)}
        if (d / ".git").exists():
            entry["git"] = col.guard(f"git:{name}", git_info, d)
        if (d / ".ai" / "decisions.jsonl").is_file():
            entry["decisions"] = col.guard(f"decisions:{name}", decisions_info, d / ".ai" / "decisions.jsonl")
        if (d / "_projectpilot" / "state" / "current.json").is_file():
            entry["projectpilot"] = col.guard(f"projectpilot:{name}", projectpilot_info, d / "_projectpilot", now)
        projects[name] = entry
    return projects


# ---------------------------------------------------------------- mac (daily)

def parse_launchctl_list(text: str, prefixes: list[str]) -> dict:
    services = {}
    for line in text.splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        pid, status, label = parts
        if not any(label.startswith(p) for p in prefixes):
            continue
        services[label] = {"loaded": True, "pid": None if pid == "-" else int(pid),
                           "last_exit": int(status) if status.lstrip("-").isdigit() else None}
    return services


def collect_launchd(prefixes: list[str], agents_dir: Path) -> dict:
    services = parse_launchctl_list(run(["launchctl", "list"]), prefixes)
    for plist in agents_dir.glob("*.plist"):
        label = plist.stem
        if any(label.startswith(p) for p in prefixes) and label not in services:
            services[label] = {"loaded": False, "pid": None, "last_exit": None}
    for s in services.values():
        s["running"] = s["pid"] is not None
        # 常駐でないジョブ（定時実行）は pid なし・終了コード0 が正常
        s["healthy"] = s["loaded"] and (s["running"] or s["last_exit"] == 0)
    return dict(sorted(services.items()))


def collect_disk(path: str) -> dict:
    u = shutil.disk_usage(path)
    return {"path": path, "free_gb": round(u.free / 1e9, 1), "free_pct": round(u.free / u.total * 100, 1)}


# ---------------------------------------------------------------- weekly

def collect_brew(brewfile: Path) -> dict:
    out = json.loads(run(["brew", "outdated", "--json=v2"], timeout=120))
    result = {"outdated_formulae": len(out.get("formulae", [])), "outdated_casks": len(out.get("casks", []))}
    if brewfile.is_file():
        p = subprocess.run(["brew", "bundle", "check", "--no-upgrade", "--verbose", f"--file={brewfile}"],
                           capture_output=True, text=True, timeout=180, env=tool_env())
        missing = [ln.strip() for ln in p.stdout.splitlines() if "needs to be installed" in ln or "is not installed" in ln]
        result["brewfile_missing"] = missing[:50]
        result["brewfile_satisfied"] = p.returncode == 0
    return result


def collect_versions(tools: dict[str, list[str]]) -> dict:
    versions = {}
    for name, cmd in tools.items():
        try:
            versions[name] = run(cmd, timeout=15).strip().splitlines()[0][:80]
        except Exception as e:  # noqa: BLE001
            versions[name] = f"unavailable: {e}"[:80]
    return versions


def collect_open_prs() -> list[dict]:
    out = run(["gh", "search", "prs", "--author=@me", "--state=open", "--limit=100",
               "--json", "repository,title,url,updatedAt"], timeout=60)
    return [{"repo": p["repository"]["nameWithOwner"], "title": p["title"][:120], "url": p["url"],
             "updated": p["updatedAt"]} for p in json.loads(out)]


CACHE_VERSION = 2


def collect_token_usage(projects_dir: Path, cache_path: Path, now: dt.datetime, days: int = 7) -> dict:
    """Claude Code のトランスクリプトからトークン数を集計する。ファイル単位で mtime/size を見て増分処理。"""
    cache = json.loads(cache_path.read_text()) if cache_path.is_file() else {}
    since = now - dt.timedelta(days=days)
    fresh = {}
    for f in projects_dir.glob("*/*.jsonl"):
        st = f.stat()
        if dt.datetime.fromtimestamp(st.st_mtime, dt.timezone.utc) < since:
            continue
        key, sig = str(f), f"{CACHE_VERSION}:{st.st_mtime_ns}:{st.st_size}"
        if cache.get(key, {}).get("sig") == sig:
            fresh[key] = cache[key]
            continue
        per_msg: dict[str, tuple] = {}  # ストリーミングで同じ message.id が複数行に出るため最後の値を採用
        with f.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if '"usage"' not in line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                m = d.get("message")
                if not isinstance(m, dict) or not m.get("usage"):
                    continue
                u = m["usage"]
                tokens = sum(int(u.get(k) or 0) for k in ("input_tokens", "output_tokens",
                                                          "cache_creation_input_tokens", "cache_read_input_tokens"))
                per_msg[m.get("id") or str(len(per_msg))] = ((d.get("timestamp") or "")[:10], d.get("cwd") or "",
                                                              m.get("model") or "", tokens, int(u.get("output_tokens") or 0),
                                                              int(u.get("cache_read_input_tokens") or 0))
        rows: dict[str, list] = {}
        for day, cwd, model, *counts in per_msg.values():
            row = rows.setdefault("|".join((day, cwd, model)), [0, 0, 0])
            for i, n in enumerate(counts):
                row[i] += n
        fresh[key] = {"sig": sig, "rows": rows}
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(fresh))
    tmp.replace(cache_path)

    by_project: dict[str, int] = defaultdict(int)
    by_model: dict[str, int] = defaultdict(int)
    by_day: dict[str, int] = defaultdict(int)
    output_total = cache_read_total = 0
    since_day = since.date().isoformat()
    for entry in fresh.values():
        for k, (tokens, out_tokens, cache_read) in entry["rows"].items():
            day, cwd, model = k.split("|", 2)
            if day < since_day:
                continue
            project = cwd.split("/project/", 1)[1].split("/", 1)[0] if "/project/" in cwd else (cwd or "(unknown)")
            by_project[project] += tokens
            by_model[model] += tokens
            by_day[day] += tokens
            output_total += out_tokens
            cache_read_total += cache_read
    top = sorted(by_project.items(), key=lambda x: -x[1])
    return {"days": days, "total_tokens": sum(by_day.values()), "output_tokens": output_total,
            "cache_read_tokens": cache_read_total,
            "by_day": dict(sorted(by_day.items())), "by_model": dict(sorted(by_model.items(), key=lambda x: -x[1])),
            "by_project_top": dict(top[:15])}


# ---------------------------------------------------------------- alerts / diff

def compute_alerts(snap: dict, cfg: dict, previous: dict | None) -> list[dict]:
    th = cfg["thresholds"]
    alerts = []
    if snap["collection_status"] != "complete":
        alerts.append({"level": "error" if snap["collection_status"] == "error" else "warn", "kind": "collection",
                       "subject": "ops-pulse", "message": f"収集が {snap['collection_status']}（失敗 {len(snap['failures'])} 件）"})
    prev_services = (previous or {}).get("mac", {}).get("launchd") or {}
    for label, s in (snap["mac"].get("launchd") or {}).items():
        if s["healthy"]:
            continue
        streak = (prev_services.get(label, {}).get("unhealthy_streak") or 0) + 1
        s["unhealthy_streak"] = streak
        why = "未ロード" if not s["loaded"] else f"停止中（最後の終了コード {s['last_exit']}）"
        alerts.append({"level": "error", "kind": "service", "subject": label, "message": f"{why}・連続 {streak} 回"})
    disk = snap["mac"].get("disk")
    if disk and (disk["free_pct"] < th["disk_free_pct"] or disk["free_gb"] < th["disk_free_gb"]):
        alerts.append({"level": "warn", "kind": "disk", "subject": disk["path"],
                       "message": f"空き {disk['free_gb']} GB（{disk['free_pct']}%）"})
    if previous and previous.get("collection_status") == "complete" and snap["counts"]["projects"] < previous["counts"]["projects"]:
        alerts.append({"level": "warn", "kind": "scope", "subject": "projects",
                       "message": f"対象プロジェクト数が {previous['counts']['projects']} → {snap['counts']['projects']} に減少"})
    for name, p in snap["projects"].items():
        pp = p.get("projectpilot") or {}
        if (pp.get("oldest_pending_days") or 0) >= th["pending_approval_days"]:
            alerts.append({"level": "warn", "kind": "approval", "subject": name,
                           "message": f"承認待ちの移行提案が {pp['oldest_pending_days']} 日滞留"})
        g = p.get("git") or {}
        if (g.get("ahead") or 0) > 0 and (age_days(g.get("last_commit"), parse_ts(snap["collected_at"])) or 0) >= th["unpushed_days"]:
            alerts.append({"level": "info", "kind": "unpushed", "subject": name,
                           "message": f"未 push のコミット {g['ahead']} 件（最終コミットから {age_days(g['last_commit'], parse_ts(snap['collected_at']))} 日）"})
    order = {"error": 0, "warn": 1, "info": 2}
    # 収集自身の失敗は、他の判定の前提が崩れていることを示すので常に先頭
    return sorted(alerts, key=lambda a: (a["kind"] != "collection", order[a["level"]], a["kind"], a["subject"]))


# 差分から外す項目。時間とともに必ず変わる値は差分ではなく compute_alerts の時刻判定で扱う
VOLATILE = {"collected_at", "duration_sec", "unhealthy_streak", "pid", "free_gb", "free_pct",
            "oldest_pending_days", "oldest_open_card_days"}


def flatten(obj, prefix: str = "") -> dict:
    out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in VOLATILE:
                continue
            out.update(flatten(v, f"{prefix}.{k}" if prefix else k))
    else:
        out[prefix] = obj
    return out


def compute_diff(snap: dict, previous: dict | None) -> dict:
    """意味のある差分。quiet は complete・同じ範囲・差分なし・異常なしのときだけ True（§4.1）。"""
    base = {"schema_version": SCHEMA_VERSION, "collected_at": snap["collected_at"],
            "previous_collected_at": (previous or {}).get("collected_at")}
    if previous is None:
        return {**base, "quiet": False, "reason": "前回の state がない（初回）", "changes": []}
    keys = ("projects", "mac")
    a, b = flatten({k: previous.get(k) for k in keys}), flatten({k: snap.get(k) for k in keys})
    changes = [{"key": k, "before": a.get(k), "after": b.get(k)} for k in sorted(set(a) | set(b)) if a.get(k) != b.get(k)]
    same_scope = previous.get("config_hash") == snap["config_hash"] and \
        set(previous.get("projects", {})) == set(snap["projects"])
    complete = snap["collection_status"] == "complete" and previous.get("collection_status") == "complete"
    quiet = complete and same_scope and not changes and not snap["alerts"]
    reason = "差分なし" if quiet else ("収集が不完全" if not complete else "範囲が変わった" if not same_scope
                                    else "異常あり" if snap["alerts"] and not changes else "差分あり")
    return {**base, "quiet": quiet, "reason": reason, "complete": complete, "same_scope": same_scope,
            "changes": changes[:500], "changes_total": len(changes)}


# ---------------------------------------------------------------- digest

def render_digest(snap: dict, diff: dict) -> str:
    local = parse_ts(snap["collected_at"]).astimezone()
    L = [f"# ops-pulse {local:%Y-%m-%d %H:%M}", "",
         f"- 収集: **{snap['collection_status']}**（{snap['duration_sec']} 秒、プロジェクト {snap['counts']['projects']} 件）",
         f"- 前回との差分: {diff['reason']}（{diff.get('changes_total', 0)} 件）", ""]
    L.append("## 異常・要確認")
    if snap["alerts"]:
        L += [f"- [{a['level']}] {a['subject']} — {a['message']}" for a in snap["alerts"]]
    else:
        L.append("- なし")
    if snap["failures"]:
        L += ["", "## 収集の失敗"] + [f"- {f['section']}: {f['error']}" for f in snap["failures"]]
    L += ["", "## プロジェクト", "", "| プロジェクト | ブランチ | 未コミット | 未push | 最終コミット | decisions | ProjectPilot |",
          "|---|---|---:|---:|---|---|---|"]
    now = parse_ts(snap["collected_at"])
    for name, p in snap["projects"].items():
        g, d, pp = p.get("git") or {}, p.get("decisions") or {}, p.get("projectpilot")
        if not (g or d or pp):
            continue
        last = age_days(g.get("last_commit"), now)
        dec = f"{d['count']}件・{age_days(d['last'], now)}日前" if d.get("last") else ""
        ppt = f"{pp['stage']}・承認待ち{pp['pending_transitions']}・カード{sum(pp['cards'].values())}" if pp else ""
        L.append(f"| {name} | {g.get('branch', '—')} | {g.get('dirty', '')} | {g.get('ahead') if g.get('ahead') is not None else ''} "
                 f"| {f'{last}日前' if last is not None else ''} | {dec} | {ppt} |")
    plain = [n for n, p in snap["projects"].items() if not (p.get("git") or p.get("decisions") or p.get("projectpilot"))]
    if plain:
        L += ["", f"git・decisions・ProjectPilot のいずれもないフォルダ: {', '.join(plain)}"]
    mac = snap["mac"]
    L += ["", "## Mac"]
    if mac.get("disk"):
        L.append(f"- ディスク空き: {mac['disk']['free_gb']} GB（{mac['disk']['free_pct']}%）")
    svc = mac.get("launchd") or {}
    L.append(f"- LaunchAgent: {sum(s['healthy'] for s in svc.values())}/{len(svc)} 正常")
    w = snap.get("weekly")
    if w:
        L += ["", f"## 週次（{parse_ts(w['collected_at']).astimezone():%Y-%m-%d} 収集）"]
        if w.get("brew"):
            b = w["brew"]
            L.append(f"- brew outdated: formula {b['outdated_formulae']} / cask {b['outdated_casks']}"
                     + (f"、Brewfile 未導入 {len(b.get('brewfile_missing', []))} 件" if "brewfile_missing" in b else ""))
        if w.get("versions"):
            L.append("- 版: " + " / ".join(f"{k} {v}" for k, v in w["versions"].items()))
        if w.get("open_prs") is not None:
            L.append(f"- open PR: {len(w['open_prs'])} 件")
            L += [f"  - {p['repo']}: {p['title']}" for p in w["open_prs"][:10]]
        if w.get("tokens"):
            t = w["tokens"]
            L.append(f"- Claude Code トークン（直近{t['days']}日）: {t['total_tokens']:,}"
                     f"（うちキャッシュ読込 {t.get('cache_read_tokens', 0):,}、出力 {t['output_tokens']:,}）")
            L += [f"  - {k}: {v:,}" for k, v in list(t["by_project_top"].items())[:8]]
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- main

def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def load_config(path: Path) -> tuple[dict, str]:
    raw = path.read_bytes()
    cfg = json.loads(raw)
    for k in ("root", "data_dir", "launch_agents_dir", "brewfile", "claude_projects_dir"):
        cfg[k] = str(Path(os.path.expanduser(cfg[k])) if Path(os.path.expanduser(cfg[k])).is_absolute()
                     else (path.parent / cfg[k]).resolve())
    return cfg, hashlib.sha256(raw).hexdigest()[:16]


def collect(cfg: dict, config_hash: str, weekly: bool, previous: dict | None) -> dict:
    started, now = time.monotonic(), now_utc()
    col = Collector()
    projects = col.guard("projects", collect_projects, Path(cfg["root"]), col, now, default={}) or {}
    mac = {
        "launchd": col.guard("launchd", collect_launchd, cfg["launchd_prefixes"], Path(cfg["launch_agents_dir"])),
        "disk": col.guard("disk", collect_disk, cfg["disk_path"]),
    }
    snap = {
        "schema_version": SCHEMA_VERSION,
        "collector": "ops-pulse",
        "collected_at": iso(now),
        "config_hash": config_hash,
        "scope": {"root": cfg["root"], "weekly": weekly},
        "projects": projects,
        "mac": mac,
        "counts": {"projects": len(projects), "git": sum("git" in p for p in projects.values()),
                   "decisions": sum("decisions" in p for p in projects.values()),
                   "projectpilot": sum("projectpilot" in p for p in projects.values())},
    }
    if weekly:
        data = Path(cfg["data_dir"])
        snap["weekly"] = {
            "collected_at": iso(now),
            "brew": col.guard("brew", collect_brew, Path(cfg["brewfile"])),
            "versions": col.guard("versions", collect_versions, cfg["versions"]),
            "open_prs": col.guard("open_prs", collect_open_prs),
            "tokens": col.guard("tokens", collect_token_usage, Path(cfg["claude_projects_dir"]),
                                data / "token-cache.json", now),
        }
    elif previous and previous.get("weekly"):
        snap["weekly"] = previous["weekly"]  # 週次の結果は直近のものを引き継ぐ（collected_at で鮮度がわかる）
    snap["failures"] = col.failures
    snap["collection_status"] = col.status()
    snap["duration_sec"] = round(time.monotonic() - started, 1)
    snap["alerts"] = compute_alerts(snap, cfg, previous)
    return snap


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    ap.add_argument("--weekly", action="store_true", help="週次の収集も行う")
    ap.add_argument("--print", action="store_true", help="ダイジェストを標準出力に出す")
    args = ap.parse_args(argv)

    cfg, config_hash = load_config(args.config)
    data = Path(cfg["data_dir"])
    latest_path = data / "latest.json"
    previous = json.loads(latest_path.read_text(encoding="utf-8")) if latest_path.is_file() else None

    snap = collect(cfg, config_hash, args.weekly, previous)
    diff = compute_diff(snap, previous)
    digest = render_digest(snap, diff)

    local_day = parse_ts(snap["collected_at"]).astimezone().date().isoformat()
    body = json.dumps(snap, ensure_ascii=False, indent=1)
    atomic_write(data / "snapshots" / f"{local_day}.json", body)
    atomic_write(latest_path, body)
    atomic_write(data / "diff.json", json.dumps(diff, ensure_ascii=False, indent=1))
    atomic_write(data / "digest.md", digest)
    if args.print:
        print(digest)
    return {"complete": 0, "partial": 1, "error": 2}[snap["collection_status"]]


if __name__ == "__main__":
    sys.exit(main())
