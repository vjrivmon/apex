#!/usr/bin/env python3
"""Aggregate APEX usage metrics for the ASE 2026 Tools & Datasets paper.

Reproducible evidence-of-utility numbers. Reads:
  - the apex repo itself (tests, MCP tools, skills, hooks, LOC, commits)
  - every ~/RoadToDevOps/*/.apex/context.db (per-project substrate)
  - ~/RoadToDevOps/apex-hub/data/hub.db (cross-project aggregation)

Usage:
    .venv/bin/python3 scripts/paper_metrics.py            # human summary
    .venv/bin/python3 scripts/paper_metrics.py --json     # machine readable

This script is intentionally read-only and best-effort: missing tables or
databases degrade to zero rather than crash.
"""
from __future__ import annotations

import glob
import json
import os
import re
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROADTODEVOPS = os.path.dirname(REPO)
HUB_DB = os.path.expanduser("~/RoadToDevOps/apex-hub/data/hub.db")

# Projects that are scaffolding/sandboxes rather than "real" work.
SANDBOX_PROJECTS = {"test-apex"}


def _count_lines(paths: list[str]) -> int:
    total = 0
    for p in paths:
        try:
            with open(p, "r", encoding="utf-8", errors="replace") as fh:
                total += sum(1 for _ in fh)
        except OSError:
            pass
    return total


def repo_metrics() -> dict:
    import sqlite3

    py = lambda *parts: os.path.join(REPO, *parts)
    lib_files = glob.glob(py("lib", "**", "*.py"), recursive=True)
    test_files = glob.glob(py("tests", "test_*.py"))
    skills = [d for d in glob.glob(py("skills", "*")) if os.path.isdir(d)]
    hooks = [f for f in glob.glob(py(".claude", "hooks", "*.py"))]

    # MCP tool count: distinct apex_* identifiers referenced as tool names.
    tools = set()
    for srv in glob.glob(py("mcp", "*.py")):
        try:
            txt = open(srv, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        for m in re.finditer(r"\bapex_[a-z0-9_]+\b", txt):
            tools.add(m.group(0))
    # keep only names that look like exposed tools (heuristic: appear after name=)
    exposed = set(re.findall(r'name="?(apex_[a-z0-9_]+)"?', "\n".join(
        open(s, encoding="utf-8", errors="replace").read() for s in glob.glob(py("mcp", "*.py"))
    )))
    n_tools = len(exposed) or len(tools)

    # test count via pytest --collect-only (fast); fall back to file count.
    n_tests = 0
    try:
        out = subprocess.run(
            [py(".venv", "bin", "pytest"), "tests/", "--collect-only", "-q"],
            cwd=REPO, env={**os.environ, "PYTHONPATH": py("lib")},
            capture_output=True, text=True, timeout=120,
        ).stdout
        m = re.search(r"(\d+)\s+tests? collected", out)
        if m:
            n_tests = int(m.group(1))
    except Exception:
        pass

    n_commits = 0
    try:
        n_commits = int(subprocess.run(
            ["git", "rev-list", "--count", "HEAD"], cwd=REPO,
            capture_output=True, text=True, timeout=15).stdout.strip())
    except Exception:
        pass

    # context.db schema table count (apex's own db).
    n_tables = 0
    own_db = os.path.join(REPO, ".apex", "context.db")
    if os.path.exists(own_db):
        try:
            c = sqlite3.connect(own_db)
            n_tables = c.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' AND name NOT LIKE '%_fts%' "
                "AND name NOT LIKE '%_config' AND name NOT LIKE '%_content' "
                "AND name NOT LIKE '%_data' AND name NOT LIKE '%_docsize' "
                "AND name NOT LIKE '%_idx'").fetchone()[0]
            c.close()
        except Exception:
            pass

    return {
        "tests": n_tests,
        "mcp_tools": n_tools,
        "skills": len(skills),
        "hooks": len(hooks),
        "lib_loc": _count_lines(lib_files),
        "lib_modules": len(lib_files),
        "commits": n_commits,
        "context_db_tables": n_tables,
    }


def _q(conn, sql: str) -> int:
    try:
        v = conn.execute(sql).fetchone()
        return int(v[0]) if v and v[0] is not None else 0
    except Exception:
        return 0


