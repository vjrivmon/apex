"""Apex-doctor — loop de auto-mejora periódico (Sprint 13).

Corre 3 analizadores sobre context.db + .apex/handoff/ y propone mejoras
accionables al sistema. Trigger normal: hook `end-of-day-doctor.py` al detectar
una frase de cierre del día o tras superar el umbral de duración de la sesión.

Analizadores:

- **A1 override_clusters** — agrupa errores recurrentes (`recurrence_count>=3`)
  o de severidad `critical`/`high`. Cada cluster se transforma en una propuesta
  preventiva (skill o checklist).
- **A2 grader_block_patterns** — busca issues del grader (`should_block=1`)
  que aparecen en >=2 fases distintas. Propone refinar la regla determinista
  o crear una skill que lo evite.
- **A3 stale_handoffs** — handoffs en `.apex/handoff/` con mtime >7 días que
  no fueron rehidratados. Marca para limpieza.
- **A4 cross_project_patterns** (Sprint 13.8) — errores o issues del grader
  agregados en `hub.db` que aparecen en >=2 proyectos APEX distintos.
  Genera propuestas para promoverlos a guideline cross-project. Antes de
  correr, sincroniza los verdicts locales a `hub.db` para que estén
  disponibles. Best-effort: si `hub.db` no existe, A4 se salta sin crashear.

Idempotencia: cada propuesta lleva una `signature` canónica. Si ya existe en
`doctor_proposals` con esa signature, no se duplica (UNIQUE constraint).
Las propuestas `cross_project_pattern` se postean además a
`doctor_tickets` en `hub.db` (también UNIQUE por signature).

Throttle: `MIN_RUN_GAP_SECONDS` (default 3600s = 1h) entre ejecuciones para
evitar doble-disparo. `force=True` lo salta.

Diseño síncrono (sqlite3) porque el hook que dispara debe ser barato y no
queremos arrastrar asyncio al ciclo PostHook.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── Constantes ────────────────────────────────────────────────────────────

MIN_RUN_GAP_SECONDS = 3600          # 1h entre runs (throttle)
A1_MIN_RECURRENCE = 3               # errores con recurrence_count >= 3
A1_HIGH_SEVERITIES = {"critical", "high"}
A2_MIN_PHASES = 2                   # issue del grader en >=2 fases
A3_STALE_DAYS = 7                   # handoff sin tocar >7 días = stale
A2_LOOKBACK = 100                   # últimos N verdicts del grader
A4_MIN_PROJECTS = 2                 # cross-project pattern: issue en >=2 proyectos
A4_LOOKBACK = 500                   # últimos N verdicts del hub al cruzar

HUB_DB_DEFAULT = Path.home() / "RoadToDevOps" / "apex-hub" / "data" / "hub.db"

_HUB_SCHEMA = """
CREATE TABLE IF NOT EXISTS doctor_tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    signature TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    source_projects_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_doctor_tickets_kind
    ON doctor_tickets(kind, created_at DESC);

CREATE TABLE IF NOT EXISTS grader_verdicts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    original_id INTEGER NOT NULL,
    phase INTEGER,
    question_index INTEGER,
    status TEXT,
    issues_json TEXT NOT NULL DEFAULT '[]',
    suggestion TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(project_id, original_id)
);
CREATE INDEX IF NOT EXISTS idx_grader_verdicts_project
    ON grader_verdicts(project_id, created_at DESC);
