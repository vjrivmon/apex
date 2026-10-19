"""Handoff para sesiones largas (Sprint 9).

A ~40% de la ventana de contexto, la sesión empieza a perder precisión: las
respuestas se vuelven más superficiales y aumentan los errores de coherencia.
Esta librería construye un puente limpio para que la siguiente sesión arranque
con todo lo importante en contexto, sin arrastrar el ruido acumulado.

Componentes:

- `estimate_tokens_in_transcript(path)` — aproximación rápida (chars/4) del
  tamaño del JSONL de la sesión actual.
- `serialize_handoff(project_root, session_id, db)` — escribe
  `.apex/handoff/{session_id}.md` con estado activo: tasks pendientes,
  verdicts del grader bloqueando, goals activos, decisiones recientes,
  next_steps abiertos.
- `load_handoff(project_root, session_id)` — lee el .md serializado.
- `list_handoffs(project_root)` — lista handoffs disponibles ordenados por
  fecha descendente.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:  # el curador es opcional: sin httpx, APEX sigue funcionando igual
    import curator as _curator
except ImportError:  # pragma: no cover - solo si httpx no está instalado
    _curator = None  # type: ignore

# Aproximación grosera: 1 token ≈ 4 chars en inglés/español. Suficiente para
# detectar el umbral del 40% sin depender de tiktoken.
_CHARS_PER_TOKEN = 4

# Ventana de contexto típica de Claude Opus 4.7 (1M context). El umbral del 40%
# se interpreta sobre la ventana EFECTIVA (200K para sesiones normales) porque
# la 1M context es un tier especial. Se puede ajustar con la env var.
DEFAULT_CONTEXT_LIMIT = 200_000
HANDOFF_THRESHOLD = 0.40


# ── Medición ──────────────────────────────────────────────────────────────

def estimate_tokens_in_transcript(transcript_path: Path | str) -> int:
    """Aproxima el número de tokens leyendo el transcript JSONL."""
    p = Path(transcript_path)
    if not p.exists():
        return 0
    try:
        size_bytes = p.stat().st_size
    except OSError:
        return 0
    return size_bytes // _CHARS_PER_TOKEN


def is_over_threshold(transcript_path: Path | str,
                       threshold: float = HANDOFF_THRESHOLD,
                       context_limit: int = DEFAULT_CONTEXT_LIMIT) -> bool:
    tokens = estimate_tokens_in_transcript(transcript_path)
    return tokens >= int(context_limit * threshold)


# ── Serialización ─────────────────────────────────────────────────────────

def _handoff_dir(project_root: Path) -> Path:
    return Path(project_root) / ".apex" / "handoff"


def _handoff_path(project_root: Path, session_id: str) -> Path:
    return _handoff_dir(project_root) / f"{session_id}.md"


def _format_section(title: str, items: list[str]) -> str:
    if not items:
        return f"## {title}\n\n(ninguno)\n"
    body = "\n".join(f"- {x}" for x in items)
    return f"## {title}\n\n{body}\n"


async def collect_state_from_db(db) -> dict[str, Any]:
    """Extrae estado activo desde el ApexContextDB."""
    state: dict[str, Any] = {}

    try:
        state["current_phase"] = await db.get_current_phase()
    except Exception:
        state["current_phase"] = None

    try:
        state["all_phases"] = await db.get_all_phases()
    except Exception:
        state["all_phases"] = []

    # Verdicts del grader bloqueando alguna fase
    try:
        verdicts = await db.list_verdicts(limit=20)
        # Los bloqueos se consultan aparte, no se filtran del histórico:
        # filtrar los 20 últimos ocultaba un bloqueo vigente más antiguo, y
        # mostraba como vigentes los ya resueltos por un PASS posterior.
        state["blocking_verdicts"] = await db.list_blocking_verdicts()
        state["recent_verdicts"] = verdicts[:5]
    except Exception:
        state["blocking_verdicts"] = []
        state["recent_verdicts"] = []

    return state


def collect_active_goals(project_root: Path) -> list[dict]:
    """Lee `.apex/goal/*.json` y devuelve los activos."""
    out = []
    goal_dir = Path(project_root) / ".apex" / "goal"
    if not goal_dir.exists():
        return out
    for f in sorted(goal_dir.glob("*.json")):
        try:
            data = json.loads(f.read_text())
        except Exception:
            continue
        if data.get("status") == "active":
            out.append({
                "id": data.get("id"),
                "goal": data.get("goal"),
                "turns_used": data.get("turns_used"),
                "turn_budget": data.get("turn_budget"),
            })
    return out


def render_handoff(state: dict, active_goals: list[dict],
                   session_id: str, transcript_tokens: int) -> str:
    """Construye el markdown del handoff."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    lines: list[str] = []
    lines.append(f"# Handoff — sesión `{session_id}`")
    lines.append("")
    lines.append(f"Generado: {now}")
    lines.append(f"Tokens estimados en transcript: ~{transcript_tokens:,}")
    lines.append("")
    lines.append("> Este archivo se escribe automáticamente cuando la sesión "
                 "supera el 40% de la ventana de contexto. Para retomar en una "
                 "sesión nueva: `apex_resume_session(session_id)`.")
    lines.append("")

    cp = state.get("current_phase")
    if cp:
        lines.append(f"## Fase actual\n\n- {cp.get('number')} · {cp.get('name')}"
                     f" · {cp.get('status')}")
        if cp.get("notes"):
            lines.append(f"- notas: {cp['notes'][:200]}")
        lines.append("")
    else:
        lines.append("## Fase actual\n\n(ninguna en `in_progress`)\n")

    blocking = state.get("blocking_verdicts", [])
    if blocking:
        items = [
            f"Fase {v['phase']} — quality {v['quality']}/4 — issues: "
            f"{', '.join(v['issues'])} — {v['reasoning'][:160]}"
            for v in blocking
        ]
        lines.append(_format_section("Verdicts del grader BLOQUEANDO", items))
    else:
        lines.append("## Verdicts del grader BLOQUEANDO\n\n(ninguno)\n")

    if active_goals:
        items = [
            f"`{g['id']}` — {g['turns_used']}/{g['turn_budget']} — "
            f"{(g.get('goal') or '')[:140]}"
            for g in active_goals
        ]
        lines.append(_format_section("Goals activos", items))
    else:
        lines.append("## Goals activos\n\n(ninguno)\n")

    recent = state.get("recent_verdicts", [])
    if recent:
        items = [
            f"#{v['id']} fase {v['phase']} · q{v['quality']}/4 · "
            f"{('blocked' if v['should_block'] else 'pass')} · {v['created_at'][:19]}"
            for v in recent
        ]
        lines.append(_format_section("Últimos verdicts", items))

    return "\n".join(lines).rstrip() + "\n"


