"""Reader puro de `~/.claude/usage-data/{facets,session-meta}` (Sprint 13.9).

Claude Code escribe dos directorios cuando el usuario corre `/insights`
(slash command oficial que genera `~/.claude/usage-data/report.html`):

- `session-meta/{uuid}.json` — métricas cuantitativas: tools usados,
  errores, líneas modificadas, commits, project_path, duración.
- `facets/{uuid}.json` — análisis cualitativo de un observer ajeno: outcome,
  helpfulness, primary_success, friction_counts, user_satisfaction,
  brief_summary.

Sirven a APEX como **ground truth externo**: el observer NO es el grader
interno, así que cruzando estos archivos con `context.db/grader_verdicts`
detectamos casos donde el grader pasó (`should_block=0`) pero el observer
dice que la sesión no logró el objetivo → grader laxo (A5 del doctor).

Best-effort en todo: si el directorio no existe (Claude Code nunca corrió
`/insights`, o se purgó), `iter_*` devuelve `[]` sin error.

Variable de entorno `APEX_USAGE_DATA_ROOT` permite override para tests.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator


def usage_data_root() -> Path:
    """Raíz de usage-data. Respeta `APEX_USAGE_DATA_ROOT` (tests)."""
    env = os.environ.get("APEX_USAGE_DATA_ROOT")
    if env:
        return Path(env)
    return Path.home() / ".claude" / "usage-data"


@dataclass
class UsageMeta:
    """Subset relevante de `session-meta/{sid}.json` para el doctor."""
    session_id: str
    project_path: str
    start_time: str                       # ISO8601 UTC
    duration_minutes: int
    tool_counts: dict[str, int]
    tool_errors: int
    tool_error_categories: dict[str, int]
    git_commits: int
    lines_added: int
    lines_removed: int
    files_modified: int

    def started_at_dt(self) -> datetime | None:
        if not self.start_time:
            return None
        try:
            s = self.start_time.replace("Z", "+00:00")
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except (ValueError, AttributeError):
            return None

    def contains_timestamp(self, ts: datetime, slack_minutes: int = 5) -> bool:
        """¿Cae `ts` dentro de [start, start + duration + slack]?"""
        start = self.started_at_dt()
        if start is None:
            return False
        end = start + timedelta(minutes=self.duration_minutes + slack_minutes)
        return start <= ts <= end


@dataclass
class UsageFacets:
    """Subset relevante de `facets/{sid}.json` para el doctor."""
    session_id: str
    outcome: str
    claude_helpfulness: str
    primary_success: str
    session_type: str
    friction_counts: dict[str, int]
    friction_detail: str
    user_satisfaction_counts: dict[str, int]
    brief_summary: str


def _load_json(path: Path) -> dict | None:
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def iter_meta(
    project_path: str | None = None,
    root: Path | None = None,
) -> Iterator[UsageMeta]:
    """Itera `session-meta`. Si `project_path` se da, filtra a esas sesiones."""
    base = (root or usage_data_root()) / "session-meta"
    if not base.exists():
        return
    for f in sorted(base.glob("*.json")):
        d = _load_json(f)
        if not d:
            continue
        if project_path is not None and d.get("project_path") != project_path:
            continue
        try:
            yield UsageMeta(
                session_id=str(d.get("session_id") or f.stem),
                project_path=str(d.get("project_path", "") or ""),
                start_time=str(d.get("start_time", "") or ""),
                duration_minutes=int(d.get("duration_minutes", 0) or 0),
                tool_counts=d.get("tool_counts") or {},
                tool_errors=int(d.get("tool_errors", 0) or 0),
                tool_error_categories=d.get("tool_error_categories") or {},
                git_commits=int(d.get("git_commits", 0) or 0),
                lines_added=int(d.get("lines_added", 0) or 0),
                lines_removed=int(d.get("lines_removed", 0) or 0),
                files_modified=int(d.get("files_modified", 0) or 0),
            )
        except (TypeError, ValueError):
            continue


def iter_facets(
    session_ids: set[str] | None = None,
    root: Path | None = None,
) -> Iterator[UsageFacets]:
    """Itera `facets`. Si `session_ids` se da, filtra a esas sesiones."""
    base = (root or usage_data_root()) / "facets"
    if not base.exists():
        return
    files = sorted(base.glob("*.json"))
    if session_ids is not None:
        files = [f for f in files if f.stem in session_ids]
    for f in files:
        d = _load_json(f)
        if not d:
            continue
        try:
            yield UsageFacets(
                session_id=str(d.get("session_id") or f.stem),
                outcome=str(d.get("outcome", "") or ""),
                claude_helpfulness=str(d.get("claude_helpfulness", "") or ""),
                primary_success=str(d.get("primary_success", "") or ""),
                session_type=str(d.get("session_type", "") or ""),
                friction_counts=d.get("friction_counts") or {},
                friction_detail=str(d.get("friction_detail", "") or ""),
                user_satisfaction_counts=d.get("user_satisfaction_counts") or {},
                brief_summary=str(d.get("brief_summary", "") or ""),
            )
        except (TypeError, ValueError):
            continue


def find_session_for_timestamp(
    ts: datetime,
    project_path: str,
    root: Path | None = None,
    slack_minutes: int = 5,
) -> str | None:
    """Devuelve session_id de la sesión del proyecto que contiene `ts`.

    Heurística temporal usada por A5 para asociar `grader_verdicts.created_at`
    con sesiones de Claude Code sin necesidad de migrar el schema. Si dos
    sesiones del proyecto solapan en el tiempo (raro porque Claude Code
    serializa una sesión activa por usuario), devuelve la primera match."""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    for meta in iter_meta(project_path=project_path, root=root):
        if meta.contains_timestamp(ts, slack_minutes=slack_minutes):
            return meta.session_id
    return None


def project_session_ids(
    project_path: str,
    root: Path | None = None,
) -> set[str]:
    """Set de `session_id` del proyecto. Útil para acotar `iter_facets()`."""
    return {m.session_id for m in iter_meta(project_path=project_path, root=root)}
