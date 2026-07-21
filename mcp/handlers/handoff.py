"""APEX MCP handler: handoff."""
from __future__ import annotations

# Imports que el refactor a handlers dejó fuera al cortar del monolito.
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[2] / 'lib'))
from mcp.types import TextContent
from apex_handlers._common import find_project_root as _find_project_root
import handoff as _handoff
import token_filter as _tf
from typing import Any


async def handle_apex_handoff_write(db: Any, arguments: dict) -> Any:
    """Handler for apex_handoff_write."""
    session_id = arguments["session_id"]
    transcript_tokens = int(arguments.get("transcript_tokens", 0))
    project_root = _find_project_root()
    path = await _handoff.serialize_handoff(
        project_root, session_id, db, transcript_tokens=transcript_tokens)
    return [TextContent(type="text", text=(
        f"Handoff escrito en {path}\n"
        f"Tokens estimados: {transcript_tokens:,}\n"
        f"Para retomar: apex_resume_session(session_id=\"{session_id}\")"
    ))]

async def handle_apex_resume_session(db: Any, arguments: dict) -> Any:
    """Handler for apex_resume_session."""
    project_root = _find_project_root()
    session_id = arguments.get("session_id")
    if not session_id:
        handoffs = _handoff.list_handoffs(project_root)
        if not handoffs:
            return [TextContent(type="text", text=(
                "No hay handoffs en .apex/handoff/. "
                "Ejecuta apex_handoff_write(session_id=...) primero."))]
        else:
            lines = [f"{len(handoffs)} handoff(s) disponible(s):"]
            for h in handoffs[:10]:
                lines.append(f"  - {h['session_id']} · "
                             f"{h['size_bytes']:,} bytes · {h['modified']}")
            return [TextContent(type="text", text="\n".join(lines))]
    else:
        content = _handoff.load_handoff(project_root, session_id)
        if content is None:
            return [TextContent(type="text", text=(
                f"No hay handoff para session_id={session_id}. "
                f"Lista disponibles con apex_resume_session() sin args."))]
        else:
            return [TextContent(type="text", text=content)]


async def handle_apex_archive_output(db: Any, arguments: dict) -> Any:
    """Handler for apex_archive_output."""
    tool_name = arguments["tool"]
    tool_args = arguments.get("arguments", {})
    output = arguments["output"]
    summary = _tf.summarize_for_context(output)
    aid = await db.archive_output(tool_name, tool_args, output, summary)
    return [TextContent(type="text", text=(
        f"Archivado #{aid} — {len(output):,} chars completos, "
        f"{len(summary):,} chars en resumen.\n"
        f"Recuperar con apex_get_archived(id={aid}).\n\n"
        f"Resumen:\n{summary}"
    ))]

async def handle_apex_get_archived(db: Any, arguments: dict) -> Any:
    """Handler for apex_get_archived."""
    aid = arguments.get("id")
    if aid is None:
        tool_filter = arguments.get("tool")
        items = await db.list_archived(limit=20, tool=tool_filter)
        if not items:
            return [TextContent(type="text", text="No hay archivos en tool_output_archive.")]
        else:
            lines = [f"{len(items)} archivo(s):"]
            for it in items:
                lines.append(
                    f"  #{it['id']} · {it['tool']} · "
                    f"{it['chars_full']:,} chars (resumen {it['chars_summary']:,}) · "
                    f"{it['created_at']}"
                )
            return [TextContent(type="text", text="\n".join(lines))]
    else:
        rec = await db.get_archived(int(aid))
        if rec is None:
            return [TextContent(type="text", text=f"No existe archivo #{aid}.")]
        else:
            return [TextContent(type="text", text=(
                f"Archivo #{rec['id']} ({rec['tool']}, "
                f"{rec['chars_full']:,} chars, {rec['created_at']}):\n\n"
                f"{rec['output_full']}"
            ))]


