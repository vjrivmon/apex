"""APEX MCP handler: advisor."""
from __future__ import annotations

# Imports que el refactor a handlers dejó fuera al cortar del monolito.
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[2] / 'lib'))
from mcp.types import TextContent
import advisor as _advisor
import advisor_health as _advisor_health
import advisor_outcomes as _advisor_outcomes
import advisor_tuning as _advisor_tuning
from apex_handlers._common import find_project_root as _find_project_root
from typing import Any


async def handle_apex_advisor_review(db: Any, arguments: dict) -> Any:
    """Handler for apex_advisor_review."""
    session_id = arguments["session_id"]
    force = bool(arguments.get("force", False))
    trigger = arguments.get("trigger", "manual")
    db_path = str(db.db_path)
    # Mantenimiento del ciclo (independiente del throttle): podar la
    # basura antigua y cerrar los reviews que ya están listos. Sin esto
    # los reviews se acumulaban en 'pending' para siempre (7269 filas
    # en la auditoría del 2026-10-19).
    _advisor.reap_stale_reviews(db_path)
    _advisor.close_ready_reviews(db_path)
    run_, reason = _advisor.should_run(db_path, force=force)
    if not run_:
        return [TextContent(
            type="text",
            text=f"Advisor review SKIPPED: {reason}",
        )]
    else:
        # Al abrir un review nuevo se cierra el anterior de la sesión:
        # un review abierto no puede quedar huérfano.
        cerrados = []
        for prev in _advisor.pending_reviews(db_path, session_id):
            cerrado = _advisor.close_review(db_path, prev["id"])
            if cerrado is not None:
                cerrados.append(cerrado)
        bundle = _advisor.build_bundle(db_path, session_id)
        tokens = _advisor.estimate_bundle_tokens(bundle)
        rid = _advisor.record_review(
            db_path, session_id, trigger, bundle_size_tokens=tokens,
        )
        lines = [
            f"advisor_review #{rid} creado · trigger={trigger}",
            f"  bundle_size_tokens≈{tokens}",
            f"  reason: {reason}",
        ]
        for c in cerrados:
            lines.append(
                f"  review anterior #{c['review_id']} cerrado: "
                f"status={c['status']} advice_count={c['advice_count']} "
                f"duration_ms={c['duration_ms']}"
            )
        lines += [
            "",
            "Próximo paso: invocar el subagent",
            f"  Task(subagent_type='apex-advisor', prompt='review_id={rid}; "
            f"session_id={session_id}; ver bundle vía apex_get_context')",
        ]
        if bundle.get("phase"):
            lines.append(f"  phase actual: {bundle['phase']}")
        if bundle.get("blocking_verdicts"):
            lines.append(
                f"  verdicts bloqueantes: {len(bundle['blocking_verdicts'])}"
            )
        return [TextContent(type="text", text="\n".join(lines))]


async def handle_apex_record_advice(db: Any, arguments: dict) -> Any:
    """Handler for apex_record_advice."""
    db_path = str(db.db_path)
    review_id = int(arguments["review_id"])
    try:
        aid = _advisor.record_advice(
            db_path,
            review_id=review_id,
            kind=arguments["kind"],
            severity=arguments["severity"],
            title=arguments["title"],
            body=arguments["body"],
            evidence_refs=arguments.get("evidence_refs", []),
        )
    except ValueError as e:
        return [TextContent(type="text", text=f"Validación falló: {e}")]
    else:
        # El review sigue 'pending' hasta que el subagente termine: no
        # hay señal de "fin de turno" en el protocolo. Lo que sí se
        # actualiza en cada card es el conteo, así que el cierre
        # posterior siempre es exacto.
        review = _advisor.get_review(db_path, review_id)
        extra = ""
        if review is not None:
            extra = (
                f" · review #{review_id} advice_count={review['advice_count']}"
                f" status={review['status']}"
            )
        if aid is None:
            return [TextContent(
                type="text",
                text=(
                    "Card duplicada (mismo review/kind/title) — "
                    "ignorada silenciosamente." + extra
                ),
            )]
        else:
            return [TextContent(
                type="text",
                text=(
                    f"advice #{aid} registrada · kind={arguments['kind']} "
                    f"severity={arguments['severity']}" + extra
                ),
            )]


