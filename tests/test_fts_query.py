"""El retrieval cross-project no puede quedarse en AND implícito.

FTS5 hace AND implícito: `MATCH "a b c"` exige las tres palabras en la misma
fila. Pasando la consulta cruda, una pregunta natural ("memoria global
errores graves") devolvía 0 hits aunque la base tuviera las tres palabras
repartidas en 365 filas distintas.

Estos tests fijan la construcción de la consulta y, sobre una BD real con
el esquema de `hub.db`, que la consulta OR encuentra lo que la AND no.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from lib.fts_query import (  # noqa: E402
    FTS_STOPWORDS,
    build_fts_or_query,
    tokenize,
)


class TestTokenize:
    def test_trocea_y_pasa_a_minusculas(self):
        assert tokenize("Memoria Global") == ["memoria", "global"]

    def test_quita_puntuacion(self):
        assert tokenize("gitleaks: secrets, filtrados!") == [
            "gitleaks", "secrets", "filtrados",
        ]

    def test_no_repite(self):
        assert tokenize("error error error") == ["error"]

    def test_vacio(self):
        assert tokenize("") == []
        assert tokenize("   ") == []
        assert tokenize("!!!") == []

    def test_conserva_acentos_y_enie(self):
        assert tokenize("diseño eñes añejo") == ["diseño", "eñes", "añejo"]


class TestBuildOrQuery:
    def test_une_con_or(self):
        assert build_fts_or_query("memoria global") == "memoria OR global"

    def test_quita_stopwords(self):
        q = build_fts_or_query("el error de la memoria global")
        assert "el" not in q.split(" OR ")
        assert "error" not in q.split(" OR ")
        assert "memoria" in q and "global" in q

    def test_descarta_tokens_muy_cortos(self):
        """Si sólo hay stopwords, cae al token más largo del original.

        Es una consulta degenerada: no hay nada mejor que hacer que
        devolver algún término del original. Da igual cuál: lo que
        importa es que no se quede vacía y devuelva 0 hits para siempre.
        """
        q = build_fts_or_query("de la y a en")
        assert q in ("de", "la", "y", "a", "en")

    def test_si_solo_quedan_stopwords_cae_al_mas_largo(self):
        assert build_fts_or_query("el error la") == "error"

    def test_no_repite_tokens(self):
        assert build_fts_or_query("memoria memoria global") == "memoria OR global"

    def test_error_es_stopword(self):
        """'error' no discrimina: aparece en casi todas las filas de error.

        Por eso se quita: si no, cualquier consulta mentioning 'error'
        devolvería el mismo top-K.
        """
        assert "error" not in build_fts_or_query("error de memoria").split(" OR ")

    def test_consulta_vacia(self):
        assert build_fts_or_query("") == ""

    def test_no_deja_caracteres_que_fts5_rechace(self):
        q = build_fts_or_query('datos "mock" (hardcodeados) AND')
        for caracter in '()"':
            assert caracter not in q


class TestStopwords:
    def test_los_stopwords_de_ingles_estan_cubiertos(self):
        for palabra in ("the", "and", "or", "of", "in", "to", "a", "an"):
            assert palabra in FTS_STOPWORDS


class TestSobreHubReal:
    """La prueba que importa: contra el esquema real de hub.db."""

    @pytest.fixture
    def hub(self, tmp_path):
        """Mini hub.db con el esquema real de la tabla `hub_search`."""
        path = tmp_path / "hub.db"
        conn = sqlite3.connect(path)
        conn.execute(
            "CREATE VIRTUAL TABLE hub_search USING fts5("
            "content, source_type UNINDEXED, source_id UNINDEXED, project_id UNINDEXED)"
        )
        # Filas SEPARADAS: cada término en su fila, como pasa de verdad.
        # Éste es el caso que el AND implícito no puede cazar.
        conn.execute(
            "INSERT INTO hub_search (content, source_type, source_id, project_id) "
            "VALUES (?,?,?,?)",
            ("memoria global", "error", 1, "otro"),
        )
        conn.execute(
            "INSERT INTO hub_search (content, source_type, source_id, project_id) "
            "VALUES (?,?,?,?)",
            ("errores graves", "error", 2, "otro"),
        )
        conn.execute(
            "INSERT INTO hub_search (content, source_type, source_id, project_id) "
            "VALUES (?,?,?,?)",
            ("el filtro de gitleaks no funciona", "error", 3, "otro"),
        )
        conn.execute(
            "INSERT INTO hub_search (content, source_type, source_id, project_id) "
            "VALUES (?,?,?,?)",
            ("secretos filtrados en el commit", "error", 4, "otro"),
        )
        conn.commit()
        conn.close()
        return path

    def _hits(self, hub: Path, query: str) -> int:
        conn = sqlite3.connect(f"file:{hub}?mode=ro", uri=True)
        try:
            return conn.execute(
                "SELECT count(*) FROM hub_search WHERE hub_search MATCH ?", (query,)
            ).fetchone()[0]
        finally:
            conn.close()

    def test_and_implicito_no_encuentra_nada(self, hub):
        """El bug: los términos están en filas distintas."""
        assert self._hits(hub, "memoria global errores graves") == 0

    def test_la_consulta_or_si_lo_encuentra(self, hub):
        or_q = build_fts_or_query("memoria global errores graves")
        assert self._hits(hub, or_q) > 0

    def test_una_consulta_de_una_palabra_sigue_funcionando(self, hub):
        assert self._hits(hub, build_fts_or_query("gitleaks")) == 1

    def test_una_frase_exacta_sigue_encontrando(self, hub):
        assert self._hits(hub, build_fts_or_query("memoria global")) == 1
