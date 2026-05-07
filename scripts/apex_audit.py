#!/usr/bin/env python3
"""APEX Audit — instrumenta una sesión Claude Code + /apex y registra TODO.

Pensado para correr en una terminal en background mientras tú ejecutas
`claude --dangerously-skip-permissions` y `/apex` en OTRA terminal sobre el
mismo proyecto. Captura eventos de cinco fuentes y los une en un report
único legible para diagnóstico post-mortem.

Uso:
    python3 apex_audit.py /ruta/al/proyecto
    # Ctrl+C para terminar; deja un resumen final en el report.

Outputs (en cwd):
    apex_audit.jsonl       — append-only, todos los eventos timestamped (UTC)
    apex_audit_report.md   — humano, regenerado cada 5s

Fuentes monitorizadas:
    1. `.apex/context.db`    — snapshot SQL cada 2s (read-only WAL-friendly)
    2. transcript JSONL más reciente del proyecto en ~/.claude/projects/...
       (lee incrementalmente eventos nuevos)
    3. arbol `.apex/` (handoff/, doctor/, skill-proposals/, browser-traces/,
       wiki/synthesis/, security/) — detecta archivos nuevos por mtime
    4. `git log` del proyecto — detecta commits nuevos
    5. fichero `apex_audit.stderr` (opcional) — si rediriges stderr de los
       hooks ahí, lo absorbe línea a línea

Validaciones automáticas que aparecen en el report:
    • Fases ejecutadas EN ORDEN, sin saltos (0→1→2→…→14, con 10.5 antes de 11)
    • Cada fase cerrada tiene grader_verdict; verdicts bloqueantes resaltados
    • Roles invocados coinciden con phase→role mapping (Sprint 12)
    • Doctor invocado al cerrar si frase de cierre detectada (Sprint 13)
    • Handoff escrito si transcript pasa de 40% del context limit (Sprint 9)
    • Hooks disparados (PreToolUse phase-gate, PostToolUse skill-forge-watch,
      UserPromptSubmit context-watch + end-of-day-doctor, SessionStart x2)

Sin dependencias externas: stdlib pura.
"""
from __future__ import annotations

import argparse
import http.server
import json
import os
import queue
import sqlite3
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

POLL_DB_S = 2.0
POLL_TRANSCRIPT_S = 1.0
REPORT_REFRESH_S = 5.0

PHASE_ROLE_MAP = {
    2: "apex-architect", 3: "apex-architect",
    4: "apex-qa",
    5: "apex-implementer", 6: "apex-implementer", 7: "apex-implementer",
    8: "apex-reviewer",
    9: "apex-qa",
    10: "apex-reviewer",
    11: "apex-devops",
}

PHASE_NAMES = {
    0: "socratic", 1: "scope", 2: "design", 3: "spec", 4: "edge-cases",
    5: "scaffold", 6: "skill-build", 7: "swarm-mvp", 8: "review",
    9: "test", 10: "iterate", 105: "security-gate", 11: "deploy",
    12: "monitor", 13: "portfolio", 14: "maintenance",
}


# ── Event log ───────────────────────────────────────────────────────────────

class EventLog:
    """Append a JSONL + agrega en estructura para el report."""

    def __init__(self, jsonl_path: Path) -> None:
        self.jsonl_path = jsonl_path
        self.events: list[dict[str, Any]] = []
        self.start_ts = datetime.now(timezone.utc)
        # bins por categoría
        self.phases_set: list[dict] = []           # apex_set_phase calls
        self.verdicts: list[dict] = []             # apex_grader_evaluate
        self.role_invocations: list[dict] = []
        self.doctor_runs: list[dict] = []
        self.handoffs: list[dict] = []
        self.skill_proposals: list[dict] = []
        self.browser_traces: list[dict] = []
        self.commits: list[dict] = []
        self.hook_calls: list[dict] = []
        self.tool_calls: list[dict] = []
        self.errors: list[dict] = []
        # contexto extra para el frontend
        self.project_root: Path | None = None
        # fan-out SSE: cada suscriptor recibe una cola con eventos nuevos
        self._subscribers: list[queue.Queue] = []
        self._lock = threading.Lock()

    def subscribe(self, max_buffer: int = 1024) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=max_buffer)
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            try:
                self._subscribers.remove(q)
            except ValueError:
                pass

    def emit(self, kind: str, **fields: Any) -> None:
        evt = {"ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
               "kind": kind, **fields}
        self.events.append(evt)
        # bins
        if kind == "phase_set":
            self.phases_set.append(evt)
        elif kind == "grader_verdict":
            self.verdicts.append(evt)
        elif kind == "role_invocation":
            self.role_invocations.append(evt)
        elif kind == "doctor_run":
            self.doctor_runs.append(evt)
        elif kind == "handoff_written":
            self.handoffs.append(evt)
        elif kind == "skill_proposal_new":
            self.skill_proposals.append(evt)
        elif kind == "browser_trace_new":
            self.browser_traces.append(evt)
        elif kind == "git_commit":
            self.commits.append(evt)
        elif kind == "hook_fired":
            self.hook_calls.append(evt)
        elif kind == "tool_call":
            self.tool_calls.append(evt)
        elif kind == "error":
            self.errors.append(evt)
        # persist
        try:
            with self.jsonl_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(evt, ensure_ascii=False) + "\n")
        except OSError:
            pass
        # fan-out a suscriptores SSE (no bloqueante: si una cola está
        # llena, descartamos para ese cliente — el snapshot inicial lo
        # rehidratará en la siguiente reconexión)
        with self._lock:
            subs = list(self._subscribers)
        for q in subs:
            try:
                q.put_nowait(evt)
            except queue.Full:
                pass


# ── Sources ────────────────────────────────────────────────────────────────

