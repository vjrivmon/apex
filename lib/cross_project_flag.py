"""Registro de "se consultó el hub" para la regla absoluta #18.

La regla #18 de `commands/rules/absolute-rules.md` dice:

    18. **Cross-project retrieval obligatorio** antes de decisiones de
    diseno/stack: `apex_search_cross_project(query)` previene repetir
    bugs vistos en otros proyectos del ecosistema.

"Obligatorio" sin maquinaria es una recomendación. Esta es la maquinaria:
cuando el agente consulta el hub, queda registrado que lo hizo para esa
fase; el grader lo comprueba en las fases de decisión (0, 2, 3 y 5) y
bloquea si no se consultó.

El flag vive en `project_meta`, con una clave por fase
(`cross_project_consulted_phase_<N>`). Es un hecho: "para esta fase se
consultó el hub". No se puede registrar a mano desde fuera del MCP, y el
escape (`force=True` con razón) deja traza igual que los demás overrides.

La lógica venía del commit `bce5bf6` de la rama
`origin/fix/cross-project-tone-2026-07-06`, que nunca se fusionó.
"""
from __future__ import annotations

# Fases donde consultar el hub es obligatorio: son las de DECISIÓN
# (mercado, diseño, spec, scaffold). Regla absoluta #18.
CROSS_PROJECT_PHASES = frozenset({0, 2, 3, 5})

# Prefijo de la clave en project_meta.
META_PREFIX = "cross_project_consulted_phase_"


def meta_key(phase: int) -> str:
    """Clave de `project_meta` que registra la consulta para esa fase."""
    return f"{META_PREFIX}{int(phase)}"


async def mark_consulted(db, phase: int | None = None) -> bool:
    """Registra que se consultó el hub para esa fase. Best-effort.

    Si `phase` es None, usa la fase actual del proyecto. Devuelve True si
    quedó registrado. Nunca lanza: el retrieval no se interrumpe por no
    poder anotar una meta.
    """
    if phase is None:
        try:
            actual = await db.get_current_phase()
            phase = actual["number"] if actual else None
        except Exception:
            phase = None
    if phase is None:
        return False
    try:
        await db.set_meta(meta_key(phase), "true")
        return True
    except Exception:
        return False


async def was_consulted(db, phase: int) -> bool:
    """¿Se consultó el hub para esa fase? Best-effort."""
    try:
        valor = await db.get_meta(meta_key(phase))
        return valor == "true"
    except Exception:
        return False
