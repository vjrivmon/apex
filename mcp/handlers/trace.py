"""APEX MCP handler: trace."""
from __future__ import annotations

# Imports que el refactor a handlers dejó fuera al cortar del monolito.
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[2] / 'lib'))
from mcp.types import TextContent
import skill_handoff as _handoff_skill
import reasoning_traces as _traces
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
    else:
        return [TextContent(
            type="text",
            text=(
                f"reasoning_trace #{tid} registrada · "
                f"category={arguments['category']} "
                f"gate={arguments['gate_kind']}"
            ),
        )]


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
    else:
        return [TextContent(
            type="text",
            text=(
                f"skill_handoff #{hid} creado: "
                f"{arguments['from_skill']} → {arguments['to_skill']}.\n"
                f"Para volver: apex_resume_skill_handoff(handoff_id={hid}, "
                f"result_summary='...')"
            ),
        )]


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
    else:
        lines = [
            f"skill_handoff #{d['id']} retomado · "
            f"vuelves a {d['from_skill']}",
            f"  origen del handoff: {d['from_skill']} → {d['to_skill']}",
            f"  razón original: {d['reason']}",
        ]
        snap = d.get("snapshot")
        if isinstance(snap, dict) and snap:
            lines.append(f"  snapshot keys: {list(snap.keys())}")
        return [TextContent(type="text", text="\n".join(lines))]