class ContextDBSnapshotter:
    """Polling de tablas relevantes para detectar inserts nuevos."""

    def __init__(self, db_path: Path, log: EventLog) -> None:
        self.db_path = db_path
        self.log = log
        self.last_seen_ids: dict[str, int] = {
            "phases": 0, "grader_verdicts": 0, "role_invocations": 0,
            "doctor_runs": 0, "tool_call_log": 0, "errors": 0,
            "decisions": 0, "next_steps": 0, "session_starts_seen": 0,
        }

    def _ro(self) -> sqlite3.Connection | None:
        if not self.db_path.exists():
            return None
        try:
            return sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True, timeout=2.0)
        except sqlite3.Error:
            return None

    def tick(self) -> None:
        conn = self._ro()
        if conn is None:
            return
        try:
            for tbl, query, handler in (
                ("phases",
                 "SELECT id, phase, status, started_at, completed_at FROM phases WHERE id>? ORDER BY id",
                 self._on_phase),
                ("grader_verdicts",
                 "SELECT id, phase, quality, issues, should_block, reasoning, created_at "
                 "FROM grader_verdicts WHERE id>? ORDER BY id",
                 self._on_verdict),
                ("role_invocations",
                 "SELECT id, role, phase, fired_at, status FROM role_invocations WHERE id>? ORDER BY id",
                 self._on_role),
                ("doctor_runs",
                 "SELECT id, started_at, finished_at, trigger, status, proposals_count "
                 "FROM doctor_runs WHERE id>? ORDER BY id",
                 self._on_doctor),
                ("tool_call_log",
                 "SELECT id, tool, called_at FROM tool_call_log WHERE id>? ORDER BY id",
                 self._on_tool_call),
                ("errors",
                 "SELECT id, source, phase, description, severity, recurrence_count "
                 "FROM errors WHERE id>? ORDER BY id",
                 self._on_error),
                ("decisions",
                 "SELECT id, phase, title, rationale, created_at FROM decisions WHERE id>? ORDER BY id",
                 self._on_decision),
            ):
                try:
                    last = self.last_seen_ids[tbl]
                    rows = conn.execute(query, (last,)).fetchall()
                    for row in rows:
                        handler(row)
                        self.last_seen_ids[tbl] = max(self.last_seen_ids[tbl], int(row[0]))
                except sqlite3.OperationalError as e:
                    self.log.emit("error", source=f"db.{tbl}", msg=str(e))
        finally:
            conn.close()

    def _on_phase(self, row: tuple) -> None:
        rid, phase, status, started, completed = row
        self.log.emit("phase_set", phase=phase, status=status,
                       started_at=started, completed_at=completed, row_id=rid)

    def _on_verdict(self, row: tuple) -> None:
        rid, phase, quality, issues, should_block, reasoning, created = row
        try:
            issues_list = json.loads(issues or "[]")
        except json.JSONDecodeError:
            issues_list = []
        self.log.emit("grader_verdict", phase=phase, quality=quality,
                       issues=issues_list, blocked=bool(should_block),
                       reasoning=(reasoning or "")[:240], created_at=created,
                       row_id=rid)

    def _on_role(self, row: tuple) -> None:
        rid, role, phase, fired, status = row
        self.log.emit("role_invocation", role=role, phase=phase,
                       fired_at=fired, status=status, row_id=rid)

    def _on_doctor(self, row: tuple) -> None:
        rid, started, finished, trigger, status, n = row
        self.log.emit("doctor_run", started_at=started, finished_at=finished,
                       trigger=trigger, status=status, proposals=n, row_id=rid)

    def _on_tool_call(self, row: tuple) -> None:
        rid, tool, called = row
        self.log.emit("tool_call", tool=tool, called_at=called, row_id=rid)

    def _on_error(self, row: tuple) -> None:
        rid, source, phase, desc, severity, recurrence = row
        self.log.emit("error", source=source, phase=phase, severity=severity,
                       recurrence=recurrence, msg=(desc or "")[:240], row_id=rid)

    def _on_decision(self, row: tuple) -> None:
        rid, phase, title, rationale, created = row
        self.log.emit("decision", phase=phase, title=(title or "")[:120],
                       rationale=(rationale or "")[:240], created_at=created,
                       row_id=rid)


class TranscriptTailer:
    """Lee incrementalmente el JSONL más reciente del proyecto en
    ~/.claude/projects/<slug>/. Captura tool_use, hooks y errores."""

    def __init__(self, project_root: Path, log: EventLog) -> None:
        self.project_root = project_root
        self.log = log
        slug = "-" + str(project_root.resolve()).strip("/").replace("/", "-")
        self.proj_dir = Path.home() / ".claude" / "projects" / slug
        self.current_file: Path | None = None
        self.offset = 0

    def _pick_latest(self) -> Path | None:
        if not self.proj_dir.exists():
            return None
        files = sorted(self.proj_dir.glob("*.jsonl"),
                        key=lambda p: p.stat().st_mtime, reverse=True)
        return files[0] if files else None

    def tick(self) -> None:
        latest = self._pick_latest()
        if latest is None:
            return
        if latest != self.current_file:
            self.current_file = latest
            self.offset = 0
            self.log.emit("transcript_switch", file=str(latest))
        try:
            with latest.open("rb") as f:
                f.seek(self.offset)
                chunk = f.read()
                self.offset = f.tell()
        except OSError:
            return
        if not chunk:
            return
        for raw in chunk.splitlines():
            if not raw.strip():
                continue
            try:
                evt = json.loads(raw)
            except json.JSONDecodeError:
                continue
            self._process(evt)

    def _process(self, evt: dict) -> None:
        t = evt.get("type")
        if t == "assistant":
            for c in evt.get("message", {}).get("content", []) or []:
                if c.get("type") == "tool_use":
                    name = c.get("name", "")
                    if name.startswith("mcp__apex__") or name in (
                        "Bash", "Edit", "Write", "Read", "Task",
                    ):
                        self.log.emit("transcript_tool_use", tool=name,
                                       ts=evt.get("timestamp"))
        elif t == "user":
            content = evt.get("message", {}).get("content", [])
            if isinstance(content, list):
                for c in content:
                    if c.get("type") == "tool_result" and c.get("is_error"):
                        out = str(c.get("content", ""))[:240]
                        self.log.emit("error", source="tool_result", msg=out)
        elif t == "attachment":
            attach = evt.get("attachment", {})
            if attach.get("type") == "hook_success":
                self.log.emit("hook_fired", hook=attach.get("hookName", ""),
                               ts=evt.get("timestamp"))
        elif t == "system":
            sub = evt.get("subtype", "")
            if sub == "stop_hook_summary":
                self.log.emit("stop_hook_summary", count=evt.get("hookCount", 0))
            elif sub == "turn_duration":
                self.log.emit("turn_duration", ms=evt.get("durationMs", 0))


class FilesystemWatcher:
    """Detecta archivos nuevos en directorios clave de .apex/."""

    def __init__(self, project_root: Path, log: EventLog) -> None:
        self.project_root = project_root
        self.log = log
        self.seen: dict[str, set[str]] = {}

    def _watch(self, subdir: str, kind: str, glob: str = "*") -> None:
        d = self.project_root / ".apex" / subdir
        if not d.exists():
            return
        seen = self.seen.setdefault(subdir, set())
        for f in d.glob(glob):
            if f.name in seen:
                continue
            seen.add(f.name)
            try:
                size = f.stat().st_size
            except OSError:
                size = 0
            self.log.emit(kind, name=f.name, path=str(f), size=size)

    def tick(self) -> None:
        self._watch("handoff", "handoff_written", "*.md")
        self._watch("doctor", "doctor_report_new", "*.md")
        self._watch("skill-proposals", "skill_proposal_new", "*.md")
        self._watch("browser-traces", "browser_trace_new", "*")
        self._watch("wiki/synthesis", "synthesis_new", "*.md")
        self._watch("security", "security_report_new", "*.md")


class GitWatcher:
    """Lee `git log --oneline` incrementalmente."""

    def __init__(self, project_root: Path, log: EventLog) -> None:
        self.project_root = project_root
        self.log = log
        self.seen_shas: set[str] = set()
        self._initial_sweep()

    def _initial_sweep(self) -> None:
        for sha, _msg in self._oneline(limit=20):
            self.seen_shas.add(sha)

    def _oneline(self, limit: int = 30) -> list[tuple[str, str]]:
        try:
            out = subprocess.check_output(
                ["git", "-C", str(self.project_root), "log", "--oneline", f"-n{limit}"],
                stderr=subprocess.DEVNULL, timeout=3,
            ).decode().splitlines()
        except (subprocess.SubprocessError, OSError):
            return []
        result = []
        for line in out:
            parts = line.split(" ", 1)
            if len(parts) == 2:
                result.append((parts[0], parts[1]))
        return result

    def tick(self) -> None:
        for sha, msg in self._oneline(limit=30):
            if sha in self.seen_shas:
                continue
            self.seen_shas.add(sha)
            self.log.emit("git_commit", sha=sha, msg=msg)


class StderrIngest:
    """Si redirigís stderr de los hooks a apex_audit.stderr, lo absorbemos."""

    def __init__(self, log: EventLog) -> None:
        self.log = log
        self.path = Path("apex_audit.stderr")
        self.offset = 0

    def tick(self) -> None:
        if not self.path.exists():
            return
        try:
            with self.path.open("rb") as f:
                f.seek(self.offset)
                chunk = f.read().decode("utf-8", "replace")
                self.offset = f.tell()
        except OSError:
            return
        for line in chunk.splitlines():
            line = line.strip()
            if not line:
                continue
            kind = "hook_stderr"
            if "[skill-forge]" in line:
                kind = "skill_forge_stderr"
            elif "[apex-doctor]" in line:
                kind = "apex_doctor_stderr"
            self.log.emit(kind, line=line[:400])


