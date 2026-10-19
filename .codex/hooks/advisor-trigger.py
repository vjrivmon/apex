#!/usr/bin/env python3
"""APEX Sprint 15 — PostToolUse hook: dispara reviews del Advisor.

Cuenta tool calls en project_meta.advisor_tool_count y, cuando se cumple el
intervalo (default 8) o se da un force trigger (apex_set_phase, grader
bloqueante, error critical/high), crea una fila advisor_reviews(pending) y
emite a stderr un mensaje pidiendo invocar `Task(subagent_type='apex-advisor')`.

Ciclo de vida del review (Sprint 15/16, arreglado 2026-10-19):

- Antes de abrir un review nuevo se cierra el que hubiera pendiente: la
  fila se queda 'pending' si el subagente no ha hablado y se cierra con
  su conteo real cuando ya no puede emitir más cards.
- Un review con advice cards no se cierra en caliente: se espera una
  ventana de asentamiento (ADVISOR_SETTLE_SEC) desde la última card.
- Un review pending sin cards se cierra como 'skipped' tras la ventana de
  gracia (ADVISOR_GRACE_SEC): así el circuit breaker ve los reviews vacíos.
- Los reviews pending más viejos que ADVISOR_STALE_REVIEW_SEC se podan
  como 'abandoned' (reparación idempotente de la basura histórica).
- Mientras hay un review abierto NO se abre otro: sin este guard se
  acumulaba un review por cada tool call (7269 filas 'pending' en la
  auditoría del 2026-10-19).

NO llama al modelo. NO bloquea. Si algo falla, exit 0 silencioso (mejor
ruido que un hook que rompe la sesión).
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

# La raíz del repo debe estar en sys.path ANTES de `from lib.…`:
# el hook puede ejecutarse desde cualquier cwd.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from lib.hook_metrics import start_hook, end_hook

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "lib"))

try:
    import advisor as _advisor  # type: ignore
except Exception:
    _advisor = None

# Tools cuya invocación NO se cuenta (evita bucles + ruido).
SKIP_TOOLS = {
    "mcp__apex__apex_advisor_review",
    "mcp__apex__apex_record_advice",
    "mcp__apex__apex_dismiss_advice",
    "mcp__apex__apex_archive_output",
    "mcp__apex__apex_get_archived",
    "mcp__apex__apex_skill_forge_scan",
    "mcp__apex__apex_skill_forge_approve",
    "mcp__apex__apex_skill_forge_reject",
}

# Tools que disparan force trigger (ignoran throttle).
FORCE_TOOLS = {
    "mcp__apex__apex_set_phase",
    "mcp__apex__apex_grader_evaluate",
    "mcp__apex__apex_add_error",
}

TIMEOUT_S = float(os.environ.get("APEX_ADVISOR_HOOK_TIMEOUT_S", "2.0"))


# La raiz del proyecto la resuelve lib/project_root.py, la implementacion UNICA.
# Antes cada hook traia su propia copia, con reglas distintas: seis de ellas
# no cortaban al llegar al home y resolvian ~/.apex/context.db (memoria global)
# como si fuera el contexto de un proyecto.
from lib.project_root import find_project_root as _find_project_root


def _response_text(payload: dict) -> str:
    resp = payload.get("tool_response") or payload.get("output") or ""
    if isinstance(resp, str):
        return resp
    if isinstance(resp, dict):
        content = resp.get("content")
        if isinstance(content, list):
            return "".join(str(c.get("text", c)) for c in content)
        return str(content or resp)
    return str(resp)


def _is_force_trigger(tool: str, payload: dict) -> bool:
    if tool not in FORCE_TOOLS:
        return False
    if tool == "mcp__apex__apex_grader_evaluate":
        text = _response_text(payload)
        return "BLOQUEADO" in text or "should_block" in text.lower()
    if tool == "mcp__apex__apex_add_error":
        sev = (payload.get("tool_input") or {}).get("severity", "")
        return sev in {"critical", "high"}
    return True  # apex_set_phase: siempre force


def main() -> int:
    _hook_start = start_hook("advisor-trigger")
    if _advisor is None:
        end_hook("advisor-trigger", _hook_start, exit_code=0)
        return 0
    t0 = time.monotonic()
    try:
        payload = json.load(sys.stdin)
    except Exception:
        end_hook("advisor-trigger", _hook_start, exit_code=0)
        return 0
    tool = payload.get("tool_name", "") or ""
    cwd = Path(payload.get("cwd") or os.getcwd())
    root = _find_project_root(cwd)
    if root is None:
        end_hook("advisor-trigger", _hook_start, exit_code=0)
        return 0
    db_path = root / ".apex" / "context.db"
    if not db_path.exists():
        end_hook("advisor-trigger", _hook_start, exit_code=0)
        return 0
    session_id = (
        payload.get("session_id")
        or os.environ.get("APEX_SESSION_ID")
        or "unknown"
    )

    try:
        # 1. Reparación idempotente: podar los reviews 'pending'
        #    huérfanos (basura histórica acumulada).
        _advisor.reap_stale_reviews(str(db_path))
        # 2. Cerrar los reviews que ya están listos (de cualquier
        #    sesión: uno de una sesión anterior no puede quedar
        #    abierto para siempre). Es donde se resetea `tool_count` y
        #    se actualiza el circuit breaker.
        _advisor.close_ready_reviews(str(db_path))
        force = _is_force_trigger(tool, payload)
        pendientes = _advisor.pending_reviews(str(db_path), session_id)
        if pendientes and force:
            # Un force trigger invalida el review en curso.
            for p in pendientes:
                _advisor.close_review(str(db_path), p["id"])
            pendientes = []
        if tool in SKIP_TOOLS:
            end_hook("advisor-trigger", _hook_start, exit_code=0)
            return 0
        _advisor.increment_tool_count(str(db_path))
        run_, reason = _advisor.should_run(str(db_path), force=force)
        if not run_:
            end_hook("advisor-trigger", _hook_start, exit_code=0)
            return 0
        if pendientes:
            # Ya hay un review abierto en esta sesión: no se apila otro
            # (esto era el flood de 7269 reviews 'pending').
            end_hook("advisor-trigger", _hook_start, exit_code=0)
            return 0
        bundle = _advisor.build_bundle(str(db_path), session_id)
        tokens = _advisor.estimate_bundle_tokens(bundle)
        trigger_kind = "force" if force else "tool_count"
        rid = _advisor.record_review(
            str(db_path), session_id, trigger_kind,
            bundle_size_tokens=tokens,
        )
    except Exception as e:
        sys.stderr.write(f"[apex-advisor] hook error: {e}\n")
        end_hook("advisor-trigger", _hook_start, exit_code=0)
        return 0

    elapsed_ms = (time.monotonic() - t0) * 1000
    if elapsed_ms > TIMEOUT_S * 1000:
        sys.stderr.write(
            f"[apex-advisor] hook tardó {elapsed_ms:.0f}ms "
            f"(timeout objetivo {TIMEOUT_S * 1000:.0f}ms)\n"
        )

    sys.stderr.write(
        f"[apex-advisor] advisor_review #{rid} pendiente "
        f"(trigger={trigger_kind}, bundle≈{tokens}tok, {reason}).\n"
        f"  Invoca Task(subagent_type='apex-advisor', "
        f"prompt='review_id={rid}; session_id={session_id}; lee bundle "
        f"vía apex_get_context y apex_search'). MAX, no API.\n"
        f"  El review se cierra solo cuando el subagente termine "
        f"(o se poda por antigüedad).\n"
    )
    end_hook("advisor-trigger", _hook_start, exit_code=0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
