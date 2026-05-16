"""APEX MCP handler: advisor."""
from __future__ import annotations
from typing import Any


async def handle_apex_advisor_review(db: Any, arguments: dict) -> Any:
    """Handler for apex_advisor_review."""
    session_id = arguments["session_id"]
    force = bool(arguments.get("force", False))
    trigger = arguments.get("trigger", "manual")
    db_path = str(db.db_path)
    run_, reason = _advisor.should_run(db_path, force=force)
    if not run_:
        return [TextContent(
            type="text",
            text=f"Advisor review SKIPPED: {reason}",
        )]

async def handle_apex_record_advice(db: Any, arguments: dict) -> Any:
    """Handler for apex_record_advice."""
    db_path = str(db.db_path)
    try:
        aid = _advisor.record_advice(
            db_path,
            review_id=int(arguments["review_id"]),
            kind=arguments["kind"],
            severity=arguments["severity"],
            title=arguments["title"],
            body=arguments["body"],
            evidence_refs=arguments.get("evidence_refs", []),
        )
    except ValueError as e:
        return [TextContent(type="text", text=f"Validación falló: {e}")]

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

async def handle_apex_advisor_compute_outcomes(db: Any, arguments: dict) -> Any:
    """Handler for apex_advisor_compute_outcomes."""
    project_path = str(_find_project_root().resolve())
    res = _advisor_outcomes.compute_outcomes(
        str(db.db_path),
        project_path,
        lookback_days=int(arguments.get("lookback_days", 14)),
        force=bool(arguments.get("force", False)),
    )
    lines = [
        "advisor_compute_outcomes:",
        f"  computed:      {res.computed}",
        f"  skipped:       {res.skipped}",
        f"  no_facet_yet:  {res.no_facet_yet}",
        f"  force_updated: {res.force_updated}",
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

