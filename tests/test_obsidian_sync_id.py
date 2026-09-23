"""Los eventos del MCP van a `projects/<id>/log.md`, la carpeta que exporta apex-hub.

Antes el nombre salía de la meta `nombre`: libre (FeedbackIA, "APEX Hub") y, si
faltaba, todo caía en unknown-log.md. La nota del hub se llama por la carpeta,
así que un mismo proyecto acababa con dos nombres en el vault.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from test_handlers_not_stubbed import handlers, run  # noqa: F401  (fixture)


@pytest.fixture
def proyecto(tmp_path, monkeypatch):
    from context_db import ApexContextDB

    raiz = tmp_path / "Mi Proyecto"
    (raiz / ".apex").mkdir(parents=True)
    monkeypatch.chdir(raiz)
    db = ApexContextDB(str(raiz / ".apex" / "context.db"))
    asyncio.run(db.initialize())
    asyncio.run(db.set_meta("nombre", "Nombre Libre"))
    return db


def _logs():
    raiz = Path(os.environ["APEX_VAULT_DIR"]) / "projects"
    return {str(p.relative_to(raiz)): p.read_text(encoding="utf-8") for p in raiz.rglob("*.md")}


def test_decision_va_al_log_con_el_id_de_carpeta(handlers, proyecto):
    from apex_handlers.decisions import handle_apex_add_decision

    run(handle_apex_add_decision(proyecto, {
        "category": "stack", "decision": "Usar SQLite", "reasoning": "Un proceso"}))

    logs = _logs()
    assert list(logs) == ["mi-proyecto/log.md"]
    assert "Usar SQLite" in logs["mi-proyecto/log.md"]


def test_sin_meta_nombre_no_cae_en_unknown(handlers, proyecto):
    from apex_handlers.decisions import handle_apex_add_error

    run(proyecto.set_meta("nombre", ""))
    run(handle_apex_add_error(proyecto, {
        "source": "claude", "description": "Rompí algo", "lesson": "No romperlo"}))

    assert list(_logs()) == ["mi-proyecto/log.md"]


def test_mismo_id_que_el_hub(handlers):
    """La fórmula debe ser la de apex-hub/backend/scanner.py:_project_id_from_path."""
    from apex_handlers._common import vault_project_id

    assert vault_project_id("/home/v/RoadToDevOps/igRAG/.apex/context.db") == "igrag"
    assert vault_project_id("/x/Osyris Web/.apex/context.db") == "osyris-web"


def test_detecta_llamada_filtrada_y_no_menciones(handlers):
    """Formas reales de la fuga (2026-09-23) frente a texto legítimo que habla de ella."""
    from apex_handlers._common import leaked_call_markup

    assert leaked_call_markup({"reasoning": 'Motivo\n<parameter name="alternatives">Otra'}) == "reasoning"
    assert leaked_call_markup({"lesson": "Texto</lesson>\n</invoke>\n<invoke name=\"x\">"}) == "lesson"
    assert leaked_call_markup({"a": "ok", "phase": 3}) is None
    assert leaked_call_markup({"decision": 'El texto `<parameter name="alternatives">` rompía Obsidian'}) is None