# ── Validators ─────────────────────────────────────────────────────────────

def validate_phase_order(log: EventLog) -> list[str]:
    """Comprueba que las fases se ejecutaron en orden estricto."""
    issues: list[str] = []
    phases = [int(p["phase"]) for p in log.phases_set if p.get("phase") is not None]
    if not phases:
        return ["Sin fases registradas todavía."]
    expected_progression = []
    last = -1
    for p in phases:
        if p < last:
            issues.append(f"Fase {p} aparece DESPUÉS de fase {last} (regresión).")
        if p > last + 1 and p != 105:  # 105 = 10.5
            if not (last == 10 and p == 11) or 105 in phases[:phases.index(p)]:
                issues.append(f"Salto de fase: {last} → {p} sin pasar por intermedias.")
        last = p
        expected_progression.append(p)
    if 11 in phases and 105 not in phases:
        issues.append("Fase 11 ejecutada SIN pasar por gate 10.5 (security).")
    return issues


def validate_role_invocations(log: EventLog) -> list[str]:
    """Comprueba que cada fase con rol asociado lo invocó."""
    issues = []
    invoked_by_phase: dict[int, set[str]] = {}
    for inv in log.role_invocations:
        try:
            invoked_by_phase.setdefault(int(inv["phase"]), set()).add(inv["role"])
        except (TypeError, ValueError):
            continue
    for phase_evt in log.phases_set:
        try:
            ph = int(phase_evt["phase"])
        except (TypeError, ValueError):
            continue
        if phase_evt.get("status") not in ("done", "in_progress"):
            continue
        expected = PHASE_ROLE_MAP.get(ph)
        if expected and expected not in invoked_by_phase.get(ph, set()):
            issues.append(f"Fase {ph} ({PHASE_NAMES.get(ph,'?')}) no invocó rol esperado: {expected}.")
    return issues


def validate_grader_blocking(log: EventLog) -> list[str]:
    """Resalta verdicts que bloquearon."""
    return [
        f"GRADER bloqueó fase {v['phase']} (q{v.get('quality','?')}/4): {v['issues']} — {v.get('reasoning','')[:120]}"
        for v in log.verdicts if v.get("blocked")
    ]


def validate_doctor(log: EventLog) -> list[str]:
    """Verifica que el doctor corrió al menos 1 vez."""
    if not log.doctor_runs:
        return ["Apex-doctor NO se ha ejecutado en esta sesión."]
    return [
        f"Doctor #{r['row_id']} trigger={r['trigger']} status={r['status']} props={r['proposals']}"
        for r in log.doctor_runs
    ]


# ── Report rendering ───────────────────────────────────────────────────────

