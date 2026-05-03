#!/usr/bin/env python3
"""PostToolUse hook: avisa cuando un output supera el umbral, sugiriendo
archivar cooperativamente vía apex_archive_output (Sprint 9.2).

NO modifica el output (los hooks PostToolUse no pueden, el modelo ya lo leyó).
Solo emite un aviso por stderr para que el agente recuerde archivar el
contenido en futuras invocaciones similares.

Convención de hooks Claude Code (PostToolUse):
- Lee JSON desde stdin con tool_name + tool_input + tool_response.
- stderr → mensaje al usuario; exit 0.
"""
from __future__ import annotations

import json
import os
import sys

DEFAULT_THRESHOLD = int(os.environ.get("APEX_ARCHIVE_THRESHOLD_CHARS", "5000"))

# Tools cuya salida queremos vigilar. apex_get_archived NO se vigila a sí mismo
# para evitar loops, y apex_archive_output tampoco (su salida YA es resumen).
WATCHED_TOOL_PREFIXES = (
    "Bash",
    "Read",
    "mcp__playwright__",
    "mcp__github__",
    "mcp__plugin_github_github__",
    "mcp__filesystem__",
)
SKIP_TOOLS = {
    "mcp__apex__apex_archive_output",
    "mcp__apex__apex_get_archived",
}


def _output_size(response: dict) -> int:
    """Calcula chars del output. Maneja distintos shapes."""
    if isinstance(response, str):
        return len(response)
    if isinstance(response, dict):
        if "content" in response:
            content = response["content"]
            if isinstance(content, list):
                return sum(len(str(c.get("text", c))) for c in content)
            return len(str(content))
        if "output" in response:
            return len(str(response["output"]))
        return len(json.dumps(response))
    if isinstance(response, list):
        return sum(_output_size(item) for item in response)
    return len(str(response))


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0

    tool = payload.get("tool_name", "")
    if tool in SKIP_TOOLS:
        return 0

    if not any(tool.startswith(p) for p in WATCHED_TOOL_PREFIXES):
        return 0

    response = payload.get("tool_response") or payload.get("output") or ""
    size = _output_size(response)
    if size < DEFAULT_THRESHOLD:
        return 0

    sys.stderr.write(
        f"[apex post-tool-archive] {tool} devolvió ~{size:,} chars. "
        f"Considera apex_archive_output(tool=\"{tool}\", output=...) "
        f"para mantener el contexto limpio.\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
