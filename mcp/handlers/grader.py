"""APEX MCP handler: grader."""
from __future__ import annotations

# Imports que el refactor a handlers dejó fuera al cortar del monolito.
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[2] / 'lib'))
from mcp.types import TextContent
from apex_handlers._common import find_project_root as _find_project_root
import grader as _grader
import json
from typing import Any


async def handle_apex_grader_evaluate(db: Any, arguments: dict) -> Any:
    """Handler for apex_grader_evaluate."""
    phase_n = int(arguments["phase"])
    mode = arguments.get("mode", "deterministic")
    component_types = list(arguments.get("component_types", []))
    persist = bool(arguments.get("persist", True))

    # Recolectar metadata de decisiones para enriquecer evidence
    try:
        decisions_meta = {}
        _os = await db.get_meta("detected_os")
        if _os:
            decisions_meta["detected_os"] = _os
    except Exception:
        decisions_meta = {}

    project_root = _find_project_root()
    evidence = _grader.gather_evidence(
        project_root=project_root,
        phase=phase_n,
        component_types=component_types,
        decisions_metadata=decisions_meta,
    )
    if mode == "full":
        verdict_obj = _grader.evaluate_full(evidence, use_anthropic=True)
    else:
        verdict_obj = _grader.evaluate_deterministic(evidence)

    verdict_id = None
    if persist:
        verdict_id = await db.add_verdict(**verdict_obj.to_db_kwargs())

    block_marker = "BLOCK" if verdict_obj.should_block else "PASS"
    lines = [
        f"[{block_marker}] Grader fase {phase_n} — quality {verdict_obj.quality}/4",
        f"Issues: {', '.join(verdict_obj.issues) or '(ninguna)'}",
        f"Checks: {json.dumps(verdict_obj.deterministic_checks, ensure_ascii=False)}",
        f"LLM judged: {verdict_obj.llm_judged}",
        f"Razón: {verdict_obj.reasoning}",
    ]
    if verdict_id:
        lines.append(f"Persistido como verdict #{verdict_id}")
    return [TextContent(type="text", text="\n".join(lines))]

