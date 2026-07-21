"""APEX MCP handler: goal."""
from __future__ import annotations

# Imports que el refactor a handlers dejó fuera al cortar del monolito.
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[2] / 'lib'))
from mcp.types import TextContent
from apex_handlers._common import find_project_root as _find_project_root
import goal_loop as _goal
import handoff as _handoff
from typing import Any


async def handle_apex_goal_loop(db: Any, arguments: dict) -> Any:
    """Handler for apex_goal_loop."""
    action = arguments["action"]
    project_root = _find_project_root()
    if action == "start":
        state = _goal.start_goal(
            project_root,
            arguments["goal"],
            turn_budget=int(arguments.get("turn_budget", _goal.DEFAULT_TURN_BUDGET)),
        )
        return [TextContent(type="text", text=(
            f"○ Goal set ({state.turn_budget}-turn budget): {state.goal}\n"
            f"  id: {state.id}"
        ))]
    elif action == "record_turn":
        transcript_path = arguments.get("transcript_path") or None
        threshold_tokens = arguments.get("threshold_tokens")
        state = _goal.record_turn(
            project_root,
            arguments["goal_id"],
            arguments.get("turn_summary", ""),
            list(arguments.get("tools_used", [])),
            transcript_path=transcript_path,
            threshold_tokens=int(threshold_tokens) if threshold_tokens else None,
        )
        msg = (
            f"Turn {state.turns_used}/{state.turn_budget} recorded — "
            f"status={state.status}"
        )
        if state.status == _goal.STATUS_CONTEXT_THRESHOLD:
            sid = arguments.get("session_id") or f"goal_{state.id}"
            last_entry = state.history[-1] if state.history else {}
            transcript_tokens = int(last_entry.get("transcript_tokens", 0))
            threshold_used = int(last_entry.get("threshold_tokens", 0))
            handoff_path = await _handoff.serialize_handoff(
                project_root, sid, db,
                transcript_tokens=transcript_tokens,
            )
            msg += (
                f"\n\n⚠ Umbral de contexto cruzado "
                f"({transcript_tokens:,} tk ≥ {threshold_used:,} tk).\n"
                f"Handoff escrito en: {handoff_path}\n"
                f"Acción del usuario:\n"
                f"  1. Teclea `/clear` para liberar contexto.\n"
                f"  2. En la sesión nueva, ejecuta:\n"
                f"     apex_resume_session(session_id=\"{sid}\")"
            )
        return [TextContent(type="text", text=msg)]
    elif action == "judge_prompt":
        state = _goal.load_goal(project_root, arguments["goal_id"])
        prompt = _goal.build_judge_prompt(state)
        return [TextContent(type="text", text=prompt)]
    elif action == "apply_decision":
        decision = arguments.get("decision") or {"decision": "continue", "reason": "(sin)"}
        state = _goal.apply_judge_decision(project_root, arguments["goal_id"], decision)
        glyph = {"done": "✓", "degenerate": "✗", "active": "↻",
                 "paused": "‖", "budget_exhausted": "⊘"}.get(state.status, "·")
        return [TextContent(type="text", text=(
            f"{glyph} status={state.status} ({state.turns_used}/{state.turn_budget}) — "
            f"{decision.get('reason', '')}"
        ))]
    elif action == "pause":
        state = _goal.pause_goal(project_root, arguments["goal_id"])
        return [TextContent(type="text", text=(
            f"‖ Goal paused — {state.turns_used}/{state.turn_budget} turns used"
        ))]
    elif action == "list":
        actives = _goal.list_active_goals(project_root)
        if not actives:
            return [TextContent(type="text", text="No hay goals activos.")]
        else:
            lines = [f"{len(actives)} goal(s) activo(s):"]
            for s in actives:
                lines.append(f"  - [{s.id}] {s.turns_used}/{s.turn_budget} — {s.goal[:120]}")
            return [TextContent(type="text", text="\n".join(lines))]
    elif action == "load":
        state = _goal.load_goal(project_root, arguments["goal_id"])
        return [TextContent(type="text", text=state.to_json())]
    else:
        return [TextContent(type="text", text=f"action desconocida: {action}")]


