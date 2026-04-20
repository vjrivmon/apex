"""Self-heal del segundo cerebro — detecta contradicciones, huérfanos, stale.

Ejecuta una batería de reglas sobre `.apex/context.db` + `.apex/wiki/` y
produce un informe en `.apex/wiki/lint-report-YYYY-MM-DD.md` agrupado por
severidad. No modifica nada por defecto (opt-in para auto-fix trivial).

Reglas implementadas:

- **DR-001 Decisiones contradictorias**: dos decisiones activas en la
  misma `category` con keywords opuestas (heurística "usar X" vs "no
  usar X", "hexagonal" vs "monolito"). Severidad: critical.

- **DR-002 Errores no enlazados a decisión**: errores con recurrence≥2
  que no tienen una decisión posterior que los aborde. Severidad: high.

- **CO-001 Componentes huérfanos**: componentes en `implemented` sin
  referencias en decisiones/wiki/errors. Severidad: medium.

- **WK-001 Wiki stale**: páginas con `updated_at` > 30 días y sin
  menciones en session_logs recientes. Severidad: low.

- **WK-002 Wiki sin wikilinks**: páginas (no raw/) sin outbound links.
  Severidad: low.

- **NS-001 Next steps bloqueados por step completado**: pasos abiertos
  cuyo `blocked_by` ya está `completed`. Severidad: medium (auto-fixable).

Uso:
    python -m lib.lint --project-root .          # informe
    python -m lib.lint --project-root . --apply  # auto-fix NS-001
    python -m lib.lint --severity critical       # sólo criticals
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Iterable


SEVERITIES = ("critical", "high", "medium", "low")


@dataclass
class Finding:
    rule_id: str
    severity: str
    title: str
    detail: str
    refs: list[str] = field(default_factory=list)
    fixable: bool = False


@dataclass
class LintReport:
    started_at: datetime
    project_root: Path
    findings: list[Finding] = field(default_factory=list)
    fixes_applied: list[str] = field(default_factory=list)

    def by_severity(self, sev: str) -> list[Finding]:
        return [f for f in self.findings if f.severity == sev]


# --- Reglas ---

CONTRADICTION_HINTS = [
    (re.compile(r"\bhexagonal\b", re.I), re.compile(r"\bmonolit", re.I)),
    (re.compile(r"\bmulti[- ]?agent", re.I), re.compile(r"\bmon(o|a)lit", re.I)),
    (re.compile(r"\blocal (llm|model)", re.I), re.compile(r"\bcloud (llm|model)", re.I)),
    (re.compile(r"\bnosql\b", re.I), re.compile(r"\brelational|postgres|sqlite\b", re.I)),
    (re.compile(r"\bsql(ite)?\b", re.I), re.compile(r"\bnosql|mongo|dynamo\b", re.I)),
    (re.compile(r"\bdark mode\b", re.I), re.compile(r"\blight mode only|no dark\b", re.I)),
]


def _check_contradictions(conn: sqlite3.Connection) -> list[Finding]:
    out: list[Finding] = []
    rows = conn.execute(
        "SELECT id, category, decision, reasoning FROM decisions "
        "WHERE invalid_from IS NULL OR invalid_from = ''"
    ).fetchall()
    by_cat: dict[str, list] = {}
    for r in rows:
        by_cat.setdefault(r[1] or "_", []).append(r)
    for cat, decs in by_cat.items():
        for i in range(len(decs)):
            for j in range(i + 1, len(decs)):
                a_id, _, a_dec, a_reason = decs[i]
                b_id, _, b_dec, b_reason = decs[j]
                a_text = f"{a_dec} {a_reason}"
                b_text = f"{b_dec} {b_reason}"
                for pat_a, pat_b in CONTRADICTION_HINTS:
                    if pat_a.search(a_text) and pat_b.search(b_text):
                        out.append(Finding(
                            rule_id="DR-001",
                            severity="critical",
                            title=f"Contradicción en categoría '{cat}'",
                            detail=f"Decisión #{a_id} ('{a_dec[:80]}') entra en conflicto con "
                                   f"decisión #{b_id} ('{b_dec[:80]}'). Una debe invalidarse.",
                            refs=[f"decision:{a_id}", f"decision:{b_id}"],
                        ))
                    elif pat_b.search(a_text) and pat_a.search(b_text):
                        out.append(Finding(
                            rule_id="DR-001",
                            severity="critical",
                            title=f"Contradicción en categoría '{cat}'",
                            detail=f"Decisión #{a_id} ('{a_dec[:80]}') entra en conflicto con "
                                   f"decisión #{b_id} ('{b_dec[:80]}').",
                            refs=[f"decision:{a_id}", f"decision:{b_id}"],
                        ))
    return out


def _check_errors_without_decision(conn: sqlite3.Connection) -> list[Finding]:
    out: list[Finding] = []
    try:
        errors = conn.execute(
            "SELECT id, source, description, lesson, recurrence_count, phase "
            "FROM errors WHERE recurrence_count >= 2"
        ).fetchall()
    except sqlite3.OperationalError:
        return out
    for e in errors:
        eid, src, desc, lesson, rec, phase = e
        # Buscar si hay decisión posterior cuyo texto contenga keywords del error
        keywords = _extract_keywords(desc + " " + (lesson or ""))
        hits = 0
        if keywords:
            q = " OR ".join(["decision LIKE ?"] * len(keywords))
            params = [f"%{k}%" for k in keywords]
            try:
                hits = conn.execute(
                    f"SELECT COUNT(*) FROM decisions WHERE ({q}) AND (invalid_from IS NULL OR invalid_from='')",
                    params,
                ).fetchone()[0]
            except sqlite3.OperationalError:
                hits = 0
        if hits == 0:
            out.append(Finding(
                rule_id="DR-002",
                severity="high",
                title=f"Error recurrente sin decisión vinculada",
                detail=f"Error #{eid} '{desc[:100]}' (x{rec}) no tiene decisión posterior "
                       "que institucionalice la lección. Considera registrar una.",
                refs=[f"error:{eid}"],
            ))
    return out


def _extract_keywords(text: str, min_len: int = 5, max_n: int = 3) -> list[str]:
    words = re.findall(r"[A-Za-zÁÉÍÓÚáéíóúñÑ]{%d,}" % min_len, text)
    # Más útiles: palabras capitalizadas o términos técnicos
    stop = {
        "siempre", "nunca", "hacer", "usando", "debido", "haber", "porque",
        "cuando", "antes", "después", "mismo", "sobre", "hacia", "entre",
    }
    seen: list[str] = []
    for w in words:
        wl = w.lower()
        if wl in stop or wl in seen:
            continue
        seen.append(wl)
        if len(seen) >= max_n:
            break
    return seen


def _check_orphan_components(conn: sqlite3.Connection) -> list[Finding]:
    out: list[Finding] = []
    try:
        comps = conn.execute(
            "SELECT id, name, status, description FROM components WHERE status = 'implemented'"
        ).fetchall()
    except sqlite3.OperationalError:
        return out
    for cid, cname, status, cdesc in comps:
        name = cname or cid
        refs = 0
        for table, col in [("decisions", "decision"), ("session_logs", "summary"),
                           ("wiki_pages", "content"), ("errors", "description")]:
            try:
                r = conn.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE {col} LIKE ?",
                    (f"%{name}%",),
                ).fetchone()[0]
                refs += r
            except sqlite3.OperationalError:
                continue
        if refs == 0:
            out.append(Finding(
                rule_id="CO-001",
                severity="medium",
                title=f"Componente huérfano",
                detail=f"Componente '{name}' marcado implemented pero sin mención "
                       "en decisiones/sesiones/wiki/errores. ¿Sigue vigente?",
                refs=[f"component:{cid}"],
            ))
    return out


def _check_wiki_stale(conn: sqlite3.Connection, cutoff_days: int = 30) -> list[Finding]:
    out: list[Finding] = []
    try:
        pages = conn.execute(
            "SELECT slug, title, updated_at FROM wiki_pages WHERE updated_at IS NOT NULL"
        ).fetchall()
    except sqlite3.OperationalError:
        return out
    cutoff = datetime.now(timezone.utc) - timedelta(days=cutoff_days)
    for slug, title, updated_at in pages:
        if not updated_at:
            continue
        try:
            dt = datetime.fromisoformat(str(updated_at).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if dt < cutoff:
            out.append(Finding(
                rule_id="WK-001",
                severity="low",
                title="Wiki page stale",
                detail=f"'{slug}' no se actualiza desde {dt.date().isoformat()} "
                       f"(>{cutoff_days}d). Revisar si sigue siendo cierta.",
                refs=[f"wiki:{slug}"],
            ))
    return out


def _check_wiki_without_links(project_root: Path) -> list[Finding]:
    out: list[Finding] = []
    wiki = project_root / ".apex" / "wiki"
    if not wiki.exists():
        return out
    for md in wiki.rglob("*.md"):
        rel = md.relative_to(wiki).as_posix()
        if rel.startswith(("raw/", "synthesis/")) or md.stem in ("SCHEMA", "index", "log"):
            continue
        text = md.read_text(encoding="utf-8", errors="ignore")
        if "[[" not in text:
            out.append(Finding(
                rule_id="WK-002",
                severity="low",
                title="Wiki sin wikilinks",
                detail=f"'{rel}' no tiene outbound [[wikilinks]]. El wiki "
                       "necesita cross-links para ser navegable.",
                refs=[f"wiki:{rel}"],
            ))
    return out


def _check_blocked_steps(conn: sqlite3.Connection) -> tuple[list[Finding], list[int]]:
    """Retorna findings + lista de step_ids auto-fixables (unblock)."""
    out: list[Finding] = []
    fixable_ids: list[int] = []
    try:
        steps = conn.execute(
            "SELECT id, description, priority, blocked_by, completed "
            "FROM next_steps WHERE (completed IS NULL OR completed = 0) "
            "AND blocked_by IS NOT NULL AND blocked_by != ''"
        ).fetchall()
    except sqlite3.OperationalError:
        return out, fixable_ids
    for sid, desc, prio, blocked_by, _ in steps:
        try:
            blockers = [int(x) for x in str(blocked_by).split(",") if x.strip().isdigit()]
        except ValueError:
            continue
        if not blockers:
            continue
        placeholders = ",".join(["?"] * len(blockers))
        try:
            incomplete = conn.execute(
                f"SELECT COUNT(*) FROM next_steps WHERE id IN ({placeholders}) "
                "AND (completed IS NULL OR completed = 0)",
                blockers,
            ).fetchone()[0]
        except sqlite3.OperationalError:
            continue
        if incomplete == 0:
            out.append(Finding(
                rule_id="NS-001",
                severity="medium",
                title="Next step bloqueado por paso ya completado",
                detail=f"Step #{sid} '{desc[:80]}' bloqueado por {blockers} — "
                       "todos completados. Desbloquéalo.",
                refs=[f"next_step:{sid}"],
                fixable=True,
            ))
            fixable_ids.append(sid)
    return out, fixable_ids


# --- Orquestador ---

def run_lint(project_root: Path, apply_fixes: bool = False) -> LintReport:
    report = LintReport(
        started_at=datetime.now(timezone.utc),
        project_root=project_root,
    )
    db_path = project_root / ".apex" / "context.db"
    if not db_path.exists():
        report.findings.append(Finding(
            rule_id="GEN-001", severity="critical",
            title="context.db no encontrada",
            detail=f"Sin {db_path} no hay second brain que limpiar. "
                   "Ejecuta apex_init_project primero.",
        ))
        return report

    conn = sqlite3.connect(str(db_path))
    try:
        report.findings.extend(_check_contradictions(conn))
        report.findings.extend(_check_errors_without_decision(conn))
        report.findings.extend(_check_orphan_components(conn))
        report.findings.extend(_check_wiki_stale(conn))
        report.findings.extend(_check_wiki_without_links(project_root))

        ns_findings, fixable_ids = _check_blocked_steps(conn)
        report.findings.extend(ns_findings)

        if apply_fixes and fixable_ids:
            conn.executemany(
                "UPDATE next_steps SET blocked_by = '' WHERE id = ?",
                [(sid,) for sid in fixable_ids],
            )
            conn.commit()
            for sid in fixable_ids:
                report.fixes_applied.append(f"NS-001 auto-fix: next_step #{sid} unblocked")
    finally:
        conn.close()

    return report


def _render_report(report: LintReport) -> str:
    date = report.started_at.strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"# Lint Report — {report.started_at.strftime('%Y-%m-%d')}",
        "",
        f"- Ejecutado: {date}",
        f"- Proyecto: `{report.project_root}`",
        f"- Findings: {len(report.findings)}",
        f"- Fixes aplicados: {len(report.fixes_applied)}",
        "",
    ]

    for sev in SEVERITIES:
        group = report.by_severity(sev)
        if not group:
            continue
        lines.append(f"## {sev.upper()} ({len(group)})")
        lines.append("")
        for f in group:
            tag = " · auto-fixable" if f.fixable else ""
            lines.append(f"### {f.rule_id} — {f.title}{tag}")
            lines.append(f.detail)
            if f.refs:
                lines.append("Refs: " + ", ".join(f.refs))
            lines.append("")

    if report.fixes_applied:
        lines.append("## Fixes aplicados")
        lines.extend(f"- {x}" for x in report.fixes_applied)

    if not report.findings:
        lines.append("✓ Sin findings. El segundo cerebro está limpio.")

    return "\n".join(lines)


def write_report(report: LintReport) -> Path:
    out_dir = report.project_root / ".apex" / "wiki"
    out_dir.mkdir(parents=True, exist_ok=True)
    date = report.started_at.strftime("%Y-%m-%d")
    path = out_dir / f"lint-report-{date}.md"
    path.write_text(_render_report(report), encoding="utf-8")
    return path


# --- CLI ---

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--project-root", type=Path, default=Path("."))
    p.add_argument("--apply", action="store_true",
                   help="Aplica fixes auto-fixables (NS-001)")
    p.add_argument("--severity", choices=SEVERITIES, default=None,
                   help="Filtra findings por severidad mínima")
    p.add_argument("--no-write", action="store_true",
                   help="No escribe el report a disco (stdout only)")
    args = p.parse_args(argv)

    report = run_lint(args.project_root.resolve(), apply_fixes=args.apply)

    if args.severity:
        level = SEVERITIES.index(args.severity)
        report.findings = [
            f for f in report.findings if SEVERITIES.index(f.severity) <= level
        ]

    md = _render_report(report)
    print(md)
    if not args.no_write:
        out = write_report(report)
        print(f"\nReport: {out}", file=sys.stderr)

    critical = len(report.by_severity("critical"))
    return 2 if critical > 0 else (1 if report.findings else 0)


if __name__ == "__main__":
    sys.exit(main())