def render_report(log: EventLog, project_root: Path) -> str:
    now = datetime.now(timezone.utc)
    elapsed = now - log.start_ts
    lines: list[str] = []
    lines.append(f"# APEX Audit — `{project_root.name}`")
    lines.append("")
    lines.append(f"- Inicio: `{log.start_ts.isoformat(timespec='seconds')}`")
    lines.append(f"- Última actualización: `{now.isoformat(timespec='seconds')}` "
                  f"(elapsed {int(elapsed.total_seconds())}s)")
    lines.append(f"- Eventos totales: **{len(log.events)}**")
    lines.append(f"- JSONL: `apex_audit.jsonl`")
    lines.append("")

    # Fases
    lines.append("## Fases ejecutadas")
    if log.phases_set:
        lines.append("")
        lines.append("| # | fase | nombre | status | inicio | fin |")
        lines.append("|---|------|--------|--------|--------|-----|")
        for p in log.phases_set:
            ph = p.get("phase", "?")
            name = PHASE_NAMES.get(int(ph) if str(ph).isdigit() else 0, "?")
            lines.append(f"| {p['row_id']} | {ph} | {name} | "
                          f"{p.get('status','?')} | {p.get('started_at','')} | "
                          f"{p.get('completed_at','') or '_(in progress)_'} |")
    else:
        lines.append("\n_(sin fases registradas)_")
    lines.append("")

    # Validaciones
    lines.append("## Sanity checks")
    lines.append("")
    for title, fn in (("Orden de fases", validate_phase_order),
                       ("Roles invocados por fase", validate_role_invocations),
                       ("Grader bloqueando", validate_grader_blocking),
                       ("Doctor runs", validate_doctor)):
        lines.append(f"### {title}")
        results = fn(log)
        if not results:
            lines.append("- OK")
        else:
            for r in results:
                lines.append(f"- {r}")
        lines.append("")

    # Verdicts del grader
    lines.append("## Grader verdicts")
    if log.verdicts:
        for v in log.verdicts:
            mark = "BLOQUEÓ" if v.get("blocked") else "ok"
            lines.append(f"- fase {v['phase']} q{v.get('quality','?')}/4 [{mark}] "
                          f"issues={v.get('issues')} — {v.get('reasoning','')[:120]}")
    else:
        lines.append("\n_(sin verdicts)_")
    lines.append("")

    # Roles
    lines.append("## Roles invocados")
    if log.role_invocations:
        for r in log.role_invocations:
            lines.append(f"- fase {r['phase']} → `{r['role']}` ({r.get('status','?')}) @ {r.get('fired_at','')}")
    else:
        lines.append("\n_(sin invocaciones)_")
    lines.append("")

    # Hooks fired
    lines.append("## Hooks disparados")
    if log.hook_calls:
        from collections import Counter
        c = Counter(h.get("hook", "?") for h in log.hook_calls)
        for hook, n in c.most_common():
            lines.append(f"- `{hook}`: {n}")
    else:
        lines.append("\n_(ninguno)_")
    lines.append("")

    # Doctor
    lines.append("## Doctor runs")
    if log.doctor_runs:
        for r in log.doctor_runs:
            lines.append(f"- #{r['row_id']} trigger=`{r['trigger']}` status={r['status']} "
                          f"proposals={r['proposals']} ({r.get('started_at','')})")
    else:
        lines.append("\n_(sin runs del doctor)_")
    lines.append("")

    # Handoffs / proposals / traces / commits
    for title, items, fmt in (
        ("Handoffs escritos", log.handoffs, lambda x: f"- `{x['name']}` ({x.get('size',0)} bytes)"),
        ("Skill-forge proposals", log.skill_proposals, lambda x: f"- `{x['name']}`"),
        ("Browser traces", log.browser_traces, lambda x: f"- `{x['name']}`"),
        ("Commits durante la sesión", log.commits, lambda x: f"- `{x['sha']}` {x['msg']}"),
    ):
        lines.append(f"## {title}")
        if items:
            for it in items:
                lines.append(fmt(it))
        else:
            lines.append("\n_(ninguno)_")
        lines.append("")

    # Errores
    lines.append("## Errores capturados")
    if log.errors:
        for e in log.errors[-20:]:
            lines.append(f"- [{e.get('source','?')}] {e.get('msg','')}")
    else:
        lines.append("\n_(ninguno)_")
    lines.append("")

    # Tool calls top
    if log.tool_calls:
        from collections import Counter
        c = Counter(t.get("tool", "?") for t in log.tool_calls)
        lines.append("## Top tool calls (de tool_call_log)")
        for tool, n in c.most_common(15):
            lines.append(f"- `{tool}`: {n}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


# ── Web UI (stdlib HTTP + SSE) ─────────────────────────────────────────────

_INDEX_HTML = r"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>APEX Audit — vivo</title>
<style>
  :root {
    --bg: #0d0e11;
    --panel: #15171b;
    --panel-2: #1b1e24;
    --border: #262931;
    --text: #e6e8ec;
    --muted: #8a8f99;
    --accent: #5b8def;
    --ok: #22c55e;
    --warn: #f59e0b;
    --err: #ef4444;
    --info: #38bdf8;
    --violet: #a78bfa;
    --mono: ui-monospace, "JetBrains Mono", "SFMono-Regular", Menlo, Consolas, monospace;
  }
  * { box-sizing: border-box; }
  html, body { height: 100%; }
  body {
    margin: 0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, system-ui, sans-serif;
    background: var(--bg);
    color: var(--text);
    -webkit-font-smoothing: antialiased;
    font-size: 14px;
    line-height: 1.45;
  }
  header {
    position: sticky; top: 0; z-index: 10;
    background: rgba(13, 14, 17, 0.92);
    backdrop-filter: blur(8px);
    border-bottom: 1px solid var(--border);
    padding: 10px 18px;
    display: flex; align-items: center; gap: 14px; flex-wrap: wrap;
  }
  header .title {
    font-weight: 600; letter-spacing: -0.01em; font-size: 15px;
    display: inline-flex; align-items: center; gap: 8px;
  }
  header .title .root { color: var(--muted); font-weight: 400; }
  header .meta { color: var(--muted); font-family: var(--mono); font-size: 12px; }
  header .grow { flex: 1; }
  header button {
    background: transparent;
    border: 1px solid var(--border);
    color: var(--text);
    font: inherit; font-size: 12px;
    padding: 6px 10px; border-radius: 6px;
    cursor: pointer;
    display: inline-flex; align-items: center; gap: 6px;
  }
  header button:hover { background: var(--panel-2); border-color: #353945; }
  header button.toggle.on { background: #1f2a44; border-color: #2c3a5a; color: #c8d6f8; }
  .conn { display: inline-flex; align-items: center; gap: 6px; font-family: var(--mono); font-size: 12px; }
  .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--muted); }
  .dot.ok { background: var(--ok); box-shadow: 0 0 8px rgba(34,197,94,.55); }
  .dot.err { background: var(--err); }
  main {
    display: grid;
    grid-template-columns: minmax(0, 1.4fr) minmax(0, 1fr);
    gap: 14px;
    padding: 14px;
    max-width: 1600px;
    margin: 0 auto;
  }
  @media (max-width: 1100px) { main { grid-template-columns: 1fr; } }
  .card {
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 10px;
    overflow: hidden;
  }
  .card > h2 {
    margin: 0;
    padding: 10px 14px;
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--muted);
    border-bottom: 1px solid var(--border);
    display: flex; align-items: center; gap: 8px;
  }
  .card > h2 .count {
    margin-left: auto; font-family: var(--mono);
    font-size: 11px; color: var(--text);
    background: var(--panel-2); padding: 1px 8px; border-radius: 999px;
    text-transform: none; letter-spacing: 0;
  }
  .filters {
    padding: 10px 14px;
    display: flex; flex-wrap: wrap; gap: 6px;
    border-bottom: 1px solid var(--border);
    background: var(--panel-2);
  }
  .filters input[type=search] {
    flex: 1; min-width: 160px;
    background: var(--bg);
    border: 1px solid var(--border);
    color: var(--text);
    border-radius: 6px;
    padding: 6px 10px;
    font: inherit; font-size: 13px;
  }
  .filters input[type=search]:focus { outline: none; border-color: var(--accent); }
  .chip {
    border: 1px solid var(--border);
    background: transparent;
    color: var(--muted);
    padding: 3px 9px;
    border-radius: 999px;
    font-size: 11px;
    cursor: pointer;
    font-family: var(--mono);
  }
  .chip:hover { color: var(--text); }
  .chip.on { background: #1f2a44; border-color: #2c3a5a; color: #c8d6f8; }
  #timeline {
    overflow-y: auto;
    max-height: calc(100vh - 220px);
    padding: 4px 0;
  }
  .ev {
    display: grid;
    grid-template-columns: 78px 22px 1fr;
    gap: 8px;
    padding: 6px 14px;
    border-bottom: 1px solid #1a1d22;
    font-family: var(--mono);
    font-size: 12px;
    align-items: start;
  }
  .ev:hover { background: #12141a; }
  .ev .ts { color: var(--muted); }
  .ev .icon { display: inline-flex; align-items: center; justify-content: center; opacity: .85; }
  .ev .body { color: var(--text); white-space: pre-wrap; word-break: break-word; }
  .ev .body .kind {
    display: inline-block;
    padding: 1px 7px; border-radius: 4px;
    margin-right: 8px;
    background: #1d2129; color: #aab2c0;
    font-size: 11px;
  }
  .ev.kind-error .icon, .ev.kind-error .body .kind { color: var(--err); }
  .ev.kind-error .body .kind { background: #2a1414; color: #fda4a4; }
  .ev.kind-grader_verdict.blocked .body .kind { background: #2a1414; color: #fda4a4; }
  .ev.kind-grader_verdict.blocked .icon { color: var(--err); }
  .ev.kind-grader_verdict .body .kind { background: #1f2a14; color: #b6e3a0; }
  .ev.kind-phase_set .body .kind { background: #14202a; color: #a0d2f7; }
  .ev.kind-role_invocation .body .kind { background: #211a2e; color: #d2bef5; }
  .ev.kind-doctor_run .body .kind { background: #2a2414; color: #f7d68a; }
  .ev.kind-hook_fired .body .kind, .ev.kind-tool_call .body .kind { background: #14272a; color: #9cd6dc; }
  .ev.kind-git_commit .body .kind { background: #1f2a1f; color: #b9d6b9; }
  .ev.kind-handoff_written .body .kind, .ev.kind-skill_proposal_new .body .kind,
  .ev.kind-browser_trace_new .body .kind, .ev.kind-doctor_report_new .body .kind,
  .ev.kind-synthesis_new .body .kind, .ev.kind-security_report_new .body .kind { background: #1c2330; color: #b3c4e0; }
  .right-stack { display: flex; flex-direction: column; gap: 14px; min-width: 0; }
  .summary { padding: 8px 14px 14px; }
  .summary .row {
    display: flex; align-items: baseline; gap: 8px;
    padding: 4px 0; border-bottom: 1px dashed #1a1d22;
    font-family: var(--mono); font-size: 12px;
  }
  .summary .row:last-child { border-bottom: 0; }
  .summary .row .k { color: var(--muted); flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; }
  .summary .row .v { color: var(--text); font-weight: 600; }
  .summary .empty { color: var(--muted); font-style: italic; padding: 6px 0; }
  .pill {
    display: inline-block; padding: 1px 7px; border-radius: 999px;
    font-size: 10px; margin-left: 6px;
    background: #1d2129; color: #aab2c0;
  }
  .pill.ok { background: #122318; color: #86efac; }
  .pill.warn { background: #2a2414; color: #f7d68a; }
  .pill.err { background: #2a1414; color: #fda4a4; }
  .pill.info { background: #14202a; color: #a0d2f7; }
  .stats {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
    gap: 1px;
    background: var(--border);
  }
  .stat {
    background: var(--panel);
    padding: 10px 12px;
  }
  .stat .label { color: var(--muted); font-size: 10px; text-transform: uppercase; letter-spacing: .08em; }
  .stat .value { font-family: var(--mono); font-size: 18px; margin-top: 4px; }
  .stat .value.err { color: var(--err); }
  .stat .value.warn { color: var(--warn); }
  .stat .value.ok { color: var(--ok); }
  svg.icon { width: 14px; height: 14px; stroke: currentColor; fill: none; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }
  ::-webkit-scrollbar { width: 10px; height: 10px; }
  ::-webkit-scrollbar-track { background: var(--bg); }
  ::-webkit-scrollbar-thumb { background: #2a2e37; border-radius: 5px; }
  ::-webkit-scrollbar-thumb:hover { background: #3a3f4a; }
</style>
</head>
<body>
<header>
  <span class="title">
    <svg class="icon" viewBox="0 0 24 24"><path d="M12 2 4 7v10l8 5 8-5V7z"/><path d="M12 22V12"/><path d="m20 7-8 5L4 7"/></svg>
    APEX Audit <span class="root" id="hdr-root">—</span>
  </span>
  <span class="meta" id="hdr-meta">esperando datos…</span>
  <span class="grow"></span>
  <span class="conn"><span class="dot" id="conn-dot"></span><span id="conn-label">conectando</span></span>
  <button id="btn-autoscroll" class="toggle on" title="Auto-scroll del timeline">
    <svg class="icon" viewBox="0 0 24 24"><path d="M12 5v14"/><path d="m19 12-7 7-7-7"/></svg>
    auto-scroll
  </button>
  <button id="btn-clear" title="Vaciar la vista (no borra el JSONL)">
    <svg class="icon" viewBox="0 0 24 24"><path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="m19 6-1 14H6L5 6"/></svg>
    limpiar
  </button>
  <button id="btn-export" title="Descargar el reporte markdown actual">
    <svg class="icon" viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m7 10 5 5 5-5"/><path d="M12 15V3"/></svg>
    exportar .md
  </button>
</header>

<main>
  <section class="card">
    <h2>
      <svg class="icon" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg>
      Timeline en vivo
      <span class="count" id="tl-count">0</span>
    </h2>
    <div class="filters">
      <input type="search" id="q" placeholder="Filtrar por texto…" />
      <button class="chip on" data-kind="*">todos</button>
      <button class="chip on" data-kind="phase_set">fases</button>
      <button class="chip on" data-kind="grader_verdict">grader</button>
      <button class="chip on" data-kind="role_invocation">roles</button>
      <button class="chip on" data-kind="doctor_run">doctor</button>
      <button class="chip on" data-kind="hook_fired">hooks</button>
      <button class="chip on" data-kind="tool_call">tools</button>
      <button class="chip on" data-kind="error">errores</button>
      <button class="chip on" data-kind="git_commit">commits</button>
      <button class="chip on" data-kind="handoff_written">handoff</button>
      <button class="chip on" data-kind="skill_proposal_new">skills</button>
      <button class="chip on" data-kind="browser_trace_new">browser</button>
    </div>
    <div id="timeline"></div>
  </section>

  <aside class="right-stack">
    <div class="card">
      <h2>
        <svg class="icon" viewBox="0 0 24 24"><path d="M3 3v18h18"/><path d="m7 14 4-4 4 4 5-5"/></svg>
        Resumen
      </h2>
      <div class="stats" id="stats"></div>
    </div>

    <div class="card">
      <h2>
        <svg class="icon" viewBox="0 0 24 24"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
        Sanity checks
      </h2>
      <div class="summary" id="checks"><div class="empty">esperando datos…</div></div>
    </div>

    <div class="card">
      <h2>
        <svg class="icon" viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M9 9h6v6H9z"/></svg>
        Fases
        <span class="count" id="cnt-phases">0</span>
      </h2>
      <div class="summary" id="list-phases"><div class="empty">sin fases registradas</div></div>
    </div>

    <div class="card">
      <h2>
        <svg class="icon" viewBox="0 0 24 24"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><path d="m9 11 3 3L22 4"/></svg>
        Grader verdicts
        <span class="count" id="cnt-verdicts">0</span>
      </h2>
      <div class="summary" id="list-verdicts"><div class="empty">sin verdicts</div></div>
    </div>

    <div class="card">
      <h2>
        <svg class="icon" viewBox="0 0 24 24"><circle cx="9" cy="7" r="4"/><path d="M16 11h6"/><path d="M19 8v6"/><path d="M3 21v-2a4 4 0 0 1 4-4h4a4 4 0 0 1 4 4v2"/></svg>
        Roles invocados
        <span class="count" id="cnt-roles">0</span>
      </h2>
      <div class="summary" id="list-roles"><div class="empty">sin invocaciones</div></div>
    </div>

    <div class="card">
      <h2>
        <svg class="icon" viewBox="0 0 24 24"><path d="M11 2a4 4 0 0 0-4 4v3a3 3 0 0 0 0 6v3a4 4 0 1 0 8 0v-3a3 3 0 0 0 0-6V6a4 4 0 0 0-4-4z"/></svg>
        Apex-doctor
        <span class="count" id="cnt-doctor">0</span>
      </h2>
      <div class="summary" id="list-doctor"><div class="empty">sin runs del doctor</div></div>
    </div>

    <div class="card">
      <h2>
        <svg class="icon" viewBox="0 0 24 24"><path d="M4 17V7a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v10"/><path d="M2 17h20"/><path d="m8 9 3 3-3 3"/><path d="M13 15h4"/></svg>
        Top tool calls
        <span class="count" id="cnt-tools">0</span>
      </h2>
      <div class="summary" id="list-tools"><div class="empty">sin tool calls</div></div>
    </div>

    <div class="card">
      <h2>
        <svg class="icon" viewBox="0 0 24 24"><path d="M12 9v4"/><path d="M12 17h.01"/><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/></svg>
        Errores recientes
        <span class="count" id="cnt-errors">0</span>
      </h2>
      <div class="summary" id="list-errors"><div class="empty">sin errores capturados</div></div>
    </div>

    <div class="card">
      <h2>
        <svg class="icon" viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"/><path d="M3 12h6"/><path d="M15 12h6"/></svg>
        Commits durante la sesión
        <span class="count" id="cnt-commits">0</span>
      </h2>
      <div class="summary" id="list-commits"><div class="empty">sin commits</div></div>
    </div>
  </aside>
</main>

<script>
(() => {
  const PHASE_NAMES = {
    0:"socratic",1:"scope",2:"design",3:"spec",4:"edge-cases",
    5:"scaffold",6:"skill-build",7:"swarm-mvp",8:"review",
    9:"test",10:"iterate",105:"security-gate",11:"deploy",
    12:"monitor",13:"portfolio",14:"maintenance"
  };
  const PHASE_ROLE_MAP = {
    2:"apex-architect",3:"apex-architect",4:"apex-qa",
    5:"apex-implementer",6:"apex-implementer",7:"apex-implementer",
    8:"apex-reviewer",9:"apex-qa",10:"apex-reviewer",11:"apex-devops"
  };
  const MAX_TIMELINE = 800;

  const state = {
    events: [],
    phases: [], verdicts: [], roles: [], doctor: [],
    handoffs: [], skills: [], traces: [], commits: [],
    hooks: [], tools: [], errors: [],
    activeKinds: new Set(["*"]),
    autoScroll: true,
    query: "",
    project: "—",
    startTs: null,
  };

  const $ = (id) => document.getElementById(id);
  const tl = $("timeline");
  const qInp = $("q");

  // Filtros (chips)
  document.querySelectorAll(".chip").forEach((c) => {
    c.addEventListener("click", () => {
      const k = c.dataset.kind;
      if (k === "*") {
        const turnOn = !c.classList.contains("on") || state.activeKinds.size > 1;
        document.querySelectorAll(".chip").forEach((x) => x.classList.toggle("on", turnOn));
        state.activeKinds = new Set(turnOn ? ["*"] : []);
        if (turnOn) {
          document.querySelectorAll(".chip").forEach((x) => state.activeKinds.add(x.dataset.kind));
        }
      } else {
        c.classList.toggle("on");
        if (c.classList.contains("on")) state.activeKinds.add(k);
        else state.activeKinds.delete(k);
        document.querySelector('.chip[data-kind="*"]').classList.remove("on");
        state.activeKinds.delete("*");
      }
      rerenderTimeline();
    });
  });

  qInp.addEventListener("input", () => {
    state.query = qInp.value.toLowerCase();
    rerenderTimeline();
  });

  $("btn-autoscroll").addEventListener("click", (e) => {
    state.autoScroll = !state.autoScroll;
    e.currentTarget.classList.toggle("on", state.autoScroll);
  });
  $("btn-clear").addEventListener("click", () => {
    tl.innerHTML = "";
  });
  $("btn-export").addEventListener("click", async () => {
    const r = await fetch("/report.md");
    const blob = await r.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "apex_audit.md";
    document.body.appendChild(a); a.click(); a.remove();
  });

  function fmtTs(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso.slice(11,19);
    const pad = (n) => String(n).padStart(2, "0");
    return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
  }

  function bodyFor(evt) {
    const k = evt.kind;
    if (k === "phase_set") {
      const ph = evt.phase;
      const name = PHASE_NAMES[ph] || "?";
      return `fase ${ph} (${name}) · ${evt.status || "?"}`;
    }
    if (k === "grader_verdict") {
      const issues = Array.isArray(evt.issues) ? evt.issues.length : 0;
      const tag = evt.blocked ? "BLOQUEÓ" : "ok";
      return `fase ${evt.phase} q${evt.quality}/4 [${tag}] · ${issues} issue(s) · ${(evt.reasoning||"").slice(0,120)}`;
    }
    if (k === "role_invocation") {
      return `fase ${evt.phase} → ${evt.role} (${evt.status})`;
    }
    if (k === "doctor_run") {
      return `#${evt.row_id} trigger=${evt.trigger} status=${evt.status} props=${evt.proposals}`;
    }
    if (k === "hook_fired") return `${evt.hook}`;
    if (k === "tool_call") return `${evt.tool}`;
    if (k === "error") return `[${evt.source||"?"}] ${evt.msg||""}`;
    if (k === "git_commit") return `${evt.sha} · ${evt.msg}`;
    if (k === "handoff_written" || k === "skill_proposal_new" || k === "browser_trace_new"
        || k === "doctor_report_new" || k === "synthesis_new" || k === "security_report_new") {
      return `${evt.name}${evt.size ? " · "+evt.size+" B" : ""}`;
    }
    if (k === "transcript_tool_use") return `transcript: ${evt.tool}`;
    if (k === "transcript_switch") return `transcript: ${evt.file}`;
    if (k === "audit_started") return `audit iniciada (pid ${evt.pid})`;
    if (k === "audit_stopped") return `audit detenida (${evt.reason})`;
    if (k === "stop_hook_summary") return `stop_hook_summary count=${evt.count}`;
    if (k === "turn_duration") return `turn ${(evt.ms/1000).toFixed(1)}s`;
    if (k === "decision") return `decisión: ${evt.title}`;
    if (k === "hook_stderr" || k === "skill_forge_stderr" || k === "apex_doctor_stderr") return evt.line || "";
    // fallback
    const cp = {...evt}; delete cp.ts; delete cp.kind;
    return JSON.stringify(cp);
  }

  function iconFor(kind) {
    const map = {
      phase_set: '<svg class="icon" viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="2"/></svg>',
      grader_verdict: '<svg class="icon" viewBox="0 0 24 24"><path d="m9 11 3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>',
      role_invocation: '<svg class="icon" viewBox="0 0 24 24"><circle cx="12" cy="8" r="4"/><path d="M5 21v-1a7 7 0 0 1 14 0v1"/></svg>',
      doctor_run: '<svg class="icon" viewBox="0 0 24 24"><path d="M11 2a4 4 0 0 0-4 4v3a3 3 0 0 0 0 6v3a4 4 0 1 0 8 0v-3a3 3 0 0 0 0-6V6a4 4 0 0 0-4-4z"/></svg>',
      hook_fired: '<svg class="icon" viewBox="0 0 24 24"><path d="M13 2 3 14h9l-1 8 10-12h-9z"/></svg>',
      tool_call: '<svg class="icon" viewBox="0 0 24 24"><path d="M14.7 6.3a4 4 0 0 1 5 5L9 22 2 22l0-7L13.3 4.7a4 4 0 0 1 1.4 1.6z"/></svg>',
      error: '<svg class="icon" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><path d="M12 8v4"/><path d="M12 16h.01"/></svg>',
      git_commit: '<svg class="icon" viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"/><path d="M3 12h6"/><path d="M15 12h6"/></svg>',
      handoff_written: '<svg class="icon" viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/></svg>',
      skill_proposal_new: '<svg class="icon" viewBox="0 0 24 24"><path d="m12 2 3 7h7l-5.5 4.5L18 21l-6-4-6 4 1.5-7.5L2 9h7z"/></svg>',
      browser_trace_new: '<svg class="icon" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><path d="M2 12h20"/><path d="M12 2a15 15 0 0 1 0 20"/><path d="M12 2a15 15 0 0 0 0 20"/></svg>',
    };
    return map[kind] || '<svg class="icon" viewBox="0 0 24 24"><circle cx="12" cy="12" r="2"/></svg>';
  }

  function eventVisible(evt) {
    if (state.activeKinds.has("*")) {
      // *
    } else if (!state.activeKinds.has(evt.kind)) {
      return false;
    }
    if (state.query) {
      const hay = (evt.kind + " " + bodyFor(evt)).toLowerCase();
      if (!hay.includes(state.query)) return false;
    }
    return true;
  }

  function renderEventNode(evt) {
    const div = document.createElement("div");
    let cls = "ev kind-" + evt.kind;
    if (evt.kind === "grader_verdict" && evt.blocked) cls += " blocked";
    div.className = cls;
    div.innerHTML = `<span class="ts">${fmtTs(evt.ts)}</span>`
      + `<span class="icon">${iconFor(evt.kind)}</span>`
      + `<span class="body"><span class="kind">${evt.kind}</span>${escapeHtml(bodyFor(evt))}</span>`;
    return div;
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"]/g, (c) =>
      ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;"}[c]));
  }

  function appendEvent(evt) {
    if (!eventVisible(evt)) return;
    tl.appendChild(renderEventNode(evt));
    while (tl.children.length > MAX_TIMELINE) tl.removeChild(tl.firstChild);
    if (state.autoScroll) tl.scrollTop = tl.scrollHeight;
  }

  function rerenderTimeline() {
    tl.innerHTML = "";
    let n = 0;
    for (const evt of state.events) {
      if (eventVisible(evt)) {
        tl.appendChild(renderEventNode(evt));
        n++;
        if (n > MAX_TIMELINE) tl.removeChild(tl.firstChild);
      }
    }
    if (state.autoScroll) tl.scrollTop = tl.scrollHeight;
  }

  function bin(evt) {
    const k = evt.kind;
    if (k === "phase_set") state.phases.push(evt);
    else if (k === "grader_verdict") state.verdicts.push(evt);
    else if (k === "role_invocation") state.roles.push(evt);
    else if (k === "doctor_run") state.doctor.push(evt);
    else if (k === "handoff_written") state.handoffs.push(evt);
    else if (k === "skill_proposal_new") state.skills.push(evt);
    else if (k === "browser_trace_new") state.traces.push(evt);
    else if (k === "git_commit") state.commits.push(evt);
    else if (k === "hook_fired") state.hooks.push(evt);
    else if (k === "tool_call") state.tools.push(evt);
    else if (k === "error") state.errors.push(evt);
  }

  function refreshSidebar() {
    $("tl-count").textContent = state.events.length;
    $("cnt-phases").textContent = state.phases.length;
    $("cnt-verdicts").textContent = state.verdicts.length;
    $("cnt-roles").textContent = state.roles.length;
    $("cnt-doctor").textContent = state.doctor.length;
    $("cnt-tools").textContent = state.tools.length;
    $("cnt-errors").textContent = state.errors.length;
    $("cnt-commits").textContent = state.commits.length;

    // Stats compactos
    const blockers = state.verdicts.filter((v) => v.blocked).length;
    const lastPhase = state.phases.length ? state.phases[state.phases.length-1].phase : "—";
    $("stats").innerHTML = `
      <div class="stat"><div class="label">eventos</div><div class="value">${state.events.length}</div></div>
      <div class="stat"><div class="label">fases</div><div class="value">${state.phases.length}</div></div>
      <div class="stat"><div class="label">última fase</div><div class="value">${lastPhase}</div></div>
      <div class="stat"><div class="label">verdicts</div><div class="value">${state.verdicts.length}</div></div>
      <div class="stat"><div class="label">bloqueos</div><div class="value ${blockers ? "err" : "ok"}">${blockers}</div></div>
      <div class="stat"><div class="label">errores</div><div class="value ${state.errors.length ? "err" : "ok"}">${state.errors.length}</div></div>
      <div class="stat"><div class="label">hooks</div><div class="value">${state.hooks.length}</div></div>
      <div class="stat"><div class="label">tools</div><div class="value">${state.tools.length}</div></div>
    `;

    // Sanity checks
    const checks = [];
    const phaseNums = state.phases.map((p) => Number(p.phase)).filter((n) => !Number.isNaN(n));
    if (phaseNums.length) {
      let last = -1, ordered = true;
      for (const n of phaseNums) { if (n < last) { ordered = false; break; } last = n; }
      checks.push(["Fases en orden estricto", ordered ? "ok" : "err",
                   ordered ? "OK" : "REGRESIÓN detectada"]);
      const has11 = phaseNums.includes(11);
      const has105 = phaseNums.includes(105);
      if (has11) checks.push(["Gate 10.5 antes de 11", has105 ? "ok" : "err",
                              has105 ? "OK" : "11 sin pasar 10.5"]);
    } else {
      checks.push(["Fases registradas", "warn", "ninguna todavía"]);
    }
    // roles esperados
    const invByPhase = {};
    state.roles.forEach((r) => {
      const p = Number(r.phase);
      if (!invByPhase[p]) invByPhase[p] = new Set();
      invByPhase[p].add(r.role);
    });
    const roleMisses = [];
    for (const p of phaseNums) {
      const exp = PHASE_ROLE_MAP[p];
      if (exp && !(invByPhase[p] && invByPhase[p].has(exp))) roleMisses.push(`${p}:${exp}`);
    }
    if (phaseNums.length)
      checks.push(["Roles invocados por fase", roleMisses.length ? "warn" : "ok",
                   roleMisses.length ? "faltan: "+roleMisses.join(", ") : "OK"]);
    checks.push(["Apex-doctor ejecutado", state.doctor.length ? "ok" : "warn",
                 state.doctor.length ? `${state.doctor.length} run(s)` : "aún no"]);

    $("checks").innerHTML = checks.map(([k, lvl, v]) =>
      `<div class="row"><span class="k">${escapeHtml(k)}</span><span class="v"><span class="pill ${lvl}">${escapeHtml(v)}</span></span></div>`
    ).join("");

    // Listas
    renderList("list-phases", state.phases, (p) => {
      const name = PHASE_NAMES[Number(p.phase)] || "?";
      const lvl = p.status === "done" ? "ok" : (p.status === "in_progress" ? "info" : "warn");
      return `<div class="row"><span class="k">fase ${p.phase} · ${name}</span><span class="v"><span class="pill ${lvl}">${p.status}</span></span></div>`;
    }, "sin fases registradas");

    renderList("list-verdicts", state.verdicts, (v) => {
      const lvl = v.blocked ? "err" : (v.quality >= 3 ? "ok" : "warn");
      return `<div class="row"><span class="k">fase ${v.phase} · q${v.quality}/4</span><span class="v"><span class="pill ${lvl}">${v.blocked ? "bloqueó" : "ok"}</span></span></div>`;
    }, "sin verdicts");

    renderList("list-roles", state.roles, (r) =>
      `<div class="row"><span class="k">fase ${r.phase} · ${r.role}</span><span class="v"><span class="pill info">${r.status||"?"}</span></span></div>`,
      "sin invocaciones");

    renderList("list-doctor", state.doctor, (r) =>
      `<div class="row"><span class="k">#${r.row_id} · ${r.trigger}</span><span class="v"><span class="pill ${r.status==="done"?"ok":"warn"}">${r.status} · ${r.proposals||0} props</span></span></div>`,
      "sin runs del doctor");

    renderList("list-errors", state.errors.slice(-15).reverse(), (e) =>
      `<div class="row"><span class="k">[${escapeHtml(e.source||"?")}] ${escapeHtml((e.msg||"").slice(0,80))}</span><span class="v"><span class="pill err">err</span></span></div>`,
      "sin errores capturados");

    renderList("list-commits", state.commits.slice(-12).reverse(), (c) =>
      `<div class="row"><span class="k">${c.sha} · ${escapeHtml((c.msg||"").slice(0,60))}</span></div>`,
      "sin commits");

    // top tools
    const counts = {};
    state.tools.forEach((t) => { counts[t.tool] = (counts[t.tool]||0)+1; });
    const top = Object.entries(counts).sort((a,b) => b[1]-a[1]).slice(0,12);
    $("cnt-tools").textContent = state.tools.length;
    $("list-tools").innerHTML = top.length
      ? top.map(([t,n]) => `<div class="row"><span class="k">${escapeHtml(t)}</span><span class="v">${n}</span></div>`).join("")
      : `<div class="empty">sin tool calls</div>`;
  }

  function renderList(id, items, fmt, empty) {
    const el = $(id);
    if (!items || !items.length) { el.innerHTML = `<div class="empty">${empty}</div>`; return; }
    el.innerHTML = items.slice(-20).reverse().map(fmt).join("");
  }

  function ingest(evt) {
    state.events.push(evt);
    bin(evt);
    appendEvent(evt);
    refreshSidebar();
    if (evt.kind === "audit_started" && evt.project) {
      state.project = evt.project;
      $("hdr-root").textContent = evt.project;
    }
    if (!state.startTs && evt.ts) state.startTs = evt.ts;
    updateMeta();
  }

  function updateMeta() {
    const n = state.events.length;
    let elapsed = "—";
    if (state.startTs) {
      const ms = Date.now() - new Date(state.startTs).getTime();
      const s = Math.floor(ms/1000);
      const h = Math.floor(s/3600), m = Math.floor((s%3600)/60), ss = s%60;
      elapsed = `${h}h ${String(m).padStart(2,"0")}m ${String(ss).padStart(2,"0")}s`;
    }
    $("hdr-meta").textContent = `${n} evento(s) · elapsed ${elapsed}`;
  }
  setInterval(updateMeta, 1000);

  async function loadSnapshot() {
    try {
      const r = await fetch("/snapshot.json");
      const data = await r.json();
      if (data.project_root) {
        state.project = data.project_root;
        $("hdr-root").textContent = data.project_root;
      }
      if (data.start_ts) state.startTs = data.start_ts;
      (data.events || []).forEach(ingest);
    } catch (e) {
      console.error("snapshot fallo:", e);
    }
  }

  function connectStream() {
    const dot = $("conn-dot");
    const lab = $("conn-label");
    dot.className = "dot"; lab.textContent = "conectando";
    const es = new EventSource("/stream");
    es.onopen = () => { dot.className = "dot ok"; lab.textContent = "en vivo"; };
    es.onerror = () => { dot.className = "dot err"; lab.textContent = "reconectando"; };
    es.onmessage = (e) => {
      try { ingest(JSON.parse(e.data)); }
      catch (err) { console.warn("parse:", err); }
    };
  }

  loadSnapshot().then(connectStream);
})();
</script>
</body>
</html>
"""


class _AuditServer(http.server.ThreadingHTTPServer):
    """ThreadingHTTPServer con referencias a EventLog y project_root."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], handler: type,
                  event_log: EventLog, project_root: Path) -> None:
        super().__init__(address, handler)
        self.event_log = event_log
        self.project_root = project_root


class _AuditHTTPHandler(http.server.BaseHTTPRequestHandler):
    """Sirve la UI vanilla y el stream SSE leyendo del EventLog."""

    server: _AuditServer  # type: ignore[assignment]

    # Silenciar el log por defecto de BaseHTTPRequestHandler (contamina stderr)
    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: D401
        return

    def _set_headers(self, status: int, content_type: str,
                       extra: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        if extra:
            for k, v in extra.items():
                self.send_header(k, v)
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        try:
            if path == "/" or path == "/index.html":
                body = _INDEX_HTML.encode("utf-8")
                self._set_headers(200, "text/html; charset=utf-8",
                                    {"Content-Length": str(len(body)),
                                     "Cache-Control": "no-cache"})
                self.wfile.write(body)
                return

            if path == "/health":
                body = b'{"status":"ok"}'
                self._set_headers(200, "application/json",
                                    {"Content-Length": str(len(body))})
                self.wfile.write(body)
                return

            if path == "/snapshot.json":
                log = self.server.event_log
                payload = {
                    "project_root": str(self.server.project_root),
                    "start_ts": log.start_ts.isoformat(timespec="milliseconds"),
                    "events": list(log.events),
                }
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self._set_headers(200, "application/json; charset=utf-8",
                                    {"Content-Length": str(len(body)),
                                     "Cache-Control": "no-cache"})
                self.wfile.write(body)
                return

            if path == "/report.md":
                md = render_report(self.server.event_log, self.server.project_root)
                body = md.encode("utf-8")
                self._set_headers(200, "text/markdown; charset=utf-8",
                                    {"Content-Length": str(len(body)),
                                     "Content-Disposition":
                                       "attachment; filename=apex_audit.md",
                                     "Cache-Control": "no-cache"})
                self.wfile.write(body)
                return

            if path == "/stream":
                self._stream_sse()
                return

            self._set_headers(404, "text/plain", {"Content-Length": "9"})
            self.wfile.write(b"not found")
        except (BrokenPipeError, ConnectionResetError):
            return

    def _stream_sse(self) -> None:
        log = self.server.event_log
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        q = log.subscribe()
        last_heartbeat = time.monotonic()
        try:
            # comentario inicial para abrir el canal en el navegador
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
            while True:
                try:
                    evt = q.get(timeout=1.0)
                except queue.Empty:
                    if time.monotonic() - last_heartbeat > 15:
                        self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
                        last_heartbeat = time.monotonic()
                    continue
                payload = json.dumps(evt, ensure_ascii=False)
                self.wfile.write(b"data: " + payload.encode("utf-8") + b"\n\n")
                self.wfile.flush()
                last_heartbeat = time.monotonic()
        except (BrokenPipeError, ConnectionResetError, OSError):
            return
        finally:
            log.unsubscribe(q)


def _start_web_server(log: EventLog, project_root: Path,
                        port: int, open_browser: bool) -> _AuditServer:
    server = _AuditServer(("127.0.0.1", port), _AuditHTTPHandler, log, project_root)
    th = threading.Thread(target=server.serve_forever,
                           name="apex-audit-web", daemon=True)
    th.start()
    if open_browser:
        url = f"http://127.0.0.1:{port}/"
        threading.Timer(0.7, lambda: webbrowser.open(url)).start()
    return server


# ── Main loop ──────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="APEX session auditor.")
    parser.add_argument("project_root", type=Path,
                         help="Raíz del proyecto a auditar (con .apex/ dentro).")
    parser.add_argument("--out-dir", type=Path, default=Path.cwd(),
                         help="Dónde escribir jsonl + report.md (default: cwd).")
    parser.add_argument("--serve", nargs="?", const=8765, type=int, default=None,
                         metavar="PORT",
                         help="Arranca un servidor HTTP+SSE local con UI vivo. "
                              "Default port 8765 si se pasa --serve sin valor.")
    parser.add_argument("--no-browser", action="store_true",
                         help="Con --serve, no abre el navegador automáticamente.")
    args = parser.parse_args()

    project_root = args.project_root.resolve()
    if not (project_root / ".apex").exists():
        print(f"[apex_audit] {project_root}/.apex no existe — sigo igual, "
              f"esperando a que se cree...", file=sys.stderr)

    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    jsonl = out_dir / "apex_audit.jsonl"
    report_md = out_dir / "apex_audit.md"
    # truncar logs previos
    jsonl.write_text("", encoding="utf-8")

    log = EventLog(jsonl)
    log.project_root = project_root
    db_snap = ContextDBSnapshotter(project_root / ".apex" / "context.db", log)
    transcript = TranscriptTailer(project_root, log)
    fs_watch = FilesystemWatcher(project_root, log)
    git_watch = GitWatcher(project_root, log)
    stderr_in = StderrIngest(log)

    web_server: _AuditServer | None = None
    if args.serve is not None:
        try:
            web_server = _start_web_server(log, project_root,
                                             port=args.serve,
                                             open_browser=not args.no_browser)
            print(f"[apex_audit] UI: http://127.0.0.1:{args.serve}/",
                   file=sys.stderr)
        except OSError as e:
            print(f"[apex_audit] No pude arrancar el servidor en "
                   f"puerto {args.serve}: {e}", file=sys.stderr)

    log.emit("audit_started", project=str(project_root),
              out_dir=str(out_dir), pid=os.getpid())

    print(f"[apex_audit] Auditando {project_root}", file=sys.stderr)
    print(f"[apex_audit] Outputs: {jsonl} + {report_md}", file=sys.stderr)
    print(f"[apex_audit] Ctrl+C para parar.", file=sys.stderr)

    last_report = 0.0
    last_db = 0.0
    try:
        while True:
            now = time.monotonic()
            if now - last_db >= POLL_DB_S:
                db_snap.tick()
                fs_watch.tick()
                git_watch.tick()
                stderr_in.tick()
                last_db = now
            transcript.tick()
            if now - last_report >= REPORT_REFRESH_S:
                try:
                    report_md.write_text(render_report(log, project_root), encoding="utf-8")
                except OSError as e:
                    print(f"[apex_audit] Error escribiendo report: {e}", file=sys.stderr)
                last_report = now
            time.sleep(POLL_TRANSCRIPT_S)
    except KeyboardInterrupt:
        log.emit("audit_stopped", reason="SIGINT")
        report_md.write_text(render_report(log, project_root), encoding="utf-8")
        print(f"\n[apex_audit] Detenido. Report final en {report_md}", file=sys.stderr)
        print(f"[apex_audit] {len(log.events)} eventos en {jsonl}", file=sys.stderr)
        return 0
    finally:
        if web_server is not None:
            try:
                web_server.shutdown()
                web_server.server_close()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
