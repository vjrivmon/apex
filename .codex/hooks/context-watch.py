#!/usr/bin/env python3
"""UserPromptSubmit hook: aviso de handoff cuando el transcript pasa el umbral
configurado (Sprint 9.1, refinado para Opus 1M).

El límite de contexto se detecta dinámicamente a partir del modelo activo
(leído del propio transcript), así el porcentaje y el umbral relativo son
correctos tanto en Sonnet 200K como en Opus 1M. Ver `_detect_context_limit`.

Dos modos de configurar el umbral (el absoluto gana si está > 0):

- `APEX_HANDOFF_THRESHOLD_TOKENS` (absoluto, recomendado): dispara cuando el
  transcript supera ese número de tokens, independiente del modelo. Por
  defecto `0` (desactivado, usa porcentaje).
- `APEX_HANDOFF_THRESHOLD` (porcentaje, fallback): fracción [0, 1] aplicada
  sobre el límite de contexto detectado. Por defecto `0.40`.

Límite de contexto (para el % y el umbral relativo):

- `APEX_CONTEXT_LIMIT` (env): si se define, gana siempre (override explícito).
- Autodetección por modelo: lee el último `model` del transcript y lo mapea a
  su ventana real (`_MODEL_CONTEXT_LIMITS`). Opus → 1M, Sonnet/Haiku → 200K.
- Si no hay env ni modelo reconocible, cae a 200000.

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

# La raíz del repo debe estar en sys.path ANTES de `from lib.…`:
# el hook puede ejecutarse desde cualquier cwd.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from lib.hook_metrics import start_hook, end_hook

# 1 token ≈ 4 chars (aproximación coherente con lib/handoff.py)
_CHARS_PER_TOKEN = 4
_FALLBACK_CONTEXT_LIMIT = 200000

# Ventana de contexto real por familia de modelo. El match es por substring
# sobre el id (`claude-opus-4-8`, `claude-sonnet-5`, `claude-haiku-4-5-...`),
# así aguanta sufijos de fecha/variante sin tener que enumerarlos.
_MODEL_CONTEXT_LIMITS = (
    ("opus", 1000000),
    ("sonnet", 200000),
    ("haiku", 200000),
)

# Override explícito del env: si está, gana sobre la autodetección.
_ENV_CONTEXT_LIMIT = int(os.environ.get("APEX_CONTEXT_LIMIT", "0"))
_THRESHOLD = float(os.environ.get("APEX_HANDOFF_THRESHOLD", "0.40"))
_THRESHOLD_TOKENS = int(os.environ.get("APEX_HANDOFF_THRESHOLD_TOKENS", "0"))


def _measure_transcript(path: str) -> int:
    try:
        return Path(path).stat().st_size // _CHARS_PER_TOKEN
    except Exception:
        return 0


def _last_model(path: str) -> str:
    """Último `model` no vacío del transcript JSONL (lo escribe cada mensaje
    del asistente). Escanea de atrás hacia delante y para en el primero."""
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except Exception:
        return ""
    for line in reversed(lines):
        if '"model"' not in line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        model = obj.get("message", {}).get("model") or obj.get("model")
        if isinstance(model, str) and model and model != "<synthetic>":
            return model
    return ""


def _detect_context_limit(transcript_path: str) -> int:
    """Límite de contexto a usar: env explícito > modelo detectado > fallback."""
    if _ENV_CONTEXT_LIMIT > 0:
        return _ENV_CONTEXT_LIMIT
    model = _last_model(transcript_path).lower()
    for needle, limit in _MODEL_CONTEXT_LIMITS:
        if needle in model:
            return limit
    return _FALLBACK_CONTEXT_LIMIT


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

    context_limit = _detect_context_limit(transcript)

    if _THRESHOLD_TOKENS > 0:
        threshold_tokens = _THRESHOLD_TOKENS
    else:
        threshold_tokens = int(context_limit * _THRESHOLD)
    if tokens < threshold_tokens:
        end_hook("context-watch", _hook_start, exit_code=0)
        return 0

    pct = round(100 * tokens / context_limit, 1)
    session_id = payload.get("session_id", "")
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()

    if _THRESHOLD_TOKENS > 0:
        threshold_label = f"umbral absoluto {_THRESHOLD_TOKENS:,} tk"
    else:
        threshold_label = (
            f"{int(_THRESHOLD * 100)}% de {context_limit:,}"
        )
    sys.stdout.write(
        "\n"
        f"[apex context-watch] La sesión actual usa ~{tokens:,} tokens "
        f"(~{pct}% de {context_limit:,}, supera {threshold_label}). "
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
