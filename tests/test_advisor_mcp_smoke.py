"""Sprint 15 S15.4 — smoke tests para el wiring MCP de las 6 tools nuevas.

Importa `apex_server` vía importlib (no contamina sys.path con `mcp/`) y
ejerce list_tools() + cada dispatcher con monkeypatch.chdir(tmp_path).
"""
from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
from pathlib import Path

import pytest

# Para que los lib imports del propio apex_server resuelvan
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

_APEX_SERVER_PATH = (
    Path(__file__).resolve().parent.parent / "mcp" / "apex_server.py"
)


@pytest.fixture(scope="module")
def apex_server_mod():
    spec = importlib.util.spec_from_file_location(
        "apex_server_under_test", str(_APEX_SERVER_PATH)
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.fixture
def project_root(tmp_path, monkeypatch):
    """tmp_path con .apex/ inicializada y CWD apuntando ahí."""
    (tmp_path / ".apex").mkdir()
    monkeypatch.chdir(tmp_path)
    # Inicializa context.db con el schema actual (incluye S15)
    from context_db import ApexContextDB
    db = ApexContextDB(str(tmp_path / ".apex" / "context.db"))
    run(db.initialize())
    return tmp_path


# ── 1. list_tools incluye las 6 nuevas ───────────────────────────

def test_list_tools_includes_new_six(apex_server_mod):
    tools = run(apex_server_mod.list_tools())
    names = {t.name for t in tools}
    expected = {
        "apex_advisor_review",
        "apex_record_advice",
        "apex_dismiss_advice",
        "apex_log_trace",
        "apex_handoff_skill",
        "apex_resume_skill_handoff",
    }
    missing = expected - names
    assert not missing, f"missing tools in list_tools(): {missing}"


# ── 2-7. Smoke por dispatcher ────────────────────────────────────

def test_advisor_review_dispatcher_skipped(apex_server_mod, project_root):
    res = run(apex_server_mod.call_tool(
        "apex_advisor_review",
        {"session_id": "s1", "force": False},
    ))
    text = res[0].text
    # Sin tool calls, count=0, debería disparar min_calls_not_reached
    assert "SKIPPED" in text or "skipped" in text.lower() or "min_calls" in text


def test_advisor_review_dispatcher_force_creates_review(apex_server_mod, project_root):
    res = run(apex_server_mod.call_tool(
        "apex_advisor_review",
        {"session_id": "s1", "force": True, "trigger": "manual"},
    ))
    text = res[0].text
    assert "advisor_review" in text and "creado" in text


def test_record_advice_dispatcher(apex_server_mod, project_root):
    # Crear review primero
    run(apex_server_mod.call_tool(
        "apex_advisor_review",
        {"session_id": "s1", "force": True, "trigger": "manual"},
    ))
    # Sabemos que es review_id=1 (BD limpia)
    res = run(apex_server_mod.call_tool(
        "apex_record_advice",
        {
            "review_id": 1,
            "kind": "phase_drift",
            "severity": "warn",
            "title": "Llevas 12 calls sin grader",
            "body": "Fase 5 lleva 30 minutos in_progress sin verdict.",
            "evidence_refs": ["phase=5"],
        },
    ))
    text = res[0].text
    assert "advice" in text and "registrada" in text


def test_dismiss_advice_dispatcher(apex_server_mod, project_root):
    run(apex_server_mod.call_tool(
        "apex_advisor_review",
        {"session_id": "s1", "force": True, "trigger": "manual"},
    ))
    run(apex_server_mod.call_tool(
        "apex_record_advice",
        {
            "review_id": 1, "kind": "phase_drift", "severity": "warn",
            "title": "T", "body": "B", "evidence_refs": [],
        },
    ))
    res = run(apex_server_mod.call_tool(
        "apex_dismiss_advice",
        {"advice_id": 1, "reason": "no aplica en esta fase"},
    ))
    text = res[0].text
    assert "descartada" in text


def test_log_trace_dispatcher(apex_server_mod, project_root):
    deliberation = (
        "Decidí cerrar la fase porque el grader devolvió quality 3/4 sin issues "
        "bloqueantes y la suite completa pasó verde. Consideré bajar a 2/4 por "
        "el code-smell del módulo X, pero los issues no son bloqueantes y la "
        "siguiente fase requiere avanzar. La alternativa de partir el sprint "
        "fue rechazada porque no hay solapamiento con otro equipo y el doctor "
        "no señaló stale_handoffs."
    )
    res = run(apex_server_mod.call_tool(
        "apex_log_trace",
        {
            "session_id": "s1",
            "phase": 8,
            "category": "cascading_failure_recovery",
            "gate_kind": "phase_close",
            "deliberation": deliberation,
            "calibration_confidence": 0.75,
            "calibration_text": "75% por el code-smell pendiente",
            "alternatives_considered": [
                {"option": "partir sprint", "rejected_because": "no hay solapamiento"},
            ],
        },
    ))
    text = res[0].text
    assert "reasoning_trace" in text and "registrada" in text


def test_handoff_skill_create_and_resume(apex_server_mod, project_root):
    res1 = run(apex_server_mod.call_tool(
        "apex_handoff_skill",
        {
            "session_id": "s1",
            "from_skill": "grill-with-docs",
            "to_skill": "prototype",
            "reason": "validar state machine del checkout",
            "snapshot": {"open_questions": ["¿qué guard usa el cancelar?"]},
        },
    ))
    text1 = res1[0].text
    assert "skill_handoff" in text1 and "creado" in text1

    res2 = run(apex_server_mod.call_tool(
        "apex_resume_skill_handoff",
        {"handoff_id": 1, "result_summary": "state machine validada"},
    ))
    text2 = res2[0].text
    assert "retomado" in text2
    assert "grill-with-docs" in text2
