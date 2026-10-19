"""El índice FTS5 debe reflejar el estado real de los datos.

Dos fallos medidos el 2026-10-19 (y arrastrados desde la creación del
índice, nunca vistos porque nada los comprobaba):

1. **Una decisión invalidada seguía apareciendo en la búsqueda.**
   `invalidate_decision()` marcaba `invalid_from` en la tabla `decisions`
   pero no sacaba la fila del índice FTS5. `apex_search` seguía
   ofreciéndola al agente como si siguiera vigente — justo lo que el
   modelo temporal (invalid_from) debe impedir.

2. **Re-indexar duplicaba la fila.** `_index_fts()` insertaba a ciegas:
   volver a registrar la misma decisión (o reescribir la misma página de
   wiki) acumulaba filas y la búsqueda devolvía el mismo contenido N
   veces.

La lógica venía del commit `bce5bf6` de la rama sin fusionar.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from context_db import ApexContextDB  # noqa: E402


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.fixture
def db(tmp_path):
    path = tmp_path / ".apex" / "context.db"
    path.parent.mkdir(parents=True)
    db = ApexContextDB(str(path))
    run(db.initialize())
    return db


class TestDecisionInvalidada:
    def test_sale_del_indice_al_invalidarla(self, db):
        run(db.add_decision(category="arquitectura", decision="Usar SQLite",
                            reasoning="simple", phase=2))
        assert len(run(db.search("SQLite"))) == 1

        run(db.invalidate_decision(1, reason="cambió de opinión"))
        assert run(db.search("SQLite")) == [], (
            "la decisión invalidada sigue en el índice FTS: el agente la "
            "vería como vigente"
        )

    def test_una_decision_vigente_no_se_toca(self, db):
        run(db.add_decision(category="arquitectura", decision="Usar SQLite",
                            reasoning="simple", phase=2))
        run(db.add_decision(category="stack", decision="Usar Postgres",
                            reasoning="escala", phase=2))
        run(db.invalidate_decision(1, reason="cambió"))
        hits = run(db.search("Postgres"))
        assert len(hits) == 1

    def test_la_decision_sigue_en_la_tabla(self, db):
        """Sacarla del índice no es borrarla: el histórico se conserva."""
        run(db.add_decision(category="arquitectura", decision="Usar SQLite",
                            reasoning="simple", phase=2))
        run(db.invalidate_decision(1, reason="cambió"))
        activas = run(db.get_active_decisions())
        assert not any(d["decision"] == "Usar SQLite" for d in activas)


class TestReindexarNoDuplica:
    def test_la_misma_pagina_de_wiki_no_se_duplica(self, db):
        run(db.add_wiki_page("conceptos/alpha", "Alpha", "contenido alpha"))
        run(db.add_wiki_page("conceptos/alpha", "Alpha", "contenido alpha"))
        assert len(run(db.search("alpha"))) == 1

    def test_reindexar_el_mismo_id_no_duplica(self, db):
        """El índice se identifica por (source, source_id).

        Re-indexar la MISMA decisión (el mismo id) debe reemplazar la fila,
        no añadir otra. Es lo que pasa al reescribir una página de wiki o al
        reindexar una decisión ya existente.
        """
        run(db.add_decision(category="arquitectura", decision="Usar SQLite",
                            reasoning="simple", phase=2))
        async def _reindexar(contenido: str):
            async with db._conn() as c:
                await db._index_fts(c, contenido, "decision", 1)

        run(_reindexar("Usar SQLite\nsimple"))
        run(_reindexar("Usar SQLite\nversion corregida"))
        hits = run(db.search("SQLite"))
        assert len(hits) == 1
        assert "corregida" in hits[0]["content"]

    def test_reindexar_con_otro_contenido_reemplaza(self, db):
        run(db.add_wiki_page("conceptos/beta", "Beta", "version vieja"))
        run(db.add_wiki_page("conceptos/beta", "Beta", "version nueva"))
        hits = run(db.search("version"))
        assert len(hits) == 1
        assert "nueva" in hits[0]["content"]


class TestCleanupFts:
    def test_repara_duplicados_y_decisiones_invalidadas(self, db):
        """Repara una BD que ya está contaminada (pase one-shot)."""
        # Contaminación a mano: la fila duplicada y la decisión invalidada
        # que quedaron en el índice antes de la corrección.
        run(db.add_decision(category="arquitectura", decision="Usar SQLite",
                            reasoning="simple", phase=2))
        run(db.invalidate_decision(1, reason="cambió"))
        async def _ensuciar():
            async with db._conn() as c:
                await c.execute(
                    "INSERT INTO context_fts (content, source, source_id) "
                    "VALUES (?,?,?)", ("Usar SQLite", "decision", "1"))
                await c.execute(
                    "INSERT INTO context_fts (content, source, source_id) "
                    "VALUES (?,?,?)", ("Usar SQLite", "decision", "1"))
                await c.commit()
        run(_ensuciar())

        stats = run(db.cleanup_fts())
        assert stats["dedup"] >= 1
        assert stats["invalidated"] >= 1
        assert run(db.search("SQLite")) == []

    def test_es_idempotente(self, db):
        run(db.add_decision(category="arquitectura", decision="Usar SQLite",
                            reasoning="simple", phase=2))
        run(db.cleanup_fts())
        segunda = run(db.cleanup_fts())
        assert segunda == {"dedup": 0, "invalidated": 0}
