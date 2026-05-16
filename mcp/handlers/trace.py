"""APEX MCP handler: trace."""
from __future__ import annotations
from typing import Any


async def handle_apex_log_trace(db: Any, arguments: dict) -> Any:
    """Handler for apex_log_trace."""
    db_path = str(db.db_path)
    try:
        tid = _traces.log_trace(
            db_path,
            session_id=arguments["session_id"],
            phase=arguments.get("phase"),
            category=arguments["category"],
            gate_kind=arguments["gate_kind"],
            deliberation=arguments["deliberation"],
            calibration_confidence=float(arguments["calibration_confidence"]),
            calibration_text=arguments.get("calibration_text", ""),
            alternatives_considered=arguments.get("alternatives_considered", []),
        )
    except ValueError as e:
        return [TextContent(type="text", text=f"Validación falló: {e}")]

async def handle_apex_handoff_skill(db: Any, arguments: dict) -> Any:
    """Handler for apex_handoff_skill."""
    db_path = str(db.db_path)
    try:
        hid = _handoff_skill.create_handoff(
            db_path,
            session_id=arguments["session_id"],
            from_skill=arguments["from_skill"],
            to_skill=arguments["to_skill"],
            reason=arguments["reason"],
            snapshot=arguments.get("snapshot", {}),
        )
    except ValueError as e:
        return [TextContent(type="text", text=f"Validación falló: {e}")]

async def handle_apex_resume_skill_handoff(db: Any, arguments: dict) -> Any:
    """Handler for apex_resume_skill_handoff."""
    db_path = str(db.db_path)
    d = _handoff_skill.resume_handoff(
        db_path,
        handoff_id=int(arguments["handoff_id"]),
        result_summary=arguments.get("result_summary", ""),
    )
    if d is None:
        return [TextContent(
            type="text",
            text=f"handoff #{arguments['handoff_id']} no existe.",
        )]

