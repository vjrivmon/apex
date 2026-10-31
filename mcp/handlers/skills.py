"""APEX MCP handler: recomendación de skills visuales.

Stageshow y el resto de skills de diseño se resuelven en el árbol del repo,
sin `context.db`. El dispatcher la despacha con `db=None`.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from mcp.types import TextContent

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

import skill_router  # noqa: E402

SKILL_TOOLS = frozenset({
    "apex_recommend_skills",
})


async def handle_apex_recommend_skills(db: Any, arguments: dict) -> Any:
    """Handler for apex_recommend_skills."""
    phase_arg = arguments.get("phase")
    phase = int(phase_arg) if phase_arg is not None else None
    brief = arguments.get("brief") or ""
    text = skill_router.format_recommendation(phase, brief)
    return [TextContent(type="text", text=text)]
