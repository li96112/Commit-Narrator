#!/usr/bin/env python3
"""Commit-Narrator: Analyze git history and generate a project narrative.

Reads git log, classifies commits, detects project eras/milestones,
identifies hotspots and key contributors, then outputs a readable
story of how the project evolved.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta


# ---------------------------------------------------------------------------
# Git data extraction
# ---------------------------------------------------------------------------

def run_git(args, cwd=None):
    """Run a git command and return stdout."""
    result = subprocess.run(
        ["git"] + args,
        capture_output=True, text=True, cwd=cwd,
    )
    if result.returncode != 0:
        return ""
    return result.stdout


def get_commits(cwd=None, since=None, until=None, author=None, path=None, max_count=5000):
    """Extract structured commit data from git log."""
    # Format: hash|author|email|date|subject
    sep = "|||"
    fmt = f"%H{sep}%an{sep}%ae{sep}%aI{sep}%s"
    args = ["log", f"--format={fmt}", f"--max-count={max_count}", "--no-merges"]

    if since:
        args.append(f"--since={since}")
    if until:
        args.append(f"--until={until}")
    if author:
        args.append(f"--author={author}")

    # Add --numstat for file change stats
    args.append("--numstat")

    if path:
        args.extend(["--", path])

    raw = run_git(args, cwd)
    if not raw:
        return []

    commits = []
    current = None

    for line in raw.split("\n"):
        if sep in line:
            if current:
                commits.append(current)
            parts = line.split(sep)
            if len(parts) >= 5:
                current = {
                    "hash": parts[0][:8],
                    "hash_full": parts[0],
                    "author": parts[1],
                    "email": parts[2],
                    "date": parts[3][:10],
                    "datetime": parts[3],
                    "subject": parts[4],
                    "files": [],
                    "insertions": 0,
                    "deletions": 0,
                }
        elif current and line.strip():
            # numstat line: additions\tdeletions\tfilename
            parts = line.split("\t")
            if len(parts) == 3:
                try:
                    ins = int(parts[0]) if parts[0] != "-" else 0
                    dels = int(parts[1]) if parts[1] != "-" else 0
                    current["files"].append({
                        "name": parts[2],
                        "insertions": ins,
                        "deletions": dels,
                    })
                    current["insertions"] += ins
                    current["deletions"] += dels
                except ValueError:
                    pass

    if current:
        commits.append(current)

    return commits


def get_repo_info(cwd=None):
    """Get basic repo metadata."""
    name = run_git(["rev-parse", "--show-toplevel"], cwd).strip()
    name = os.path.basename(name) if name else "unknown"
    branch = run_git(["branch", "--show-current"], cwd).strip()
    remote = run_git(["remote", "get-url", "origin"], cwd).strip()
    total_commits = run_git(["rev-list", "--count", "HEAD"], cwd).strip()

    return {
        "name": name,
        "branch": branch,
        "remote": remote,
        "total_commits": int(total_commits) if total_commits.isdigit() else 0,
    }


# ---------------------------------------------------------------------------
# Commit classification
# ---------------------------------------------------------------------------

COMMIT_TYPES = {
    "feat": {
        "patterns": [r"^feat[\(:]", r"^add[\s:]", r"^新增", r"^添加", r"^implement", r"^support"],
        "label": "Feature",
        "emoji": "+",
    },
    "fix": {
        "patterns": [r"^fix[\(:]", r"^bug[\s:]", r"^修复", r"^hotfix", r"^patch"],
        "label": "Bug Fix",
        "emoji": "x",
    },
    "refactor": {
        "patterns": [r"^refactor[\(:]", r"^重构", r"^restructure", r"^reorganize", r"^clean"],
        "label": "Refactor",
        "emoji": "~",
    },
    "docs": {
        "patterns": [r"^docs?[\(:]", r"^文档", r"^readme", r"^changelog"],
        "label": "Documentation",
        "emoji": "#",
    },
    "test": {
        "patterns": [r"^test[\(:]", r"^测试", r"^spec[\(:]"],
        "label": "Test",
        "emoji": "?",
    },
    "style": {
        "patterns": [r"^style[\(:]", r"^lint", r"^format", r"^样式"],
        "label": "Style",
        "emoji": ".",
    },
    "perf": {
        "patterns": [r"^perf[\(:]", r"^优化", r"^optimize", r"^performance"],
        "label": "Performance",
        "emoji": "^",
    },
    "chore": {
        "patterns": [r"^chore[\(:]", r"^build[\(:]", r"^ci[\(:]", r"^deps", r"^bump",
                     r"^upgrade", r"^update dep", r"^配置"],
        "label": "Chore",
        "emoji": ".",
    },
    "init": {
        "patterns": [r"^init", r"^initial", r"^first commit", r"^初始"],
        "label": "Init",
        "emoji": "*",
    },
    "release": {
        "patterns": [r"^release", r"^v\d+\.", r"^版本", r"^tag"],
        "label": "Release",
        "emoji": "!",
    },
    "revert": {
        "patterns": [r"^revert", r"^回滚"],
        "label": "Revert",
        "emoji": "<",
    },
}


def classify_commit(subject, files=None):
    """Classify a commit message into a type."""
    s = subject.lower().strip()

    # First: try conventional commit patterns
    for ctype, info in COMMIT_TYPES.items():
        for pat in info["patterns"]:
            if re.search(pat, s, re.I):
                return ctype

    # Second: fuzzy matching for non-conventional messages
    # Fix-like
    if any(w in s for w in ["fix", "bug", "error", "issue", "crash", "broken", "repair",
                             "修复", "修正", "解决", "问题", "报错"]):
        return "fix"
    # Feature-like
    if any(w in s for w in ["add", "create", "new", "implement", "introduce", "enable",
                             "新增", "添加", "创建", "实现", "增加", "开发"]):
        return "feat"
    # Refactor-like
    if any(w in s for w in ["refactor", "restructure", "simplify", "clean up", "extract",
                             "rename", "move", "split", "merge", "reorganize",
                             "重构", "简化", "提取", "重命名", "拆分"]):
        return "refactor"
    # Style/format
    if any(w in s for w in ["format", "lint", "style", "indent", "whitespace", "prettier",
                             "格式化", "格式"]):
        return "style"
    # Docs
    if any(w in s for w in ["readme", "doc", "comment", "changelog", "license",
                             "文档", "注释", "说明"]):
        return "docs"
    # Test
    if any(w in s for w in ["test", "spec", "assert", "mock", "测试"]):
        return "test"
    # Chore/deps
    if any(w in s for w in ["upgrade", "update", "bump", "remove", "delete", "clean",
                             "config", "ci", "cd", "deploy", "build", "docker",
                             "更新", "升级", "删除", "配置", "部署"]):
        return "chore"
    # Performance
    if any(w in s for w in ["perf", "optim", "speed", "fast", "cache", "lazy",
                             "优化", "性能", "加速"]):
        return "perf"

    # Third: infer from file paths if message is ambiguous
    if files:
        file_names = [f["name"] for f in files] if isinstance(files[0], dict) else files
        all_test = all(any(p in f for p in ["test", "spec", "__tests__"]) for f in file_names)
        all_docs = all(any(p in f.lower() for p in ["readme", "doc", "changelog", "license", ".md"]) for f in file_names)
        all_ci = all(any(p in f for p in [".github/", "Dockerfile", ".gitlab-ci", "Jenkinsfile",
                                           ".circleci", "docker-compose"]) for f in file_names)
        all_config = all(any(p in f for p in ["package.json", "tsconfig", ".eslint", ".prettier",
                                               "webpack", "vite.config", "babel"]) for f in file_names)
        if all_test:
            return "test"
        if all_docs:
            return "docs"
        if all_ci:
            return "chore"
        if all_config:
            return "chore"

    return "other"


def extract_scope(subject):
    """Extract scope from conventional commit: feat(scope): ..."""
    m = re.match(r'^\w+\(([^)]+)\)', subject)
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# Analysis engine
# ---------------------------------------------------------------------------

class CommitAnalyzer:
    def __init__(self, commits, repo_info):
        self.commits = commits
        self.repo = repo_info
        self.classified = [(c, classify_commit(c["subject"], c.get("files"))) for c in commits]

    def summary(self):
        """Overall project summary."""
        if not self.commits:
            return {"error": "No commits found"}

        dates = [c["date"] for c in self.commits]
        authors = Counter(c["author"] for c in self.commits)
        types = Counter(t for _, t in self.classified)
        total_ins = sum(c["insertions"] for c in self.commits)
        total_dels = sum(c["deletions"] for c in self.commits)

        # Time span
        first_date = min(dates)
        last_date = max(dates)
        days = (datetime.fromisoformat(last_date) - datetime.fromisoformat(first_date)).days + 1

        return {
            "repo": self.repo["name"],
            "branch": self.repo["branch"],
            "total_commits": len(self.commits),
            "first_commit": first_date,
            "last_commit": last_date,
            "active_days": days,
            "avg_commits_per_day": round(len(self.commits) / max(days, 1), 1),
            "authors": dict(authors.most_common()),
            "author_count": len(authors),
            "commit_types": dict(types.most_common()),
            "total_insertions": total_ins,
            "total_deletions": total_dels,
            "net_lines": total_ins - total_dels,
        }

    def detect_eras(self):
        """Detect project eras based on activity patterns and commit content."""
        if len(self.commits) < 3:
            dates = [c["date"] for c in self.commits]
            types = Counter(classify_commit(c["subject"], c.get("files")) for c in self.commits)
            return [{
                "name": "单一阶段",
                "start": min(dates),
                "end": max(dates),
                "commit_count": len(self.commits),
                "types_summary": dict(types.most_common()),
                "dominant_type": types.most_common(1)[0][0] if types else "other",
                "key_commits": [
                    {"hash": c["hash"], "date": c["date"], "subject": c["subject"]}
                    for c in self.commits[:5]
                ],
            }]

        # Group by week
        weeks = defaultdict(list)
        for c, t in self.classified:
            # ISO week
            dt = datetime.fromisoformat(c["datetime"].replace("Z", "+00:00") if "Z" in c["datetime"] else c["datetime"])
            week_key = dt.strftime("%Y-W%W")
            weeks[week_key].append((c, t))

        # Detect era boundaries: significant gaps or type shifts
        eras = []
        current_era = {
            "start": None, "end": None, "commits": [],
            "types": Counter(), "dominant_type": None,
        }

        sorted_weeks = sorted(weeks.items())
        prev_week_dt = None

        for week_key, week_commits in sorted_weeks:
            # Parse week start
            year, week_num = week_key.split("-W")
            try:
                week_dt = datetime.strptime(f"{year}-W{week_num}-1", "%Y-W%W-%w")
            except:
                continue

            # Check for gap (>4 weeks of inactivity)
            gap = False
            if prev_week_dt and (week_dt - prev_week_dt).days > 28:
                gap = True

            if gap and current_era["commits"]:
                current_era["end"] = current_era["commits"][-1]["date"]
                current_era["dominant_type"] = current_era["types"].most_common(1)[0][0] if current_era["types"] else "other"
                eras.append(current_era)
                current_era = {
                    "start": None, "end": None, "commits": [],
                    "types": Counter(), "dominant_type": None,
                }

            for c, t in week_commits:
                if current_era["start"] is None:
                    current_era["start"] = c["date"]
                current_era["commits"].append(c)
                current_era["types"][t] += 1

            prev_week_dt = week_dt

        # Final era
        if current_era["commits"]:
            current_era["end"] = current_era["commits"][-1]["date"]
            current_era["dominant_type"] = current_era["types"].most_common(1)[0][0] if current_era["types"] else "other"
            eras.append(current_era)

        # Name eras based on dominant activity
        era_names = {
            "init": "项目启动",
            "feat": "功能建设",
            "fix": "稳定收敛",
            "refactor": "架构重构",
            "docs": "文档完善",
            "chore": "日常维护",
            "perf": "性能优化",
            "release": "发布准备",
        }

        for i, era in enumerate(eras):
            dt = era.get("dominant_type", "other")
            base_name = era_names.get(dt, "开发中")
            era["name"] = f"第{i+1}阶段: {base_name}"
            era["commit_count"] = len(era["commits"])
            era["types_summary"] = dict(era["types"].most_common())
            # Don't include full commit list in JSON output
            era["key_commits"] = [
                {"hash": c["hash"], "date": c["date"], "subject": c["subject"]}
                for c in era["commits"][:5]
            ]
            del era["commits"]
            del era["types"]

        return eras

    def detect_milestones(self):
        """Detect major milestones — large commits, releases, architectural changes."""
        milestones = []

        for c, t in self.classified:
            is_milestone = False
            reason = ""

            # Release/version tags
            if t == "release":
                is_milestone = True
                reason = "版本发布"

            # Init commit
            elif t == "init":
                is_milestone = True
                reason = "项目初始化"

            # Large commits (>500 lines changed)
            elif c["insertions"] + c["deletions"] > 500:
                is_milestone = True
                reason = f"重大变更（{c['insertions']}+ / {c['deletions']}-）"

            # Many files changed (>20)
            elif len(c["files"]) > 20:
                is_milestone = True
                reason = f"大范围影响（{len(c['files'])} 个文件）"

            # Keywords indicating architectural changes
            arch_keywords = ["migration", "migrate", "architecture", "redesign", "rewrite",
                             "major", "breaking", "v2", "v3", "迁移", "重构", "架构"]
            if any(kw in c["subject"].lower() for kw in arch_keywords):
                is_milestone = True
                reason = "架构变更"

            if is_milestone:
                milestones.append({
                    "hash": c["hash"],
                    "date": c["date"],
                    "author": c["author"],
                    "subject": c["subject"],
                    "reason": reason,
                    "insertions": c["insertions"],
                    "deletions": c["deletions"],
                    "files_changed": len(c["files"]),
                })

        return milestones

    def hotspot_files(self, top_n=15):
        """Find files that change most frequently — high risk areas."""
        file_changes = Counter()
        file_authors = defaultdict(set)
        file_churn = defaultdict(int)  # total lines changed

        for c in self.commits:
            for f in c["files"]:
                name = f["name"]
                file_changes[name] += 1
                file_authors[name].add(c["author"])
                file_churn[name] += f["insertions"] + f["deletions"]

        result = []
        for name, count in file_changes.most_common(top_n):
            result.append({
                "file": name,
                "commits": count,
                "authors": len(file_authors[name]),
                "churn": file_churn[name],
                "risk": "高" if count > 20 else "中" if count > 10 else "低",
            })

        return result

    def temporal_coupling(self, min_co_changes=3, top_n=10):
        """Find files that always change together — architectural coupling."""
        from itertools import combinations

        pair_counts = Counter()
        for c in self.commits:
            files = [f["name"] for f in c["files"] if not f["name"].startswith(".")]
            if 2 <= len(files) <= 30:  # Skip single-file and massive commits
                for a, b in combinations(sorted(files), 2):
                    pair_counts[(a, b)] += 1

        result = []
        for (a, b), count in pair_counts.most_common(top_n):
            if count >= min_co_changes:
                result.append({
                    "file_a": a,
                    "file_b": b,
                    "co_changes": count,
                    "coupling": "强耦合" if count > 10 else "中等耦合" if count > 5 else "弱耦合",
                })

        return result

    def author_profiles(self):
        """Build contributor profiles — what they work on, when they're active."""
        profiles = defaultdict(lambda: {
            "commits": 0, "insertions": 0, "deletions": 0,
            "types": Counter(), "files": Counter(), "first": None, "last": None,
            "active_days": set(),
        })

        for c, t in self.classified:
            p = profiles[c["author"]]
            p["commits"] += 1
            p["insertions"] += c["insertions"]
            p["deletions"] += c["deletions"]
            p["types"][t] += 1
            p["active_days"].add(c["date"])
            for f in c["files"]:
                # Use directory as area
                parts = f["name"].split("/")
                area = parts[0] if len(parts) > 1 else "root"
                p["files"][area] += 1

            if p["first"] is None or c["date"] < p["first"]:
                p["first"] = c["date"]
            if p["last"] is None or c["date"] > p["last"]:
                p["last"] = c["date"]

        result = []
        for author, p in sorted(profiles.items(), key=lambda x: -x[1]["commits"]):
            top_areas = [area for area, _ in p["files"].most_common(3)]
            TYPE_LABELS_ZH = {
                "feat": "新功能", "fix": "Bug 修复", "refactor": "重构", "docs": "文档",
                "test": "测试", "style": "样式", "perf": "性能优化", "chore": "杂务",
                "init": "初始化", "release": "版本发布", "revert": "回滚", "other": "其他",
            }
            top_types = [TYPE_LABELS_ZH.get(t, t) for t, _ in p["types"].most_common(3)]
            result.append({
                "author": author,
                "commits": p["commits"],
                "insertions": p["insertions"],
                "deletions": p["deletions"],
                "net_lines": p["insertions"] - p["deletions"],
                "active_days": len(p["active_days"]),
                "first_commit": p["first"],
                "last_commit": p["last"],
                "top_areas": top_areas,
                "focus": ", ".join(top_types),
            })

        return result

    def bus_factor(self):
        """Calculate bus factor per directory — how many people hold the knowledge."""
        dir_authors = defaultdict(lambda: Counter())

        for c in self.commits:
            for f in c["files"]:
                parts = f["name"].split("/")
                directory = parts[0] if len(parts) > 1 else "root"
                dir_authors[directory][c["author"]] += 1

        result = []
        for directory, authors in sorted(dir_authors.items(), key=lambda x: -sum(x[1].values())):
            total_commits = sum(authors.values())
            # Bus factor = number of authors contributing >5% of changes
            significant = [a for a, c in authors.items() if c / total_commits > 0.05]
            bf = len(significant)
            top_author = authors.most_common(1)[0]
            top_pct = top_author[1] / total_commits * 100

            result.append({
                "directory": directory,
                "bus_factor": bf,
                "total_commits": total_commits,
                "top_contributor": top_author[0],
                "top_contributor_pct": round(top_pct, 1),
                "risk": "极高" if bf == 1 and total_commits > 5 else
                        "高" if bf <= 2 and total_commits > 10 else "正常",
            })

        return [r for r in result if r["total_commits"] >= 3][:15]

    def activity_heatmap(self):
        """Generate weekly activity data for visualization."""
        weeks = defaultdict(int)
        for c in self.commits:
            dt = datetime.fromisoformat(c["datetime"].replace("Z", "+00:00") if "Z" in c["datetime"] else c["datetime"])
            week_key = dt.strftime("%Y-W%W")
            weeks[week_key] += 1

        # Day-of-week distribution
        dow = Counter()
        hour = Counter()
        for c in self.commits:
            dt = datetime.fromisoformat(c["datetime"].replace("Z", "+00:00") if "Z" in c["datetime"] else c["datetime"])
            dow[dt.strftime("%A")] += 1
            hour[dt.hour] += 1

        return {
            "weekly_activity": dict(sorted(weeks.items())),
            "day_of_week": dict(dow.most_common()),
            "hour_distribution": dict(sorted(hour.items())),
            "busiest_week": max(weeks.items(), key=lambda x: x[1]) if weeks else None,
            "busiest_day": dow.most_common(1)[0] if dow else None,
        }

    def velocity_trend(self):
        """Calculate development velocity over time (commits per week, lines per week)."""
        weeks = defaultdict(lambda: {"commits": 0, "insertions": 0, "deletions": 0})
        for c in self.commits:
            dt = datetime.fromisoformat(c["datetime"].replace("Z", "+00:00") if "Z" in c["datetime"] else c["datetime"])
            week_key = dt.strftime("%Y-W%W")
            weeks[week_key]["commits"] += 1
            weeks[week_key]["insertions"] += c["insertions"]
            weeks[week_key]["deletions"] += c["deletions"]

        sorted_weeks = sorted(weeks.items())
        if len(sorted_weeks) < 2:
            return {"trend": "insufficient_data"}

        # Compare first half vs second half
        mid = len(sorted_weeks) // 2
        first_half = sorted_weeks[:mid]
        second_half = sorted_weeks[mid:]

        avg_first = sum(w["commits"] for _, w in first_half) / max(len(first_half), 1)
        avg_second = sum(w["commits"] for _, w in second_half) / max(len(second_half), 1)

        if avg_second > avg_first * 1.2:
            trend = "accelerating"
        elif avg_second < avg_first * 0.8:
            trend = "decelerating"
        else:
            trend = "steady"

        return {
            "trend": trend,
            "avg_commits_first_half": round(avg_first, 1),
            "avg_commits_second_half": round(avg_second, 1),
            "total_weeks": len(sorted_weeks),
        }

    def run_full_analysis(self):
        """Run all analyses and return complete report data."""
        return {
            "summary": self.summary(),
            "eras": self.detect_eras(),
            "milestones": self.detect_milestones(),
            "hotspots": self.hotspot_files(),
            "coupling": self.temporal_coupling(),
            "bus_factor": self.bus_factor(),
            "contributors": self.author_profiles(),
            "activity": self.activity_heatmap(),
            "velocity": self.velocity_trend(),
        }


