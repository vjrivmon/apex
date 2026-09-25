"""El gate de entrada nunca veía la fase anterior.

Leía `p["phase_number"]`, pero `get_all_phases` devuelve la clave `number`: el
KeyError lo tragaba un `except` y el gate decía siempre «estado desconocido»,
también con la fase anterior cerrada (TeamLens, fase 9, 25/09/2026).
"""
from __future__ import annotations

import asyncio

import pytest

from test_handlers_not_stubbed import handlers, run  # noqa: F401  (fixture)


@pytest.fixture
def proyecto(tmp_path, monkeypatch):
    from context_db import ApexContextDB

    raiz = tmp_path / "proyecto"
    (raiz / ".apex").mkdir(parents=True)
    monkeypatch.chdir(raiz)
    db = ApexContextDB(str(raiz / ".apex" / "context.db"))
    asyncio.run(db.initialize())
    return db


def test_el_gate_ve_la_fase_anterior_cerrada(handlers, proyecto):
    from apex_handlers.phase_gate import handle_apex_phase_entry_check
    from apex_handlers.context import handle_apex_set_phase

    run(handle_apex_set_phase(proyecto, {"phase_number": 8, "status": "completed", "force": True, "force_reason": "test"}))
    salida = run(handle_apex_phase_entry_check(proyecto, {"phase": 9}))[0].text

    assert "Fase 8: completed" in salida


def test_el_gate_avisa_si_la_fase_anterior_sigue_abierta(handlers, proyecto):
    from apex_handlers.phase_gate import handle_apex_phase_entry_check

    salida = run(handle_apex_phase_entry_check(proyecto, {"phase": 9}))[0].text

    assert "Fase 8 esta en estado 'pending'" in salida
