#!/usr/bin/env python3
"""UserPromptSubmit hook: aviso de handoff cuando el transcript pasa el 40%
de la ventana de contexto efectiva (Sprint 9.1).

A ~40% de contexto, las respuestas pierden precisión. Este hook mide el
tamaño del transcript JSONL de la sesión actual y, si supera el umbral,
inyecta un aviso visible para que el agente sugiera al usuario hacer
handoff + /clear + /apex:resume.

No bloquea. Solo informa. El usuario decide.

Convención de hooks Claude Code (UserPromptSubmit):
- Lee JSON desde stdin con `transcript_path`, `session_id`, etc.
- Texto a stdout se inyecta como contexto adicional al prompt.
- exit 0 → permite (el aviso ya se inyectó).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# 1 token ≈ 4 chars (aproximación coherente con lib/handoff.py)
_CHARS_PER_TOKEN = 4
_DEFAULT_CONTEXT_LIMIT = int(os.environ.get("APEX_CONTEXT_LIMIT", "200000"))
_THRESHOLD = float(os.environ.get("APEX_HANDOFF_THRESHOLD", "0.40"))


def _measure_transcript(path: str) -> int:
    try:
        return Path(path).stat().st_size // _CHARS_PER_TOKEN
    except Exception:
        return 0


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0

    transcript = payload.get("transcript_path") or ""
    if not transcript:
        return 0

    tokens = _measure_transcript(transcript)
    if tokens == 0:
        return 0

    threshold_tokens = int(_DEFAULT_CONTEXT_LIMIT * _THRESHOLD)
    if tokens < threshold_tokens:
        return 0

    pct = round(100 * tokens / _DEFAULT_CONTEXT_LIMIT, 1)
    session_id = payload.get("session_id", "")
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()

    sys.stdout.write(
        "\n"
        f"[apex context-watch] La sesión actual usa ~{tokens:,} tokens "
        f"(~{pct}% de {_DEFAULT_CONTEXT_LIMIT:,}). Recomendado:\n"
        f"  1. Llama a `apex_resume_session` para serializar el handoff "
        f"de esta sesión ({session_id[:12] or '?'}).\n"
        f"  2. Ejecuta `/clear` para liberar contexto.\n"
        f"  3. En la nueva sesión, `apex_resume_session(session_id="
        f"\"{session_id[:12] or '<id>'}\")` rehidrata el estado.\n"
        f"  Proyecto: {project_dir}\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