# ---------------------------------------------------------------------------
# Narrative generator
# ---------------------------------------------------------------------------

def generate_narrative(analysis, lang="zh"):
    """Generate a human-readable narrative from analysis data."""
    s = analysis["summary"]
    eras = analysis["eras"]
    milestones = analysis["milestones"]
    hotspots = analysis["hotspots"]
    coupling = analysis.get("coupling", [])
    contributors = analysis["contributors"]
    activity = analysis["activity"]
    velocity = analysis["velocity"]

    # Chinese labels for commit types
    TYPE_LABELS_ZH = {
        "feat": "新功能",
        "fix": "Bug 修复",
        "refactor": "重构",
        "docs": "文档",
        "test": "测试",
        "style": "样式",
        "perf": "性能优化",
        "chore": "杂务",
        "init": "初始化",
        "release": "版本发布",
        "revert": "回滚",
        "other": "其他",
    }

    # Chinese labels for era names
    ERA_NAMES_ZH = {
        "Bootstrap": "项目启动",
        "Feature Build": "功能建设",
        "Stabilization": "稳定收敛",
        "Refactoring": "架构重构",
        "Documentation": "文档完善",
        "Maintenance": "日常维护",
        "Optimization": "性能优化",
        "Release Prep": "发布准备",
        "Development": "开发中",
        "Single Era": "单一阶段",
    }

    # Chinese labels for risk levels
    RISK_ZH = {"HIGH": "高", "MEDIUM": "中", "LOW": "低", "CRITICAL": "极高", "OK": "正常"}
    COUPLING_ZH = {"STRONG": "强耦合", "MODERATE": "中等耦合", "WEAK": "弱耦合"}

    # Chinese day names
    DAY_ZH = {
        "Monday": "周一", "Tuesday": "周二", "Wednesday": "周三",
        "Thursday": "周四", "Friday": "周五", "Saturday": "周六", "Sunday": "周日",
    }

    def zh_type(ctype):
        return TYPE_LABELS_ZH.get(ctype, ctype)

    def zh_era(name):
        for en, zh in ERA_NAMES_ZH.items():
            if en in name:
                return name.replace(en, zh).replace("Era", "阶段")
        return name

    lines = []

    # Header
    lines.append(f"# {s['repo']} — 项目故事\n")
    lines.append(f"> {s['total_commits']} 次提交，{s['author_count']} 位贡献者")
    lines.append(f"> {s['first_commit']} → {s['last_commit']}（{s['active_days']} 天）")
    lines.append(f"> {s['total_insertions']:,} 行新增 / {s['total_deletions']:,} 行删除（净增 {s['net_lines']:+,} 行）\n")

    # Velocity
    trend_desc = {
        "accelerating": "开发节奏：**正在加速** — 近期活跃度明显上升。",
        "decelerating": "开发节奏：**正在放缓** — 近期活跃度有所下降。",
        "steady": "开发节奏：**保持稳定** — 整体开发速度平稳。",
        "insufficient_data": "开发节奏：数据不足，无法判断趋势。",
    }
    lines.append(f"{trend_desc.get(velocity.get('trend', ''), '')}\n")

    # One-paragraph summary
    types = s.get("commit_types", {})
    feat_count = types.get("feat", 0)
    fix_count = types.get("fix", 0)
    refactor_count = types.get("refactor", 0)

    lines.append("---\n")
    lines.append("## 故事概览\n")

    if feat_count > fix_count and feat_count > refactor_count:
        lines.append(f"这是一个以**功能开发**为主的项目 — 共构建了 {feat_count} 个功能，"
                     f"修复了 {fix_count} 个 Bug，期间经历了 {refactor_count} 次重构。\n")
    elif fix_count > feat_count:
        lines.append(f"项目正处于**稳定收敛**阶段 — {fix_count} 次 Bug 修复 vs {feat_count} 个新功能，"
                     f"团队正在集中精力提升稳定性。\n")
    elif refactor_count > feat_count:
        lines.append(f"项目正在**大规模重构** — {refactor_count} 次重构表明正在进行架构优化。\n")
    else:
        lines.append(f"项目涵盖功能开发（{feat_count}）、Bug 修复（{fix_count}）和日常维护，"
                     f"持续了 {s['active_days']} 天。\n")

    # Commit type breakdown
    lines.append("### 提交分类\n")
    lines.append("```")
    total = sum(types.values())
    for ctype, count in sorted(types.items(), key=lambda x: -x[1]):
        pct = count / max(total, 1) * 100
        bar_len = round(pct / 100 * 30)
        label = zh_type(ctype)
        emoji = COMMIT_TYPES.get(ctype, {}).get("emoji", ".")
        lines.append(f"  {emoji} {label:<10} {'█' * bar_len}{'░' * (30 - bar_len)} {count:>4}（{pct:.0f}%）")
    lines.append("```\n")

    # Eras
    if eras:
        lines.append("---\n")
        lines.append("## 项目阶段\n")
        for era in eras:
            lines.append(f"### {zh_era(era['name'])}")
            lines.append(f"**{era['start']} → {era['end']}**（{era['commit_count']} 次提交）\n")

            # Types in this era
            type_summary = era.get("types_summary", {})
            if type_summary:
                parts = []
                for t, c in sorted(type_summary.items(), key=lambda x: -x[1])[:3]:
                    parts.append(f"{zh_type(t)}: {c}")
                lines.append(f"重点: {', '.join(parts)}\n")

            # Key commits
            key = era.get("key_commits", [])
            if key:
                lines.append("关键提交:")
                for kc in key[:3]:
                    lines.append(f"- `{kc['hash']}` {kc['subject']}")
                lines.append("")

    # Milestones
    if milestones:
        REASON_ZH = {
            "Release": "版本发布",
            "Project initialized": "项目初始化",
            "Architectural change": "架构变更",
        }
        lines.append("---\n")
        lines.append("## 里程碑\n")
        lines.append("| 日期 | 提交 | 内容 | 原因 |")
        lines.append("|------|------|------|------|")
        for m in milestones[:20]:
            reason = m['reason']
            if reason in REASON_ZH:
                reason = REASON_ZH[reason]
            elif reason.startswith("Major change"):
                reason = reason.replace("Major change", "重大变更")
            elif reason.startswith("Wide impact"):
                reason = reason.replace("Wide impact", "大范围影响")
            lines.append(f"| {m['date']} | `{m['hash']}` | {m['subject'][:50]} | {reason} |")
        lines.append("")

    # Hotspots
    if hotspots:
        lines.append("---\n")
        lines.append("## 高风险文件（改得越多 = 越容易出问题）\n")
        lines.append("| 文件 | 提交次数 | 作者数 | 变更量 | 风险 |")
        lines.append("|------|----------|--------|--------|------|")
        for h in hotspots[:15]:
            risk = RISK_ZH.get(h['risk'], h['risk'])
            lines.append(f"| `{h['file'][:60]}` | {h['commits']} | {h['authors']} | {h['churn']:,} | {risk} |")
        lines.append("")

    # Temporal Coupling
    if coupling:
        lines.append("---\n")
        lines.append("## 时间耦合（总是一起改动的文件）\n")
        lines.append("以下文件存在架构耦合 — 改一个，另一个通常也得改:\n")
        lines.append("| 文件 A | 文件 B | 共同变更次数 | 耦合程度 |")
        lines.append("|--------|--------|--------------|----------|")
        for tc in coupling[:10]:
            cp = COUPLING_ZH.get(tc['coupling'], tc['coupling'])
            lines.append(f"| `{tc['file_a'][:40]}` | `{tc['file_b'][:40]}` | {tc['co_changes']} | {cp} |")
        lines.append("")

    # Timeline visualization
    if milestones and len(milestones) > 1:
        lines.append("---\n")
        lines.append("## 时间线\n")
        lines.append("```")
        for m in milestones[:15]:
            lines.append(f"  {m['date']}  {'─' * 3}●  {m['subject'][:50]}")
            reason = m['reason']
            if reason == "Release":
                reason = "版本发布"
            elif reason == "Project initialized":
                reason = "项目初始化"
            elif reason == "Architectural change":
                reason = "架构变更"
            elif reason.startswith("Major change"):
                reason = reason.replace("Major change", "重大变更")
            elif reason.startswith("Wide impact"):
                reason = reason.replace("Wide impact", "大范围影响")
            lines.append(f"              {'':>3}   [{reason}]")
        lines.append("```\n")

    # Bus Factor
    bus = analysis.get("bus_factor", [])
    critical_dirs = [b for b in bus if b["risk"] in ("CRITICAL", "HIGH")]
    if critical_dirs:
        lines.append("---\n")
        lines.append("## 巴士因子警告\n")
        lines.append("以下目录的知识高度集中在少数人手中:\n")
        lines.append("| 目录 | 巴士因子 | 核心贡献者 | 占比 | 风险 |")
        lines.append("|------|----------|------------|------|------|")
        for b in critical_dirs:
            risk = RISK_ZH.get(b['risk'], b['risk'])
            lines.append(f"| `{b['directory']}` | {b['bus_factor']} | {b['top_contributor']} | {b['top_contributor_pct']}% | **{risk}** |")
        lines.append("\n> 巴士因子 = 1 意味着只有一个人掌握该模块的知识。如果此人离开，该模块将面临风险。\n")

    # Contributors
    if contributors:
        lines.append("---\n")
        lines.append("## 贡献者\n")
        for p in contributors[:10]:
            lines.append(f"### {p['author']}")
            lines.append(f"- **{p['commits']} 次提交**（{p['first_commit']} → {p['last_commit']}）")
            lines.append(f"- {p['insertions']:,} 行新增 / {p['deletions']:,} 行删除（净增 {p['net_lines']:+,} 行）")
            lines.append(f"- 活跃 {p['active_days']} 天")
            lines.append(f"- 专注领域: {p['focus']}")
            lines.append(f"- 主要目录: {', '.join(p['top_areas'])}")
            lines.append("")

    # Activity
    if activity:
        lines.append("---\n")
        lines.append("## 活跃度分析\n")

        busiest_day = activity.get("busiest_day")
        if busiest_day:
            day_zh = DAY_ZH.get(busiest_day[0], busiest_day[0])
            lines.append(f"最活跃的一天: **{day_zh}**（{busiest_day[1]} 次提交）")

        busiest_week = activity.get("busiest_week")
        if busiest_week:
            lines.append(f"最忙碌的一周: **{busiest_week[0]}**（{busiest_week[1]} 次提交）")

        # Day-of-week chart
        dow = activity.get("day_of_week", {})
        if dow:
            lines.append("\n```")
            max_dow = max(dow.values()) if dow else 1
            day_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
            for day in day_order:
                count = dow.get(day, 0)
                bar = "█" * round(count / max(max_dow, 1) * 20)
                day_zh = DAY_ZH.get(day, day[:3])
                lines.append(f"  {day_zh}  {bar} {count}")
            lines.append("```\n")

        # Hour distribution
        hours = activity.get("hour_distribution", {})
        if hours:
            peak_hour = max(hours.items(), key=lambda x: x[1]) if hours else (0, 0)
            lines.append(f"编码高峰时段: **{peak_hour[0]:02d}:00**（{peak_hour[1]} 次提交）\n")

    # Reading guide for new engineers
    lines.append("---\n")
    lines.append("## 新人入职阅读指南\n")
    lines.append("如果你刚加入这个项目，建议按以下顺序了解:\n")

    step = 1
    if milestones:
        init_commits = [m for m in milestones if m["reason"] == "Project initialized"]
        if init_commits:
            lines.append(f"{step}. **阅读初始提交** `{init_commits[0]['hash']}` — 理解项目最初的设计意图")
            step += 1

    if hotspots:
        top_hot = hotspots[0]
        lines.append(f"{step}. **研究热点文件** `{top_hot['file']}` — 被修改了 {top_hot['commits']} 次，"
                     f"这是项目的核心所在")
        step += 1

    if contributors:
        top_author = contributors[0]
        lines.append(f"{step}. **跟读 {top_author['author']} 的提交记录** — "
                     f"{top_author['commits']} 次提交，核心贡献者")
        step += 1

    if eras and len(eras) > 1:
        latest_era = eras[-1]
        lines.append(f"{step}. **当前处于{zh_era(latest_era['name'])}** — 重点关注这个阶段的提交，了解最新方向")

    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Commit-Narrator: Git history → project story")
    parser.add_argument("--repo", default=".", help="Path to git repository (default: current dir)")
    parser.add_argument("--since", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--until", help="End date (YYYY-MM-DD)")
    parser.add_argument("--author", help="Filter by author name")
    parser.add_argument("--path", help="Filter by file path")
    parser.add_argument("--max", type=int, default=5000, help="Max commits to analyze")
    parser.add_argument("--json", dest="json_output", help="Output raw analysis JSON to file")
    parser.add_argument("--output", "-o", help="Output narrative markdown to file")
    args = parser.parse_args()

    # Verify it's a git repo
    check = run_git(["rev-parse", "--is-inside-work-tree"], args.repo)
    if "true" not in check:
        print(f"[!] 不是 Git 仓库: {args.repo}", file=sys.stderr)
        sys.exit(1)

    print(f"[*] 正在分析 {os.path.abspath(args.repo)} 的 Git 历史...")

    repo_info = get_repo_info(args.repo)
    commits = get_commits(
        cwd=args.repo,
        since=args.since,
        until=args.until,
        author=args.author,
        path=args.path,
        max_count=args.max,
    )

    if not commits:
        print("[!] 未找到符合条件的提交记录。", file=sys.stderr)
        sys.exit(1)

    print(f"[*] 找到 {len(commits)} 条提交记录，正在分析...")

    analyzer = CommitAnalyzer(commits, repo_info)
    analysis = analyzer.run_full_analysis()

    # JSON output
    if args.json_output:
        with open(args.json_output, "w", encoding="utf-8") as f:
            json.dump(analysis, f, indent=2, ensure_ascii=False, default=str)
        print(f"[+] 分析数据已保存至 {args.json_output}")

    # Narrative output
    narrative = generate_narrative(analysis)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(narrative)
        print(f"[+] 项目叙事已保存至 {args.output}")
    else:
        print(narrative)

    # Summary
    s = analysis["summary"]
    print(f"\n[+] {s['repo']}: {s['total_commits']} 次提交，"
          f"{s['author_count']} 位贡献者，"
          f"{len(analysis['milestones'])} 个里程碑，"
          f"{len(analysis['hotspots'])} 个热点文件")


if __name__ == "__main__":
    main()
