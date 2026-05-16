"""APEX MCP handler: handoff."""
from __future__ import annotations
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

