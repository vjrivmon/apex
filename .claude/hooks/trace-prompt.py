#!/usr/bin/env python3
"""APEX Sprint 15 — PostToolUse hook: tras un gate denso, pide registrar
una `reasoning_trace` (S15.3).

Triggers:
  - apex_set_phase con `phase_number` ∈ {1, 2, 3, 4, 9, 11}
  - apex_grader_evaluate con verdict bloqueante (texto contiene BLOQUEADO)
  - apex_doctor_run con propuestas (>=1)
  - apex_invalidate_decision (override)

Inyecta a stderr el `prompt_for_trace(category, gate_kind)` correspondiente.
NO bloquea.
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

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "lib"))

try:
    import reasoning_traces as _rt  # type: ignore
except Exception:
    _rt = None


PHASE_DELIBERATIVE = {1, 2, 3, 4, 9, 11}

# Mapeo fase → categoría para `apex_set_phase`. Las cuatro categorías de S15.
PHASE_CATEGORY = {
    1: "long_horizon_consequences",
    2: "multi_agent_coordination",
    3: "socratic_self_correction",
    4: "long_horizon_consequences",
    9: "cascading_failure_recovery",
    11: "cascading_failure_recovery",
}


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


def _category_for(tool: str, payload: dict) -> tuple[str, str] | None:
    args = payload.get("tool_input") or {}
    if tool == "mcp__apex__apex_set_phase":
        try:
            phase = int(args.get("phase_number", -1))
        except (TypeError, ValueError):
            return None
        if phase in PHASE_DELIBERATIVE:
            return PHASE_CATEGORY.get(phase, "socratic_self_correction"), "phase_close"
        return None
    if tool == "mcp__apex__apex_grader_evaluate":
        text = _response_text(payload)
        if "BLOQUEADO" in text or "should_block" in text.lower():
            return "cascading_failure_recovery", "grader_blocking"
        return None
    if tool == "mcp__apex__apex_doctor_run":
        text = _response_text(payload)
        if "propuesta" in text.lower():
            return "multi_agent_coordination", "doctor_proposal"
        return None
    if tool == "mcp__apex__apex_invalidate_decision":
        return "socratic_self_correction", "override"
    return None


def main() -> int:
    _hook_start = start_hook("trace-prompt")
    if _rt is None:
        end_hook("trace-prompt", _hook_start, exit_code=0)
        return 0
    try:
        payload = json.load(sys.stdin)
    except Exception:
        end_hook("trace-prompt", _hook_start, exit_code=0)
        return 0
    tool = payload.get("tool_name", "") or ""
    decision = _category_for(tool, payload)
    if decision is None:
        end_hook("trace-prompt", _hook_start, exit_code=0)
        return 0
    category, gate_kind = decision
    try:
        prompt = _rt.prompt_for_trace(category, gate_kind)
    except Exception:
        end_hook("trace-prompt", _hook_start, exit_code=0)
        return 0
    sys.stderr.write(f"[apex-trace] {prompt}\n")
    end_hook("trace-prompt", _hook_start, exit_code=0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
