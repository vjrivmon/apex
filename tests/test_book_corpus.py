"""Tests de la biblioteca de libros — esquema, indexación incremental y búsqueda.

Los tests que no necesitan Ollama sustituyen `embed_batch`/`embed_query` por
vectores deterministas, para poder verificar el ranking sin depender de la red.
Los que sí lo necesitan van marcados y se saltan si Ollama no responde.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

import book_corpus  # noqa: E402
from book_corpus import (  # noqa: E402
    EMBED_DIM,
    forget_book,
    index_book,
    library_db_path,
    list_books,
    search_books,
    slugify,
    sync_book,
)
from embeddings import health_check  # noqa: E402

_OLLAMA_OK, _OLLAMA_WHY = health_check()
requires_ollama = pytest.mark.skipif(
    not _OLLAMA_OK, reason=f"Ollama no disponible: {_OLLAMA_WHY}"
)

VAULT = Path(
    "/home/vicente/Documents/ApexVault/Building Applications with AI Agents"
)
requires_vault = pytest.mark.skipif(
    not VAULT.is_dir(), reason="bóveda no disponible"
)


@pytest.fixture
def db(tmp_path):
    """Una BD de biblioteca aislada por test."""
    return tmp_path / "library.db"


@pytest.fixture
def libro(tmp_path):
    """Un libro sintético de 2 capítulos."""
    root = tmp_path / "Libro de Prueba"
    (root / "Chapter 1").mkdir(parents=True)
    (root / "Chapter 2").mkdir(parents=True)
    (root / "Chapter 1" / "Primero.md").write_text(
        "# Vector Databases\n\n" + "Vectors encode meaning in dense space. " * 30,
        encoding="utf-8",
    )
    (root / "Chapter 2" / "Segundo.md").write_text(
        "# Agent Orchestration\n\n" + "Planner executor agents split work. " * 30,
        encoding="utf-8",
    )
    return root


@pytest.fixture
def fake_embed(monkeypatch):
    """Vectores deterministas: comparten dirección según palabras clave.

    Permite verificar que el ranking ordena por similitud sin llamar a Ollama.
    """
    def _vec(text: str) -> list[float]:
        t = text.lower()
        v = [0.0] * EMBED_DIM
        v[0] = 1.0 if "vector" in t else 0.0
        v[1] = 1.0 if "orchestration" in t or "planner" in t else 0.0
        v[2] = 0.05  # evita el vector nulo
        return v

    def fake_batch(texts, *, is_query=False):
        return [_vec(t) for t in texts]

    def fake_query(text):
        return _vec(text)

    monkeypatch.setattr(book_corpus, "embed_batch", fake_batch)
    monkeypatch.setattr(book_corpus, "embed_query", fake_query)


# ── Esquema ──

def test_schema_crea_tablas_e_indices(db):
    import sqlite3

    book_corpus._connect(db).close()
    con = sqlite3.connect(db)
    try:
        nombres = {
            r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','index')"
            )
        }
    finally:
        con.close()

    assert {"books", "book_chapters", "book_chunks"} <= nombres
    assert {"idx_bchunks_book", "idx_bchapters_book"} <= nombres


def test_ensure_schema_es_idempotente(db):
    for _ in range(3):
        book_corpus._connect(db).close()
    assert list_books(db) == []


def test_borrar_libro_no_deja_huerfanos(db, libro, fake_embed):
    """Sin PRAGMA foreign_keys=ON el CASCADE es decorativo. Este test lo prueba."""
    import sqlite3

    index_book(libro, "Libro de Prueba", db_path=db)
    assert forget_book("libro-de-prueba", db_path=db) is True

    con = sqlite3.connect(db)
    try:
        assert con.execute("SELECT count(*) FROM books").fetchone()[0] == 0
        assert con.execute("SELECT count(*) FROM book_chapters").fetchone()[0] == 0
        assert con.execute("SELECT count(*) FROM book_chunks").fetchone()[0] == 0
    finally:
        con.close()


def test_forget_book_devuelve_false_si_no_existe(db):
    assert forget_book("libro-inexistente", db_path=db) is False


def test_library_db_path_es_global():
    assert library_db_path() == Path.home() / ".apex" / "library.db"


def test_slugify():
    assert slugify("Building Applications with AI Agents") == (
        "building-applications-with-ai-agents"
    )
    assert slugify("¿Qué es esto?") == "qué-es-esto"
    assert slugify("") == "libro"


# ── Indexación ──

def test_indexar_escribe_capitulos_y_fragmentos(db, libro, fake_embed):
    r = index_book(libro, "Libro de Prueba", author="Autora", db_path=db)

    assert r.chapters_indexed == 2
    assert r.chapters_skipped == 0
    assert r.chunks_written > 0
    assert r.chunks_without_vector == 0

    libros = list_books(db)
    assert len(libros) == 1
    assert libros[0]["title"] == "Libro de Prueba"
    assert libros[0]["author"] == "Autora"
    assert libros[0]["chapters"] == 2


def test_reindexar_sin_cambios_no_toca_nada(db, libro, fake_embed, monkeypatch):
    """El caso que hace barato añadir un capítulo: cero llamadas a Ollama."""
    index_book(libro, "Libro de Prueba", db_path=db)

    llamadas = []
    original = book_corpus.embed_batch

    def contando(texts, *, is_query=False):
        llamadas.append(len(texts))
        return original(texts, is_query=is_query)

    monkeypatch.setattr(book_corpus, "embed_batch", contando)
    r = index_book(libro, "Libro de Prueba", db_path=db)

    assert r.chapters_indexed == 0
    assert r.chapters_skipped == 2
    assert llamadas == [], "no debía embeberse nada"


def test_capitulo_nuevo_solo_indexa_ese(db, libro, fake_embed):
    """Vicente añade el Capítulo 3: los otros dos no se tocan."""
    index_book(libro, "Libro de Prueba", db_path=db)

    (libro / "Chapter 3").mkdir()
    (libro / "Chapter 3" / "Tercero.md").write_text(
        "# Evaluation\n\n" + "Benchmarks measure agent quality. " * 30,
        encoding="utf-8",
    )
    r = index_book(libro, "Libro de Prueba", db_path=db)

    assert r.chapters_indexed == 1
    assert r.chapters_skipped == 2
    assert list_books(db)[0]["chapters"] == 3


def test_capitulo_modificado_se_reindexa(db, libro, fake_embed):
    index_book(libro, "Libro de Prueba", db_path=db)
    (libro / "Chapter 1" / "Primero.md").write_text(
        "# Vector Databases\n\n" + "Texto completamente distinto ahora. " * 30,
        encoding="utf-8",
    )
    r = index_book(libro, "Libro de Prueba", db_path=db)

    assert r.chapters_indexed == 1
    assert r.chapters_skipped == 1


def test_force_reindexa_todo(db, libro, fake_embed):
    index_book(libro, "Libro de Prueba", db_path=db)
    r = index_book(libro, "Libro de Prueba", db_path=db, force=True)

    assert r.chapters_indexed == 2
    assert r.chapters_skipped == 0


def test_reindexar_no_duplica_fragmentos(db, libro, fake_embed):
    r1 = index_book(libro, "Libro de Prueba", db_path=db)
    index_book(libro, "Libro de Prueba", db_path=db, force=True)
    assert list_books(db)[0]["chunks"] == r1.chunks_written


def test_numero_de_capitulo_se_extrae_de_la_ruta(db, libro, fake_embed):
    import sqlite3

    index_book(libro, "Libro de Prueba", db_path=db)
    con = sqlite3.connect(db)
    try:
        nums = sorted(
            r[0] for r in con.execute("SELECT chapter_number FROM book_chapters")
        )
    finally:
        con.close()
    assert nums == [1, 2]


def test_libro_sin_chapter_en_la_ruta_indexa_igual(db, tmp_path, fake_embed):
    """Otro libro no tendrá el layout 'Chapter N/'. Debe seguir siendo citable."""
    root = tmp_path / "Otro Libro"
    root.mkdir()
    (root / "Prologo.md").write_text(
        "# Intro\n\n" + "Contenido suficiente para un fragmento. " * 30,
        encoding="utf-8",
    )
    r = index_book(root, "Otro Libro", db_path=db)
    assert r.chapters_indexed == 1

    import sqlite3
    con = sqlite3.connect(db)
    try:
        fila = con.execute(
            "SELECT chapter_number, chapter_title FROM book_chapters"
        ).fetchone()
    finally:
        con.close()
    assert fila[0] is None          # sin número, pero
    assert fila[1] == "Prologo"     # con título: la cita degrada, no desaparece


def test_indexar_directorio_inexistente_falla_ruidosamente(db, tmp_path):
    with pytest.raises(ValueError, match="no es un directorio"):
        index_book(tmp_path / "no-existe", db_path=db)


def test_indexar_directorio_sin_markdown_falla(db, tmp_path):
    vacio = tmp_path / "vacio"
    vacio.mkdir()
    with pytest.raises(ValueError, match="no hay ficheros"):
        index_book(vacio, db_path=db)


def test_ollama_caido_guarda_fragmentos_sin_vector(db, libro, monkeypatch):
    """Fail loudly: se indexa igual, pero se reporta cuántos quedaron sin vector."""
    from embeddings import EmbeddingsUnavailable

    def caido(texts, *, is_query=False):
        raise EmbeddingsUnavailable("conexión rechazada")

    monkeypatch.setattr(book_corpus, "embed_batch", caido)
    r = index_book(libro, "Libro de Prueba", db_path=db)

    assert r.chunks_written > 0
    assert r.chunks_without_vector == r.chunks_written
    assert "conexión rechazada" in r.embed_error
    assert list_books(db)[0]["chunks_without_vector"] == r.chunks_written


# ── Sincronización automática ──

def test_sync_no_hace_nada_si_no_cambio_nada(db, libro, fake_embed):
    index_book(libro, "Libro de Prueba", db_path=db)
    assert sync_book(libro, "Libro de Prueba", db_path=db) is None


def test_sync_detecta_capitulo_nuevo(db, libro, fake_embed):
    index_book(libro, "Libro de Prueba", db_path=db)
    (libro / "Chapter 3").mkdir()
    (libro / "Chapter 3" / "Tercero.md").write_text(
        "# Nuevo\n\n" + "Contenido del capítulo recién añadido. " * 30,
        encoding="utf-8",
    )
    r = sync_book(libro, "Libro de Prueba", db_path=db)
    assert r is not None and r.chapters_indexed == 1


def test_sync_indexa_libro_nunca_visto(db, libro, fake_embed):
    r = sync_book(libro, "Libro de Prueba", db_path=db)
    assert r is not None and r.chapters_indexed == 2


def test_sync_detecta_capitulo_borrado(db, libro, fake_embed):
    index_book(libro, "Libro de Prueba", db_path=db)
    (libro / "Chapter 2" / "Segundo.md").unlink()
    assert sync_book(libro, "Libro de Prueba", db_path=db) is not None


def test_capitulo_borrado_desaparece_de_la_biblioteca(db, libro, fake_embed):
    """Regresión: la biblioteca no puede citar texto que ya no está en disco.

    Detectado en la demo real del 2026-07-21: borrar un capítulo dejaba sus
    fragmentos indexados y seguían apareciendo en las búsquedas.
    """
    index_book(libro, "Libro de Prueba", db_path=db)
    assert list_books(db)[0]["chapters"] == 2

    (libro / "Chapter 2" / "Segundo.md").unlink()
    r = index_book(libro, "Libro de Prueba", db_path=db)

    assert r.chapters_removed == 1
    assert list_books(db)[0]["chapters"] == 1

    # Y su contenido ya no se puede recuperar.
    pasajes, _ = search_books("orchestration planner", db_path=db, threshold=0.1)
    assert all("Orchestration" not in p.content for p in pasajes)


def test_capitulo_renombrado_no_se_duplica(db, libro, fake_embed):
    """Renombrar es borrar + crear: no debe dejar el viejo indexado."""
    index_book(libro, "Libro de Prueba", db_path=db)
    viejo = libro / "Chapter 2" / "Segundo.md"
    viejo.rename(viejo.parent / "Renombrado.md")

    index_book(libro, "Libro de Prueba", db_path=db)
    assert list_books(db)[0]["chapters"] == 2  # sigue habiendo 2, no 3


# ── Búsqueda ──

def test_busqueda_ordena_por_similitud(db, libro, fake_embed):
    index_book(libro, "Libro de Prueba", db_path=db)
    pasajes, diag = search_books(
        "vector", db_path=db, threshold=0.1, limit=5
    )
    assert pasajes, f"sin resultados: {diag}"
    assert "Vector" in pasajes[0].content
    assert pasajes[0].score >= pasajes[-1].score


def test_busqueda_bajo_umbral_devuelve_vacio_con_diagnostico(db, libro, fake_embed):
    """El caso crítico: el corpus no cubre la pregunta y hay que DECIRLO."""
    index_book(libro, "Libro de Prueba", db_path=db)
    pasajes, diag = search_books(
        "algo totalmente ajeno", db_path=db, threshold=0.99
    )
    assert pasajes == []
    assert diag["chunks"] > 0, "debía haber mirado el corpus"
    assert diag["best_score"] < 0.99
    assert diag["error"] == ""


def test_busqueda_filtra_por_libro(db, libro, tmp_path, fake_embed):
    index_book(libro, "Libro de Prueba", db_path=db)
    otro = tmp_path / "Otro"
    otro.mkdir()
    (otro / "Cap.md").write_text(
        "# Vector Stuff\n\n" + "Vector content elsewhere. " * 30, encoding="utf-8"
    )
    index_book(otro, "Otro", db_path=db)

    todos, _ = search_books("vector", db_path=db, threshold=0.1, limit=20)
    solo_uno, _ = search_books(
        "vector", book="Libro de Prueba", db_path=db, threshold=0.1, limit=20
    )
    assert {p.book_title for p in todos} == {"Libro de Prueba", "Otro"}
    assert {p.book_title for p in solo_uno} == {"Libro de Prueba"}


def test_busqueda_respeta_el_limite(db, libro, fake_embed):
    index_book(libro, "Libro de Prueba", db_path=db)
    pasajes, _ = search_books("vector", db_path=db, threshold=0.0, limit=2)
    assert len(pasajes) <= 2


def test_busqueda_vacia_no_llama_a_ollama(db):
    pasajes, diag = search_books("   ", db_path=db)
    assert pasajes == [] and diag["error"] == ""


def test_busqueda_con_ollama_caido_reporta_el_fallo(db, libro, monkeypatch):
    from embeddings import EmbeddingsUnavailable

    def caido(text):
        raise EmbeddingsUnavailable("conexión rechazada")

    monkeypatch.setattr(book_corpus, "embed_query", caido)
    pasajes, diag = search_books("lo que sea", db_path=db)

    assert pasajes == []
    assert "conexión rechazada" in diag["error"]


def test_vector_de_otra_dimension_se_descarta(db, libro, fake_embed):
    """Modelo cambiado bajo los pies: se detecta, no se devuelven resultados raros."""
    import sqlite3

    index_book(libro, "Libro de Prueba", db_path=db)
    con = sqlite3.connect(db)
    try:
        con.execute("UPDATE book_chunks SET embed_dim = 384")
        con.commit()
    finally:
        con.close()

    pasajes, diag = search_books("vector", db_path=db, threshold=0.0)
    assert pasajes == []
    assert diag["model_mismatch"] > 0


def test_cita_incluye_libro_capitulo_y_seccion(db, libro, fake_embed):
    index_book(libro, "Libro de Prueba", author="Autora", db_path=db)
    pasajes, _ = search_books("vector", db_path=db, threshold=0.1)
    cita = pasajes[0].citation()

    assert "Libro de Prueba" in cita
    assert "Cap. 1" in cita
    assert "Vector Databases" in cita


# ── Con Ollama y corpus reales ──

@requires_ollama
@requires_vault
def test_corpus_real_preguntas_en_espanol_encuentran_el_capitulo(db):
    """La prueba de fuego: las preguntas de Vicente, traducidas, aciertan.

    Verifica el requisito central — que APEX responda desde el libro. Si esto
    falla, la biblioteca no sirve por muy verdes que estén los demás tests.
    """
    index_book(VAULT, "Building Applications with AI Agents",
               author="Michael Albada", db_path=db)

    casos = [
        ("context window budget management token limits", 6),
        ("how to evaluate agent systems benchmarks", 2),
        ("when is fine-tuning a foundation model worth it", 7),
        ("GraphRAG knowledge graphs retrieval", 6),
        ("tool selection strategies for agents", 5),
    ]
    fallos = []
    for query, cap_esperado in casos:
        pasajes, diag = search_books(query, db_path=db, limit=3)
        caps = [p.chapter_number for p in pasajes]
        if cap_esperado not in caps:
            fallos.append(f"{query!r} -> {caps} (esperado {cap_esperado}, {diag})")

    assert not fallos, "consultas que no encontraron su capítulo:\n" + "\n".join(fallos)


@requires_ollama
@requires_vault
def test_corpus_real_pregunta_ajena_no_devuelve_nada(db):
    """Preguntas fuera del corpus deben quedar bajo umbral, no inventar."""
    index_book(VAULT, "Building Applications with AI Agents", db_path=db)

    for query in [
        "kubernetes ingress TLS certificate renewal",
        "sourdough bread recipe hydration",
        "spanish VAT tax declaration deadlines",
    ]:
        pasajes, diag = search_books(query, db_path=db)
        assert pasajes == [], (
            f"{query!r} devolvió {len(pasajes)} pasajes "
            f"(mejor score {diag['best_score']:.3f})"
        )


@requires_ollama
@requires_vault
def test_corpus_real_todos_los_fragmentos_tienen_vector(db):
    r = index_book(VAULT, "Building Applications with AI Agents", db_path=db)
    assert r.chapters_indexed == 7
    assert r.chunks_without_vector == 0
    assert r.embed_error == ""