def _session_digest(state: dict, active_goals: list[dict]) -> str:
    """Texto plano con el estado de la sesión, para resumir."""
    lines: list[str] = []

    cp = state.get("current_phase")
    if cp:
        lines.append(f"Fase actual: {cp.get('number')} · {cp.get('name')} · "
                     f"{cp.get('status')}")
        if cp.get("notes"):
            lines.append(f"Notas de la fase: {cp['notes']}")

    for v in state.get("blocking_verdicts", []):
        lines.append(f"Verdict BLOQUEANTE fase {v.get('phase')} "
                     f"(calidad {v.get('quality')}/4): {v.get('reasoning')}")
    for v in state.get("recent_verdicts", []):
        lines.append(f"Verdict reciente fase {v.get('phase')} "
                     f"(calidad {v.get('quality')}/4): {v.get('reasoning')}")
    for g in active_goals:
        lines.append(f"Goal activo {g.get('id')} "
                     f"({g.get('turns_used')}/{g.get('turn_budget')}): "
                     f"{g.get('goal')}")

    return "\n".join(lines)


def _resumen_narrativo(state: dict, active_goals: list[dict],
                        db_path=None) -> str | None:
    """Resumen narrativo de la sesión con el curador local (opcional).

    Devuelve None si el curador está apagado o falla: el handoff se queda
    con la plantilla fija de siempre. El curador solo AÑADE contexto; no
    toca las secciones de fase, verdicts ni goals.
    """
    if _curator is None:
        return None
    digest = _session_digest(state, active_goals)
    if not digest.strip():
        return None
    curador = _curator.get_curator(db_path=db_path)
    if not curador.enabled:
        return None
    return curador.summarize(digest, max_tokens=400)


def _insertar_resumen(md: str, resumen: str) -> str:
    """Mete el bloque del curador delante de '## Fase actual'."""
    bloque = f"## Resumen de la sesión (curador)\n\n{resumen.strip()}\n\n"
    marcador = "## Fase actual"
    if marcador in md:
        return md.replace(marcador, bloque + marcador, 1)
    return md + "\n" + bloque


async def serialize_handoff(project_root: Path | str, session_id: str,
                             db, transcript_tokens: int = 0) -> Path:
    state = await collect_state_from_db(db)
    active_goals = collect_active_goals(Path(project_root))
    md = render_handoff(state, active_goals, session_id, transcript_tokens)

    # Sprint 18 (opt-in): resumen narrativo de la sesión. Sin curador, el
    # markdown es EXACTAMENTE el de la plantilla fija de siempre.
    narrativo = await asyncio.to_thread(
        _resumen_narrativo, state, active_goals, getattr(db, "db_path", None))
    if narrativo:
        md = _insertar_resumen(md, narrativo)

    path = _handoff_path(Path(project_root), session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(md, encoding="utf-8")
    return path


def load_handoff(project_root: Path | str, session_id: str) -> str | None:
    path = _handoff_path(Path(project_root), session_id)
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def list_handoffs(project_root: Path | str) -> list[dict]:
    out = []
    d = _handoff_dir(Path(project_root))
    if not d.exists():
        return out
    for f in sorted(d.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True):
        out.append({
            "session_id": f.stem,
            "path": str(f),
            "size_bytes": f.stat().st_size,
            "modified": datetime.fromtimestamp(
                f.stat().st_mtime, tz=timezone.utc).isoformat(timespec="seconds"),
        })
    return out