async def handle_apex_dismiss_advice(db: Any, arguments: dict) -> Any:
    """Handler for apex_dismiss_advice."""
    db_path = str(db.db_path)
    try:
        ok = _advisor.dismiss_advice(
            db_path,
            advice_id=int(arguments["advice_id"]),
            reason=arguments["reason"],
        )
    except ValueError as e:
        return [TextContent(type="text", text=f"Validación falló: {e}")]
    else:
        if ok:
            return [TextContent(
                type="text",
                text=f"advice #{arguments['advice_id']} descartada.",
            )]
        else:
            return [TextContent(
                type="text",
                text=f"advice #{arguments['advice_id']} no existe.",
            )]


async def handle_apex_rate_advice(db: Any, arguments: dict) -> Any:
    """Handler for apex_rate_advice."""
    db_path = str(db.db_path)
    try:
        payload = _advisor.rate_advice(
            db_path,
            advice_id=int(arguments["advice_id"]),
            rating=arguments["rating"],
            reason=arguments["reason"],
        )
    except ValueError as e:
        return [TextContent(type="text", text=f"Validación falló: {e}")]
    else:
        return [TextContent(
            type="text",
            text=(
                f"outcome manual #{payload['outcome_id']} registrado "
                f"para advice #{arguments['advice_id']} "
                f"({arguments['rating']})."
            ),
        )]


async def handle_apex_advisor_compute_outcomes(db: Any, arguments: dict) -> Any:
    """Handler for apex_advisor_compute_outcomes."""
    project_path = str(_find_project_root().resolve())
    res = _advisor_outcomes.compute_outcomes(
        str(db.db_path),
        project_path,
        lookback_days=int(arguments.get("lookback_days", 14)),
        force=bool(arguments.get("force", False)),
    )
    # El escape hatch manual (`apex_rate_advice`) no depende de los
    # facets: se cuenta para que el usuario vea que sí deja señal.
    import sqlite3 as _sqlite3

    with _sqlite3.connect(str(db.db_path)) as _c:
        _row = _c.execute(
            "SELECT COUNT(*) FROM advice_outcomes WHERE assoc_method='manual'"
        ).fetchone()
    manual = int(_row[0]) if _row else 0
    lines = [
        "advisor_compute_outcomes:",
        f"  computed:      {res.computed}",
        f"  skipped:       {res.skipped}",
        f"  no_facet_yet:  {res.no_facet_yet}",
        f"  force_updated: {res.force_updated}",
        f"  manuales:      {manual}",
    ]
    if res.no_facet_yet > 0 and res.computed == 0:
        lines.append(
            "  aviso: ningún facet match. Si nunca corres "
            "`/insights`, no habrá outcomes implícitos. "
            "Considera `apex_rate_advice` (S16.6) como escape "
            "hatch o ejecuta `/insights` periódicamente."
        )
    return [TextContent(type="text", text="\n".join(lines))]

async def handle_apex_advisor_health(db: Any, arguments: dict) -> Any:
    """Handler for apex_advisor_health."""
    import json as _json
    payload = _advisor_health.advisor_health(
        str(db.db_path),
        window_days=int(arguments.get("window_days", 30)),
    )
    return [TextContent(
        type="text",
        text=_json.dumps(payload, ensure_ascii=False, indent=2),
    )]

async def handle_apex_advisor_apply_tuning(db: Any, arguments: dict) -> Any:
    """Handler for apex_advisor_apply_tuning."""
    import json as _json
    payload = _advisor_tuning.apply_tuning(
        str(db.db_path),
        dry_run=bool(arguments.get("dry_run", True)),
        force=bool(arguments.get("force", False)),
    )
    return [TextContent(
        type="text",
        text=_json.dumps(payload, ensure_ascii=False, indent=2),
    )]