"""


# ── Dataclasses ───────────────────────────────────────────────────────────

@dataclass
class DoctorProposal:
    """Propuesta accionable generada por un analizador."""
    kind: str                                       # override_cluster | grader_block_pattern | stale_handoff
    signature: str                                  # canónica para idempotencia
    title: str
    body: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def signature_hash(self) -> str:
        return hashlib.sha1(self.signature.encode("utf-8")).hexdigest()[:12]


@dataclass
class DoctorRun:
    """Resultado de una ejecución del doctor."""
    run_id: int
    started_at: str
    finished_at: str
    proposals: list[DoctorProposal]
    trigger: str
    status: str                                     # done | failed | throttled
    skipped_reason: str = ""

    @property
    def proposals_count(self) -> int:
        return len(self.proposals)


# ── Paths ─────────────────────────────────────────────────────────────────

def context_db_path(project_root: Path | str) -> Path:
    return Path(project_root) / ".apex" / "context.db"


def doctor_dir(project_root: Path | str) -> Path:
    return Path(project_root) / ".apex" / "doctor"


def handoff_dir(project_root: Path | str) -> Path:
    return Path(project_root) / ".apex" / "handoff"


# ── Conexiones ────────────────────────────────────────────────────────────

def _ro_conn(db_path: Path) -> sqlite3.Connection | None:
    if not db_path.exists():
        return None
    try:
        return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.OperationalError:
        return None


def _rw_conn(db_path: Path) -> sqlite3.Connection | None:
    if not db_path.exists():
        return None
    try:
        return sqlite3.connect(str(db_path))
    except sqlite3.OperationalError:
        return None


# ── A1: Override clusters ────────────────────────────────────────────────

def analyze_override_clusters(db_path: Path) -> list[DoctorProposal]:
    """Errores con recurrence_count alto o severity crítica → propuesta
    preventiva. Cada cluster reúne 1 error (no varios) para no diluir la
    signature; agrupar por description+severity es suficiente para detectar
    recurrencia real."""
    conn = _ro_conn(db_path)
    if conn is None:
        return []
    try:
        rows = conn.execute(
            "SELECT id, source, phase, description, lesson, severity, "
            "recurrence_count, last_seen FROM errors "
            "WHERE recurrence_count >= ? OR severity IN ('critical', 'high') "
            "ORDER BY recurrence_count DESC, last_seen DESC",
            (A1_MIN_RECURRENCE,),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()

    proposals: list[DoctorProposal] = []
    for r in rows:
        err_id, source, phase, description, lesson, severity, recurrence, last_seen = r
        sig = f"override_cluster:{severity}:{(description or '')[:120]}"
        title = f"Error recurrente ({severity}, x{recurrence}): {(description or '')[:60]}"
        body = (
            f"## Error recurrente\n\n"
            f"- **Descripción**: {description}\n"
            f"- **Severidad**: {severity}\n"
            f"- **Recurrencia**: {recurrence}\n"
            f"- **Última vez**: {last_seen}\n"
            f"- **Source**: {source}\n"
            f"- **Fase original**: {phase if phase is not None else 'sin fase'}\n\n"
            f"## Lección registrada\n\n"
            f"{lesson or '_(sin lección)_'}\n\n"
            f"## Acción sugerida\n\n"
            f"Ejecutar `apex_skill_forge_scan(force=True)` para que el detector "
            f"D1 (grader_block) genere una skill preventiva específica, o crear "
            f"una skill manual que verifique esta condición al inicio de la "
            f"fase {phase if phase is not None else 'relevante'}.\n"
        )
        proposals.append(DoctorProposal(
            kind="override_cluster",
            signature=sig,
            title=title,
            body=body,
            evidence={
                "error_id": err_id,
                "severity": severity,
                "recurrence_count": recurrence,
                "phase": phase,
            },
        ))
    return proposals


# ── A2: Grader block patterns ────────────────────────────────────────────

def analyze_grader_block_patterns(db_path: Path) -> list[DoctorProposal]:
    """Issues del grader que bloquean en >=A2_MIN_PHASES fases distintas.
    Distinto del D1 del skill_forge: aquí el umbral es menor (>=2) y la
    propuesta es para AFINAR la regla determinista del grader o cambiar
    el flujo, no para crear una skill."""
    conn = _ro_conn(db_path)
    if conn is None:
        return []
    try:
        rows = conn.execute(
            "SELECT phase, issues, reasoning FROM grader_verdicts "
            "WHERE should_block=1 ORDER BY id DESC LIMIT ?",
            (A2_LOOKBACK,),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()

    issue_to_phases: dict[str, set[int]] = {}
    issue_to_reasonings: dict[str, list[str]] = {}
    for phase, issues_json, reasoning in rows:
        try:
            issues = json.loads(issues_json or "[]")
        except (TypeError, json.JSONDecodeError):
            continue
        for iss in issues:
            if not isinstance(iss, str):
                continue
            issue_to_phases.setdefault(iss, set()).add(int(phase))
            issue_to_reasonings.setdefault(iss, []).append(reasoning or "")

    proposals: list[DoctorProposal] = []
    for issue, phases in issue_to_phases.items():
        if len(phases) < A2_MIN_PHASES:
            continue
        sample_reasoning = next(
            (r for r in issue_to_reasonings.get(issue, []) if r), ""
        )[:240]
        sig = f"grader_block_pattern:{issue}"
        title = f"Grader bloqueando issue '{issue}' en {len(phases)} fases"
        body = (
            f"## Patrón del grader\n\n"
            f"- **Issue**: `{issue}`\n"
            f"- **Fases afectadas**: {', '.join(map(str, sorted(phases)))}\n"
            f"- **Razonamiento ejemplo**: {sample_reasoning or '_(sin razonamiento)_'}\n\n"
            f"## Acción sugerida\n\n"
            f"1. Revisar el check determinista de `lib/grader.py` que dispara "
            f"`{issue}` — ¿es demasiado estricto o demasiado laxo?\n"
            f"2. Si la regla es correcta y el issue es real, crear una skill "
            f"preventiva con `apex_skill_forge_scan(force=True)` (D1).\n"
            f"3. Si la regla es ruido, ajustar `lib/grader.py` y registrar "
            f"la decisión con `apex_add_decision(category='grader', ...)`.\n"
        )
        proposals.append(DoctorProposal(
            kind="grader_block_pattern",
            signature=sig,
            title=title,
            body=body,
            evidence={
                "issue": issue,
                "phases": sorted(phases),
                "occurrences": len(phases),
            },
        ))
    return proposals


# ── A3: Stale handoffs ───────────────────────────────────────────────────

def analyze_stale_handoffs(project_root: Path) -> list[DoctorProposal]:
    """Handoffs sin tocar más de A3_STALE_DAYS días. Asume que un handoff sin
    rehidratar en una semana ya no se va a usar; mantenerlo sólo confunde."""
    d = handoff_dir(project_root)
    if not d.exists():
        return []

    cutoff = datetime.now(timezone.utc).timestamp() - A3_STALE_DAYS * 86400
    proposals: list[DoctorProposal] = []
    stale_files: list[tuple[Path, float]] = []
    for f in d.glob("*.md"):
        try:
            mtime = f.stat().st_mtime
        except OSError:
            continue
        if mtime < cutoff:
            stale_files.append((f, mtime))

    if not stale_files:
        return []

    stale_files.sort(key=lambda t: t[1])
    sig = f"stale_handoffs:{','.join(sorted(f.stem for f, _ in stale_files))}"
    title = f"{len(stale_files)} handoff(s) stale (>{A3_STALE_DAYS}d sin rehidratar)"
    listing = "\n".join(
        f"- `{f.name}` — modificado {datetime.fromtimestamp(m, tz=timezone.utc).isoformat(timespec='seconds')}"
        for f, m in stale_files
    )
    body = (
        f"## Handoffs sin uso\n\n"
        f"{listing}\n\n"
        f"## Acción sugerida\n\n"
        f"Si no vas a retomar estas sesiones, bórralas:\n\n"
        f"```bash\n"
        + "\n".join(f"rm '{f}'" for f, _ in stale_files)
        + "\n```\n\n"
        f"Si alguna sigue siendo útil, ejecuta "
        f"`apex_resume_session('{stale_files[0][0].stem[:12]}...')` para "
        f"rehidratarla y eso actualiza el mtime.\n"
    )
    proposals.append(DoctorProposal(
        kind="stale_handoff",
        signature=sig,
        title=title,
        body=body,
        evidence={
            "files": [f.name for f, _ in stale_files],
            "count": len(stale_files),
        },
    ))
    return proposals


# ── Hub bridge: schema, sync verdicts, post tickets ──────────────────────

def _project_id_from_root(project_root: Path) -> str:
    """Convención hub.db `projects.id`: nombre del directorio raíz en
    lowercase. Ejemplos: 'apex', 'tfg-tutor-virtual', 'focusnow'."""
    return project_root.resolve().name.lower()


def _hub_conn(hub_db: Path | None) -> sqlite3.Connection | None:
    """Conexión RW a hub.db. Devuelve None si la ruta no existe o falla."""
    if hub_db is None or not Path(hub_db).exists():
        return None
    try:
        return sqlite3.connect(str(hub_db), timeout=5.0)
    except sqlite3.Error:
        return None


def _ensure_hub_schema(conn: sqlite3.Connection) -> bool:
    """Crea tablas `doctor_tickets` y `grader_verdicts` (IF NOT EXISTS).
    Best-effort: True si el schema queda listo, False si falla."""
    try:
        conn.executescript(_HUB_SCHEMA)
        conn.commit()
        return True
    except sqlite3.Error:
        return False


def sync_local_verdicts_to_hub(
    local_db: Path,
    hub_db: Path | None,
    project_id: str,
) -> int:
    """Copia `grader_verdicts` locales nuevos a `hub.grader_verdicts`.

    Mapping:
      - local.id          → hub.original_id
      - hub.project_id    = `project_id`
      - local.phase       → hub.phase  (también copiado a hub.question_index
                            como proxy: local no tiene índice de pregunta)
      - local.should_block→ hub.status ('blocked' si 1, 'ok' si 0)
      - local.issues      → hub.issues_json
      - local.category +
        local.reasoning   → hub.suggestion (concatenados, máx 500 chars)
      - local.created_at  → hub.created_at

    Dedup: `INSERT OR IGNORE` sobre UNIQUE(project_id, original_id). Devuelve
    nº de filas insertadas. Best-effort: 0 si hub_db no existe o falla."""
    hub = _hub_conn(hub_db)
    if hub is None:
        return 0
    try:
        if not _ensure_hub_schema(hub):
            return 0
        local = _ro_conn(local_db)
        if local is None:
            return 0
        try:
            rows = local.execute(
                "SELECT id, phase, category, issues, should_block, "
                "reasoning, created_at FROM grader_verdicts ORDER BY id"
            ).fetchall()
        except sqlite3.OperationalError:
            return 0
        finally:
            local.close()

        inserted = 0
        for row in rows:
            local_id, phase, category, issues_json, should_block, reasoning, created_at = row
            status = "blocked" if should_block else "ok"
            suggestion = (f"[{category or 'general'}] {reasoning or ''}").strip()[:500]
            try:
                cur = hub.execute(
                    "INSERT OR IGNORE INTO grader_verdicts "
                    "(project_id, original_id, phase, question_index, status, "
                    " issues_json, suggestion, created_at) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (project_id, int(local_id), int(phase) if phase is not None else None,
                     int(phase) if phase is not None else None, status,
                     issues_json or "[]", suggestion, created_at or ""),
                )
                if cur.rowcount > 0:
                    inserted += 1
            except sqlite3.Error:
                continue
        hub.commit()
        return inserted
    finally:
        hub.close()


def post_ticket_to_hub(
    proposal: DoctorProposal,
    hub_db: Path | None,
) -> bool:
    """Escribe la propuesta como fila en `hub.doctor_tickets` con
    `INSERT OR IGNORE` sobre `signature UNIQUE`. Devuelve True si insertó
    una fila nueva, False si dedup o si hub_db ausente."""
    hub = _hub_conn(hub_db)
    if hub is None:
        return False
    try:
        if not _ensure_hub_schema(hub):
            return False
        source_projects = proposal.evidence.get("projects", [])
        try:
            cur = hub.execute(
                "INSERT OR IGNORE INTO doctor_tickets "
                "(kind, signature, title, body, source_projects_json, status) "
                "VALUES (?,?,?,?,?,?)",
                (proposal.kind, proposal.signature, proposal.title,
                 proposal.body, json.dumps(source_projects, ensure_ascii=False),
                 "open"),
            )
            hub.commit()
            return cur.rowcount > 0
        except sqlite3.Error:
            return False
    finally:
        hub.close()


# ── A4: Cross-project patterns ───────────────────────────────────────────

def analyze_cross_project_patterns(
    hub_db: Path | None,
    current_project_id: str,
) -> list[DoctorProposal]:
    """Issues del grader que aparecen en >=A4_MIN_PROJECTS proyectos distintos
    en `hub.grader_verdicts`. Genera propuesta para promover a guideline
    cross-project. Best-effort: si hub.db no existe, devuelve []."""
    hub = _hub_conn(hub_db)
    if hub is None:
        return []
    try:
        if not _ensure_hub_schema(hub):
            return []
        try:
            rows = hub.execute(
                "SELECT project_id, issues_json FROM grader_verdicts "
                "WHERE status='blocked' ORDER BY id DESC LIMIT ?",
                (A4_LOOKBACK,),
            ).fetchall()
        except sqlite3.OperationalError:
            return []

        issue_to_projects: dict[str, set[str]] = {}
        for project_id, issues_json in rows:
            try:
                issues = json.loads(issues_json or "[]")
            except (TypeError, json.JSONDecodeError):
                continue
            for iss in issues:
                if not isinstance(iss, str):
                    continue
                issue_to_projects.setdefault(iss, set()).add(project_id)

        proposals: list[DoctorProposal] = []
        for issue, projects in issue_to_projects.items():
            if len(projects) < A4_MIN_PROJECTS:
                continue
            sorted_projects = sorted(projects)
            sig = f"cross_project_pattern:{issue}"
            others = [p for p in sorted_projects if p != current_project_id]
            title = (
                f"Issue '{issue}' bloqueando en {len(projects)} proyectos "
                f"({', '.join(sorted_projects)})"
            )
            body = (
                f"## Patrón cross-project\n\n"
                f"- **Issue**: `{issue}`\n"
                f"- **Proyectos afectados**: {', '.join(sorted_projects)}\n"
                f"- **Otros proyectos** (excluyendo este): "
                f"{', '.join(others) if others else '_(sólo este)_'}\n\n"
                f"## Acción sugerida\n\n"
                f"Este issue del grader bloquea en varios proyectos. Considerar:\n\n"
                f"1. Promover la regla a una **lección cross-project** "
                f"(`apex_search_cross_project` la inyectará en SessionStart "
                f"de futuros proyectos).\n"
                f"2. Crear una skill preventiva con "
                f"`apex_skill_forge_scan(force=True)` que fire en patrones "
                f"que llevan a este issue.\n"
                f"3. Si la regla del grader es ruidosa en multiproyecto, "
                f"ajustarla en `lib/grader.py` y registrar la decisión.\n"
            )
            proposals.append(DoctorProposal(
                kind="cross_project_pattern",
                signature=sig,
                title=title,
                body=body,
                evidence={
                    "issue": issue,
                    "projects": sorted_projects,
                    "current_project": current_project_id,
                },
            ))
        return proposals
    finally:
        hub.close()


# ── Persistencia: runs y proposals ───────────────────────────────────────

def last_run_at(db_path: Path) -> datetime | None:
    """Devuelve el started_at del último run, o None si no hay runs."""
    conn = _ro_conn(db_path)
    if conn is None:
        return None
    try:
        row = conn.execute(
            "SELECT started_at FROM doctor_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    finally:
        conn.close()
    if not row or not row[0]:
        return None
    try:
        return datetime.fromisoformat(row[0].replace(" ", "T")).replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return None


def is_throttled(db_path: Path, gap_seconds: int = MIN_RUN_GAP_SECONDS) -> bool:
    last = last_run_at(db_path)
    if last is None:
        return False
    delta = datetime.now(timezone.utc) - last
    return delta.total_seconds() < gap_seconds


def _start_run(db_path: Path, trigger: str) -> int:
    conn = _rw_conn(db_path)
    if conn is None:
        return 0
    try:
        cur = conn.execute(
            "INSERT INTO doctor_runs (trigger, status) VALUES (?, 'running')",
            (trigger,),
        )
        conn.commit()
        return int(cur.lastrowid or 0)
    finally:
        conn.close()


def _finish_run(db_path: Path, run_id: int, proposals_count: int,
                status: str = "done") -> None:
    conn = _rw_conn(db_path)
    if conn is None:
        return
    try:
        conn.execute(
            "UPDATE doctor_runs SET finished_at=datetime('now'), "
            "proposals_count=?, status=? WHERE id=?",
            (proposals_count, status, run_id),
        )
        conn.commit()
    finally:
        conn.close()


def is_proposal_recorded(db_path: Path, signature: str) -> bool:
    conn = _ro_conn(db_path)
    if conn is None:
        return False
    try:
        row = conn.execute(
            "SELECT 1 FROM doctor_proposals WHERE signature=? LIMIT 1",
            (signature,),
        ).fetchone()
        return row is not None
    except sqlite3.OperationalError:
        return False
    finally:
        conn.close()


def record_proposal(db_path: Path, run_id: int,
                    proposal: DoctorProposal) -> int | None:
    """Inserta la propuesta. Devuelve el id o None si ya existía
    (UNIQUE(signature) la rechaza silenciosamente)."""
    conn = _rw_conn(db_path)
    if conn is None:
        return None
    try:
        cur = conn.execute(
            "INSERT OR IGNORE INTO doctor_proposals "
            "(run_id, kind, signature, title, body) VALUES (?, ?, ?, ?, ?)",
            (run_id, proposal.kind, proposal.signature,
             proposal.title, proposal.body),
        )
        conn.commit()
        if cur.rowcount == 0:
            return None
        return int(cur.lastrowid or 0)
    finally:
        conn.close()


def list_recent_proposals(db_path: Path,
                           status: str | None = "open",
                           limit: int = 50) -> list[dict[str, Any]]:
    conn = _ro_conn(db_path)
    if conn is None:
        return []
    try:
        if status:
            rows = conn.execute(
                "SELECT id, run_id, kind, signature, title, body, status, "
                "created_at FROM doctor_proposals WHERE status=? "
                "ORDER BY created_at DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, run_id, kind, signature, title, body, status, "
                "created_at FROM doctor_proposals "
                "ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()
    return [
        {"id": r[0], "run_id": r[1], "kind": r[2], "signature": r[3],
         "title": r[4], "body": r[5], "status": r[6], "created_at": r[7]}
        for r in rows
    ]


# ── Session start tracking (alimenta trigger temporal del hook) ──────────

def record_session_start(db_path: Path, session_id: str) -> bool:
    """Inserta session_id si no existe. Devuelve True si fue nuevo."""
    if not session_id:
        return False
    conn = _rw_conn(db_path)
    if conn is None:
        return False
    try:
        cur = conn.execute(
            "INSERT OR IGNORE INTO session_starts (session_id) VALUES (?)",
            (session_id,),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def session_started_at(db_path: Path, session_id: str) -> datetime | None:
    if not session_id:
        return None
    conn = _ro_conn(db_path)
    if conn is None:
        return None
    try:
        row = conn.execute(
            "SELECT started_at FROM session_starts WHERE session_id=?",
            (session_id,),
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    finally:
        conn.close()
    if not row or not row[0]:
        return None
    try:
        return datetime.fromisoformat(row[0].replace(" ", "T")).replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return None


def session_age_seconds(db_path: Path, session_id: str) -> float | None:
    started = session_started_at(db_path, session_id)
    if started is None:
        return None
    return (datetime.now(timezone.utc) - started).total_seconds()


# ── Markdown report ──────────────────────────────────────────────────────

def render_run_md(run: DoctorRun, project_root: Path) -> str:
    """Genera el markdown del report del run para `.apex/doctor/<run_id>.md`."""
    lines: list[str] = []
    lines.append(f"# Apex-doctor run #{run.run_id}")
    lines.append("")
    lines.append(f"- **Inicio**: {run.started_at}")
    lines.append(f"- **Fin**: {run.finished_at}")
    lines.append(f"- **Trigger**: `{run.trigger}`")
    lines.append(f"- **Status**: `{run.status}`")
    lines.append(f"- **Propuestas**: {run.proposals_count}")
    lines.append("")

    if not run.proposals:
        lines.append("> Sin hallazgos. APEX está limpio en estos analizadores.")
        lines.append("")
        return "\n".join(lines)

    by_kind: dict[str, list[DoctorProposal]] = {}
    for p in run.proposals:
        by_kind.setdefault(p.kind, []).append(p)

    kind_titles = {
        "override_cluster": "Errores recurrentes / críticos",
        "grader_block_pattern": "Patrones del grader bloqueando",
        "stale_handoff": "Handoffs obsoletos",
        "cross_project_pattern": "Patrones cross-project",
    }
    for kind, items in by_kind.items():
        lines.append(f"## {kind_titles.get(kind, kind)} ({len(items)})")
        lines.append("")
        for p in items:
            lines.append(f"### {p.title}")
            lines.append("")
            lines.append(f"- **Signature**: `{p.signature_hash()}`")
            lines.append("")
            lines.append(p.body)
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_run_md(run: DoctorRun, project_root: Path | str) -> Path:
    out_dir = doctor_dir(project_root)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{run.run_id:04d}.md"
    path.write_text(render_run_md(run, Path(project_root)), encoding="utf-8")
    return path


# ── Orquestador ──────────────────────────────────────────────────────────

def _resolve_hub_db(hub_db: Path | str | None) -> Path | None:
    """Resuelve hub_db: arg explícito > env APEX_HUB_DB_PATH > HUB_DB_DEFAULT.
    Devuelve None si la ruta no existe (best-effort: A4 se salta sin error)."""
    import os
    if hub_db is not None:
        p = Path(hub_db)
    else:
        env = os.environ.get("APEX_HUB_DB_PATH")
        p = Path(env) if env else HUB_DB_DEFAULT
    return p if p.exists() else None


def run_doctor(
    project_root: Path | str,
    trigger: str = "manual",
    force: bool = False,
    hub_db: Path | str | None = None,
) -> DoctorRun:
    """Ejecuta los 4 analizadores (A1-A4) y persiste resultados.

    Si está throttled (<MIN_RUN_GAP_SECONDS desde último run) y `force=False`,
    devuelve un DoctorRun con status='throttled'.

    `hub_db` opcional: si None, resuelve por env `APEX_HUB_DB_PATH` o cae al
    default `~/RoadToDevOps/apex-hub/data/hub.db`. Si la BD no existe, A4
    devuelve [] sin error (backward-compatible: callers sin hub_db siguen
    funcionando como Sprint 13.0).
    """
    project_root = Path(project_root)
    db = context_db_path(project_root)
    project_id = _project_id_from_root(project_root)
    resolved_hub = _resolve_hub_db(hub_db)

    if not force and is_throttled(db):
        last = last_run_at(db)
        gap_min = int((datetime.now(timezone.utc) - last).total_seconds() / 60) if last else 0
        return DoctorRun(
            run_id=0,
            started_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            finished_at="",
            proposals=[],
            trigger=trigger,
            status="throttled",
            skipped_reason=(
                f"Último run hace {gap_min}min "
                f"(<{MIN_RUN_GAP_SECONDS // 60}min de cooldown)"
            ),
        )

    run_id = _start_run(db, trigger=trigger)
    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # Sync local→hub ANTES de A4. Wrapped aparte: si falla, A1-A3 + A4 siguen.
    try:
        sync_local_verdicts_to_hub(db, resolved_hub, project_id)
    except Exception:
        pass

    # Recoger todas las propuestas, persistir las nuevas (UNIQUE skip duplicados)
    all_props: list[DoctorProposal] = []
    try:
        all_props += analyze_override_clusters(db)
        all_props += analyze_grader_block_patterns(db)
        all_props += analyze_stale_handoffs(project_root)
        all_props += analyze_cross_project_patterns(resolved_hub, project_id)
    except Exception:
        _finish_run(db, run_id, 0, status="failed")
        return DoctorRun(
            run_id=run_id, started_at=started_at,
            finished_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            proposals=[], trigger=trigger, status="failed",
        )

    new_proposals: list[DoctorProposal] = []
    for p in all_props:
        if record_proposal(db, run_id, p) is not None:
            new_proposals.append(p)
            # Cross-project patterns también se postean al hub como tickets
            if p.kind == "cross_project_pattern":
                try:
                    post_ticket_to_hub(p, resolved_hub)
                except Exception:
                    pass

    finished_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _finish_run(db, run_id, len(new_proposals), status="done")

    run = DoctorRun(
        run_id=run_id,
        started_at=started_at,
        finished_at=finished_at,
        proposals=new_proposals,
        trigger=trigger,
        status="done",
    )
    write_run_md(run, project_root)
    return run


def short_summary(run: DoctorRun) -> str:
    """Resumen de una línea para inyectar en stderr/additionalContext."""
    if run.status == "throttled":
        return f"[apex-doctor] saltado: {run.skipped_reason}"
    if run.status == "failed":
        return f"[apex-doctor] run #{run.run_id} falló"
    if run.proposals_count == 0:
        return (
            f"[apex-doctor] run #{run.run_id} corrió sin hallazgos "
            f"(trigger={run.trigger})"
        )
    kinds = sorted({p.kind for p in run.proposals})
    return (
        f"[apex-doctor] run #{run.run_id}: {run.proposals_count} propuesta(s) "
        f"en {', '.join(kinds)} → ver .apex/doctor/{run.run_id:04d}.md"
    )


# ── Util ─────────────────────────────────────────────────────────────────

_WORD_RE = re.compile(r"\w+", re.UNICODE)


def _slug_from(text: str, n: int = 40) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s[:n] or "anon"
