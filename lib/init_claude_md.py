"""Genera un `CLAUDE.md` APEX-aware (Sprint 19, Gap D).

Un `CLAUDE.md` en la raíz del proyecto le dice al agente, en el primer turno,
cómo usar APEX y en qué punto está el proyecto. Este módulo lo genera (o lo
actualiza) leyendo el estado real desde `.apex/context.db`.

REGLAS DE ESCRITURA (inviolables)
---------------------------------
1. Si no existe `CLAUDE.md`, se crea con las 4 secciones.
2. Si existe, NUNCA se pisa: solo se actualiza el bloque delimitado por
   `<!-- APEX-AWARE START -->` / `<!-- APEX-AWARE END -->`.
3. Si existe pero sin ese bloque, el bloque se añade AL FINAL sin tocar
   ninguna línea del contenido previo.
4. El bloque aparece una sola vez: si quedan marcadores sueltos (p.ej. un
   START sin END), se limpian antes de insertar el bloque nuevo.

Uso:
    python -m lib.init_claude_md --project-root .
    python -m lib.init_claude_md --project-root . --check   # solo verifica
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path

try:  # El módulo se importa suelto (lib/ en el path) o como paquete.
    from lib.db_utils import get_sync_db
except ImportError:  # pragma: no cover - depende del contexto de import
    from db_utils import get_sync_db


# Marcadores del bloque que APEX gestiona. Todo lo que hay entre ellos se
# regenera; lo que hay fuera, no se toca.
BLOCK_START = "<!-- APEX-AWARE START -->"
BLOCK_END = "<!-- APEX-AWARE END -->"

CLAUDE_MD_NAME = "CLAUDE.md"

# Skills de APEX recomendadas por tipo de solución. Los nombres existen en
# `skills/` del repo de APEX; el proyecto destino los usa vía el servidor MCP.
SKILLS_BY_SOLUTION_TYPE: dict[str, tuple[str, ...]] = {
    "cli": ("tdd", "code-review", "security-audit"),
    "bot": ("tdd", "monitor", "second-brain"),
    "mcp": ("tools-integration", "code-review", "security-audit"),
    "app": ("design-system", "tdd", "monitor"),
    "agent": ("architect", "grill-with-docs", "prototype"),
    "streamlit": ("tdd", "monitor", "flow-guardian"),
}

DEFAULT_SKILLS: tuple[str, ...] = ("tdd", "code-review", "security-audit")

SKILL_DESCRIPTIONS: dict[str, str] = {
    "architect": "decisiones de stack, diseño de sistemas y specs",
    "code-review": "revisión de cambios antes de commitear",
    "design-system": "tokens de diseño, accesibilidad y consistencia visual",
    "flow-guardian": "revisión de flujos end-to-end y de los casos límite",
    "grill-with-docs": "interrogatorio al plan contra el dominio",
    "monitor": "observabilidad, health checks y alertas",
    "prototype": "modelar lógica de negocio como máquina de estados",
    "second-brain": "ingesta y búsqueda en el wiki del proyecto",
    "security-audit": "OWASP/STRIDE sobre lo implementado",
    "tdd": "ciclo test-first con casos borde",
    "tools-integration": "conectar APIs y herramientas externas",
}


@dataclass
class ProjectState:
    """Estado del proyecto leído de `.apex/context.db`."""

    db_exists: bool = False
    db_error: str | None = None
    phase_number: int | None = None
    phase_name: str | None = None
    phase_status: str | None = None
    phase_notes: str = ""
    solution_type: str = ""
    decisions: list[dict] = field(default_factory=list)
    skills: tuple[str, ...] = DEFAULT_SKILLS


def context_db_path(project_root: Path | str) -> Path:
    """Ruta canónica de la BD de contexto del proyecto."""
    return Path(project_root) / ".apex" / "context.db"


def read_project_state(project_root: Path | str) -> ProjectState:
    """Lee fase actual, decisiones vigentes y tipo de solución del proyecto."""
    root = Path(project_root)
    db_path = context_db_path(root)
    state = ProjectState()

    if not db_path.exists():
        return state

    state.db_exists = True
    try:
        with get_sync_db(db_path) as conn:
            conn.row_factory = sqlite3.Row
            state.phase_number, state.phase_name, state.phase_status, \
                state.phase_notes = _read_phase(conn)
            state.decisions = _read_decisions(conn)
            state.solution_type = _read_meta(conn, "tipo_solución")
    except (sqlite3.Error, OSError) as exc:
        state.db_error = str(exc)

    state.skills = SKILLS_BY_SOLUTION_TYPE.get(
        state.solution_type.strip().lower(), DEFAULT_SKILLS)
    return state


def _read_phase(conn: sqlite3.Connection) -> tuple[int | None, str | None, str | None, str]:
    """Fase en curso; si no hay, la última completada."""
    row = conn.execute(
        "SELECT phase_number, name, status, notes FROM phases "
        "WHERE status='in_progress' ORDER BY phase_number LIMIT 1"
    ).fetchone()
    if row is None:
        row = conn.execute(
            "SELECT phase_number, name, status, notes FROM phases "
            "WHERE status='completed' ORDER BY phase_number DESC LIMIT 1"
        ).fetchone()
    if row is None:
        return None, None, None, ""
    return row[0], row[1], row[2], (row[3] or "")


def _read_decisions(conn: sqlite3.Connection, limit: int = 5) -> list[dict]:
    """Decisiones vigentes, las 5 más recientes."""
    rows = conn.execute(
        "SELECT category, decision, reasoning, created_at FROM decisions "
        "WHERE invalid_from IS NULL "
        "ORDER BY created_at DESC, id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [
        {
            "category": r[0] or "",
            "decision": r[1] or "",
            "reasoning": r[2] or "",
            "created_at": r[3] or "",
        }
        for r in rows
    ]


def _read_meta(conn: sqlite3.Connection, key: str) -> str:
    row = conn.execute(
        "SELECT value FROM project_meta WHERE key=?", (key,)).fetchone()
    return (row[0] or "") if row else ""


def render_block(state: ProjectState) -> str:
    """Renderiza el bloque APEX (marcadores incluidos) a partir del estado."""
    lines: list[str] = [
        BLOCK_START,
        "",
        "## APEX — contexto del proyecto",
        "",
        "> Bloque generado por APEX. No lo edites a mano: se regenera al",
        "> cambiar de fase (`apex_set_phase`) o con",
        "> `python -m lib.init_claude_md --project-root .`.",
        "",
        "### 1. Antes de empezar",
        "",
        "1. Lee el estado del proyecto:",
        "   `mcp__apex__apex_get_context(level=\"timeline\")`.",
        "2. Si el proyecto es nuevo, inicialízalo:",
        "   `mcp__apex__apex_init_project(name=..., description=...)`.",
        "3. Registra cada decisión con",
        "   `mcp__apex__apex_add_decision(category, decision, reasoning)`",
        "   y cada error con `mcp__apex__apex_add_error(...)`.",
        "4. Avanza de fase con `mcp__apex__apex_set_phase(phase_number, status)`.",
        "   El gate 10.5 (AgentArmor) bloquea el deploy si no pasa.",
        "",
        "### 2. Fase actual",
        "",
    ]

    lines.extend(_render_phase(state))
    lines.extend([
        "",
        "### 3. Decisiones vigentes (top 5 más recientes)",
        "",
    ])
    lines.extend(_render_decisions(state))
    lines.extend([
        "",
        "### 4. Skills APEX recomendadas",
        "",
    ])
    lines.extend(_render_skills(state))

    lines.append("")
    lines.append(BLOCK_END)
    return "\n".join(lines)


def _render_phase(state: ProjectState) -> list[str]:
    if state.db_error:
        return [f"- No se ha podido leer `context.db`: {state.db_error}"]
    if not state.db_exists:
        return ["- Sin datos: aún no existe `.apex/context.db` en este proyecto.",
                "- Crea el proyecto con `mcp__apex__apex_init_project(...)`."]
    if state.phase_number is None:
        return ["- Ninguna fase activa todavía. Empieza por la fase 0 (socrático)."]
    notes = f" — {state.phase_notes}" if state.phase_notes else ""
    return [
        f"- **Fase {state.phase_number} — {state.phase_name}** "
        f"(`{state.phase_status}`){notes}"
    ]


def _render_decisions(state: ProjectState) -> list[str]:
    if not state.decisions:
        return ["- No hay decisiones vigentes registradas."]
    out = []
    for i, d in enumerate(state.decisions, start=1):
        category = f"**{d['category']}** " if d["category"] else ""
        reasoning = f" — {d['reasoning']}" if d["reasoning"] else ""
        out.append(f"{i}. {category}{d['decision']}{reasoning}")
    return out


def _render_skills(state: ProjectState) -> list[str]:
    out = []
    for name in state.skills:
        desc = SKILL_DESCRIPTIONS.get(name, "")
        out.append(f"- `{name}` — {desc}" if desc else f"- `{name}`")
    out.append("")
    out.append("Para el rol especializado de la fase actual: "
               "`mcp__apex__apex_recommend_role(phase=N)`.")
    return out


def ensure_claude_md(project_root: Path | str) -> Path:
    """Crea o actualiza el `CLAUDE.md` del proyecto. Devuelve su ruta.

    Idempotente: dos llamadas seguidas producen el mismo fichero.
    """
    root = Path(project_root).resolve()
    path = root / CLAUDE_MD_NAME
    block = render_block(read_project_state(root))

    if not path.exists():
        path.write_text(f"# {CLAUDE_MD_NAME}\n\n{block}\n", encoding="utf-8")
        return path

    text = path.read_text(encoding="utf-8")
    new_text = merge_block(text, block)
    if new_text != text:
        path.write_text(new_text, encoding="utf-8")
    return path


def merge_block(text: str, block: str) -> str:
    """Devuelve `text` con el bloque APEX actualizado.

    - Con bloque completo: se reemplaza el contenido entre los marcadores.
    - Sin bloque (o con marcadores sueltos): se limpia lo que haya y se
      añade el bloque al final, sin tocar el resto del contenido.
    """
    has_start = BLOCK_START in text
    has_end = BLOCK_END in text

    if has_start and has_end:
        start = text.index(BLOCK_START)
        end = text.index(BLOCK_END, start) + len(BLOCK_END)
        return text[:start] + block + text[end:]

    cleaned_lines = [
        line for line in text.splitlines()
        if line.strip() not in (BLOCK_START, BLOCK_END)
    ]
    body = "\n".join(cleaned_lines).rstrip()
    if not body:
        return f"{block}\n"
    return f"{body}\n\n{block}\n"


def check_claude_md(project_root: Path | str) -> bool:
    """True si el `CLAUDE.md` existe y su bloque está actualizado."""
    root = Path(project_root)
    path = root / CLAUDE_MD_NAME
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8")
    expected = render_block(read_project_state(root))
    return expected in text


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--project-root", type=Path, default=Path("."),
                   help="Directorio del proyecto (raíz del repo)")
    p.add_argument("--check", action="store_true",
                   help="No escribe: sale 1 si el CLAUDE.md falta o está desfasado")
    args = p.parse_args(argv)

    root = args.project_root.resolve()

    if args.check:
        ok = check_claude_md(root)
        path = root / CLAUDE_MD_NAME
        if ok:
            print(f"CLAUDE.md actualizado: {path}")
            return 0
        print(f"CLAUDE.md ausente o desfasado: {path}", file=sys.stderr)
        return 1

    path = ensure_claude_md(root)
    state = read_project_state(root)
    fase = (f"{state.phase_number} ({state.phase_name})"
            if state.phase_number is not None else "sin fase activa")
    print(f"CLAUDE.md escrito en {path}")
    print(f"- Fase actual: {fase}")
    print(f"- Decisiones vigentes: {len(state.decisions)}")
    print(f"- Skills recomendadas: {', '.join(state.skills)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
