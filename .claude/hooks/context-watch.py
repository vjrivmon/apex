#!/usr/bin/env python3
"""UserPromptSubmit hook: aviso de handoff cuando el transcript pasa el umbral
configurado (Sprint 9.1, refinado para Opus 1M).

Dos modos de configurar el umbral (el absoluto gana si está > 0):

- `APEX_HANDOFF_THRESHOLD_TOKENS` (absoluto, recomendado): dispara cuando el
  transcript supera ese número de tokens, independiente del modelo. Útil con
  Opus 4.7 1M context donde "el 40%" no tiene el mismo significado que en
  Sonnet 200K. Por defecto `0` (desactivado, usa porcentaje).
- `APEX_HANDOFF_THRESHOLD` (porcentaje, fallback): fracción [0, 1] aplicada
  sobre `APEX_CONTEXT_LIMIT` (default 200000). Por defecto `0.40`.

A partir del umbral, las respuestas pierden precisión. Este hook mide el
tamaño del transcript JSONL de la sesión actual y, si lo supera, inyecta un
aviso para que el agente sugiera handoff + /clear + apex_resume_session.

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

from lib.hook_metrics import start_hook, end_hook

# 1 token ≈ 4 chars (aproximación coherente con lib/handoff.py)
_CHARS_PER_TOKEN = 4
_DEFAULT_CONTEXT_LIMIT = int(os.environ.get("APEX_CONTEXT_LIMIT", "200000"))
_THRESHOLD = float(os.environ.get("APEX_HANDOFF_THRESHOLD", "0.40"))
_THRESHOLD_TOKENS = int(os.environ.get("APEX_HANDOFF_THRESHOLD_TOKENS", "0"))


def _measure_transcript(path: str) -> int:
    try:
        return Path(path).stat().st_size // _CHARS_PER_TOKEN
    except Exception:
        end_hook("context-watch", _hook_start, exit_code=0)
        return 0


def main() -> int:
    _hook_start = start_hook("context-watch")
    try:
        payload = json.load(sys.stdin)
    except Exception:
        end_hook("context-watch", _hook_start, exit_code=0)
        return 0

    transcript = payload.get("transcript_path") or ""
    if not transcript:
        end_hook("context-watch", _hook_start, exit_code=0)
        return 0

    tokens = _measure_transcript(transcript)
    if tokens == 0:
        end_hook("context-watch", _hook_start, exit_code=0)
        return 0

    if _THRESHOLD_TOKENS > 0:
        threshold_tokens = _THRESHOLD_TOKENS
    else:
        threshold_tokens = int(_DEFAULT_CONTEXT_LIMIT * _THRESHOLD)
    if tokens < threshold_tokens:
        end_hook("context-watch", _hook_start, exit_code=0)
        return 0

    pct = round(100 * tokens / _DEFAULT_CONTEXT_LIMIT, 1)
    session_id = payload.get("session_id", "")
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()

    if _THRESHOLD_TOKENS > 0:
        threshold_label = f"umbral absoluto {_THRESHOLD_TOKENS:,} tk"
    else:
        threshold_label = (
            f"{int(_THRESHOLD * 100)}% de {_DEFAULT_CONTEXT_LIMIT:,}"
        )
    sys.stdout.write(
        "\n"
        f"[apex context-watch] La sesión actual usa ~{tokens:,} tokens "
        f"(~{pct}% de {_DEFAULT_CONTEXT_LIMIT:,}, supera {threshold_label}). "
        f"Recomendado:\n"
        f"  1. Llama a `apex_resume_session` para serializar el handoff "
        f"de esta sesión ({session_id[:12] or '?'}).\n"
        f"  2. Ejecuta `/clear` para liberar contexto.\n"
        f"  3. En la nueva sesión, `apex_resume_session(session_id="
        f"\"{session_id[:12] or '<id>'}\")` rehidrata el estado.\n"
        f"  Proyecto: {project_dir}\n"
    )
    end_hook("context-watch", _hook_start, exit_code=0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
