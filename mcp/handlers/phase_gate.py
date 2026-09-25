"""APEX MCP handler: gate de entrada de fase (Sprint 20).

Recuperado en el merge del 2026-07-21: la refactorización a handlers partió de
una base anterior a S20, así que `apex_phase_entry_check` había desaparecido
del servidor. Este módulo lo restituye con el patrón nuevo, sin cambiar su
comportamiento.
"""
from __future__ import annotations

from typing import Any

from mcp.types import TextContent

from apex_handlers._common import _HUB_DB, find_project_root, search_cross_project

# Queries dirigidas por fase — no genéricas: una búsqueda vaga devuelve ruido
# y el gate deja de servir para nada.
_PHASE_QUERIES: dict[int, list[str]] = {
    5: ["scaffold hexagonal estructura errores", "git init secretos env"],
    6: ["domain logic pure core errores", "entidades casos de uso tests"],
    7: ["database adapter migraciones errores", "LLM adapter infraestructura"],
    8: ["integration end-to-end errores", "mock datos hardcoded frontend"],
    9: ["tests coverage playwright errores", "edge cases regresion"],
    10: ["seguridad OWASP secretos errores", "rate limit headers auth"],
}


async def handle_apex_phase_entry_check(db: Any, arguments: dict) -> Any:
    """Comprueba fase anterior + recupera lecciones cross-project de la fase."""
    phase = arguments["phase"]
    context_hint = arguments.get("context_hint", "")

    lines = [f"## Gate de entrada — Fase {phase}", ""]

    # 1. Verificar que la fase anterior quedó cerrada.
    prev_phase = phase - 1
    try:
        all_phases = await db.get_all_phases()
        phase_map = {p["number"]: p["status"] for p in all_phases}
        prev_status = phase_map.get(prev_phase)
    except Exception:  # noqa: BLE001 — context.db puede no estar inicializado
        prev_status = None

    if prev_status and prev_status != "completed":
        lines.append(
            f"ADVERTENCIA: Fase {prev_phase} esta en estado '{prev_status}', "
            f"no 'completed'."
        )
        lines.append(
            "  Verifica con apex_get_context(level='timeline') antes de continuar."
        )
    elif prev_status == "completed":
        lines.append(f"Fase {prev_phase}: completed")
    else:
        lines.append(
            f"Fase {prev_phase}: estado desconocido "
            f"(context.db no inicializado o fase no registrada)"
        )

    lines.append("")

    # 2. Retrieval cross-project dirigido por fase.
    root = find_project_root()
    current_project = root.name.lower().replace(" ", "-")
    all_errors: list[dict] = []
    all_decisions: list[dict] = []

    base_queries = _PHASE_QUERIES.get(phase, [])
    if context_hint:
        base_queries = [context_hint] + base_queries

    seen_errors: set = set()
    seen_decisions: set = set()

    for q in base_queries[:3]:  # máx 3 queries para no saturar
        hits = search_cross_project(q, limit=5, exclude_project=current_project)
        for e in hits.get("errors", []):
            key = (e["project_id"], e["description"][:60])
            if key not in seen_errors:
                seen_errors.add(key)
                all_errors.append(e)
        for d in hits.get("decisions", []):
            key = (d["project_id"], d["decision"][:60])
            if key not in seen_decisions:
                seen_decisions.add(key)
                all_decisions.append(d)

    # 3. Bloque visual auditable: si está vacío, lo dice — nunca finge hits.
    lines.append("### Lecciones cross-project aplicadas")
    lines.append("")

    if not _HUB_DB.exists():
        lines.append("hub.db no disponible — retrieval cross-project desactivado.")
        lines.append(
            "Para activarlo: lanza apex-hub (`python -m backend` en "
            "~/RoadToDevOps/apex-hub/)."
        )
    elif not all_errors and not all_decisions:
        lines.append(
            f"Sin lecciones cross-project para fase {phase}. "
            f"No hay errores ni decisiones previas relevantes."
        )
        lines.append("(hub.db disponible, 0 hits)")
    else:
        if all_errors:
            lines.append(f"**Errores a evitar ({len(all_errors)})**")
            for e in all_errors[:6]:
                sev = e.get("severity", "medium")
                rec = e.get("recurrence_count", 1)
                proj = e.get("project_id", "?")
                desc = e.get("description", "")[:120]
                lesson = e.get("lesson", "")[:180]
                lines.append(f"- [{proj} · {sev} · x{rec}] {desc}")
                if lesson:
                    lines.append(f"  → Lección: {lesson}")
        if all_decisions:
            lines.append("")
            lines.append(f"**Decisiones previas relevantes ({len(all_decisions)})**")
            for d in all_decisions[:4]:
                proj = d.get("project_id", "?")
                cat = d.get("category", "")
                dec = d.get("decision", "")[:120]
                tag = "INVALIDADA" if d.get("invalid_from") else "vigente"
                lines.append(f"- [{proj} · {cat} · {tag}] {dec}")

    lines.append("")
    lines.append("---")
    sub_paso = "abcdefghij"[phase - 5] if 5 <= phase <= 14 else "a"
    lines.append(
        f"Retrieval completado. Procede con sub-paso [{sub_paso}a] "
        f"de la fase {phase}."
    )

    return [TextContent(type="text", text="\n".join(lines))]