def usage_metrics() -> dict:
    import sqlite3

    paths = sorted(glob.glob(os.path.join(ROADTODEVOPS, "*", ".apex", "context.db")))
    per_project = []
    for p in paths:
        name = p.split(os.sep + "RoadToDevOps" + os.sep, 1)[1].split(os.sep)[0] \
            if "RoadToDevOps" in p else os.path.basename(os.path.dirname(os.path.dirname(p)))
        try:
            c = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
        except Exception:
            continue
        row = {
            "project": name,
            "decisions": _q(c, "SELECT COUNT(*) FROM decisions"),
            "errors": _q(c, "SELECT COUNT(*) FROM errors"),
            "errors_recurring": _q(c, "SELECT COUNT(*) FROM errors WHERE recurrence_count>=2"),
            "wiki_pages": _q(c, "SELECT COUNT(*) FROM wiki_pages"),
            "components": _q(c, "SELECT COUNT(*) FROM components"),
            "sessions": _q(c, "SELECT COUNT(*) FROM session_starts"),
            "grader_verdicts": _q(c, "SELECT COUNT(*) FROM grader_verdicts"),
            "grader_blocks": _q(c, "SELECT COUNT(*) FROM grader_verdicts WHERE should_block=1"),
            "advisor_advice": _q(c, "SELECT COUNT(*) FROM advisor_advice"),
            "advisor_reviews": _q(c, "SELECT COUNT(*) FROM advisor_reviews"),
            "reasoning_traces": _q(c, "SELECT COUNT(*) FROM reasoning_traces"),
            "role_invocations": _q(c, "SELECT COUNT(*) FROM role_invocations"),
            "skill_handoffs": _q(c, "SELECT COUNT(*) FROM skill_handoffs"),
            "doctor_proposals": _q(c, "SELECT COUNT(*) FROM doctor_proposals"),
        }
        c.close()
        per_project.append(row)

    def total(key):
        return sum(r[key] for r in per_project)

    real = [r for r in per_project
            if r["project"] not in SANDBOX_PROJECTS
            and (r["decisions"] >= 5 or r["wiki_pages"] >= 5)]

    hub = {}
    if os.path.exists(HUB_DB):
        import sqlite3 as _s
        try:
            h = _s.connect(f"file:{HUB_DB}?mode=ro", uri=True)
            for t in ("projects", "decisions", "errors", "components",
                      "phases", "wiki_pages", "live_events", "session_logs",
                      "grader_verdicts"):
                hub[t] = _q(h, f"SELECT COUNT(*) FROM {t}")
            h.close()
        except Exception:
            pass

    return {
        "n_context_dbs": len(per_project),
        "n_real_projects": len(real),
        "real_project_names": sorted(r["project"] for r in real),
        "totals": {k: total(k) for k in (
            "decisions", "errors", "errors_recurring", "wiki_pages",
            "components", "sessions", "grader_verdicts", "grader_blocks",
            "advisor_advice", "advisor_reviews", "reasoning_traces",
            "role_invocations", "skill_handoffs", "doctor_proposals")},
        "hub": hub,
        "per_project": per_project,
    }


def main() -> None:
    data = {"repo": repo_metrics(), "usage": usage_metrics()}
    if "--json" in sys.argv:
        print(json.dumps(data, indent=2))
        return
    r, u = data["repo"], data["usage"]
    print("=== APEX — paper metrics ===")
    print(f"Artifact size:")
    print(f"  tests passing ........ {r['tests']}")
    print(f"  MCP tools ............ {r['mcp_tools']}")
    print(f"  skills ............... {r['skills']}")
    print(f"  hooks ................ {r['hooks']}")
    print(f"  lib/ Python LOC ...... {r['lib_loc']} across {r['lib_modules']} modules")
    print(f"  context.db tables .... {r['context_db_tables']}")
    print(f"  git commits .......... {r['commits']}")
    print()
    print(f"Field use:")
    print(f"  projects with .apex/context.db .. {u['n_context_dbs']}")
    print(f"  projects with sustained activity  {u['n_real_projects']}")
    t = u["totals"]
    print(f"  decisions recorded ............... {t['decisions']}")
    print(f"  errors recorded (recurring) ...... {t['errors']} ({t['errors_recurring']})")
    print(f"  wiki pages ....................... {t['wiki_pages']}")
    print(f"  components ....................... {t['components']}")
    print(f"  grader verdicts (blocking) ....... {t['grader_verdicts']} ({t['grader_blocks']})")
    print(f"  advisor advice cards ............. {t['advisor_advice']}")
    print(f"  reasoning traces ................. {t['reasoning_traces']}")
    print(f"  role invocations ................. {t['role_invocations']}")
    print(f"  doctor proposals ................. {t['doctor_proposals']}")
    if u["hub"]:
        h = u["hub"]
        print()
        print(f"Cross-project hub (hub.db):")
        print(f"  projects ......... {h.get('projects', 0)}")
        print(f"  decisions ........ {h.get('decisions', 0)}")
        print(f"  errors ........... {h.get('errors', 0)}")
        print(f"  components ....... {h.get('components', 0)}")
        print(f"  wiki pages ....... {h.get('wiki_pages', 0)}")
        print(f"  live events ...... {h.get('live_events', 0)}")
        print(f"  session logs ..... {h.get('session_logs', 0)}")
    print()
    print("Real projects:", ", ".join(u["real_project_names"]))


if __name__ == "__main__":
    main()
