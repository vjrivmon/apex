"""Tests del chunker de libros — verificados contra el corpus real.

Los asertos usan cadenas literales de los 7 capítulos de "Building Applications
with AI Agents" para que una regresión real (partir por un comentario de Python,
separar una fila de tabla de su cabecera) haga fallar el test.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from book_chunker import (  # noqa: E402
    MAX_CHUNK_CHARS,
    MIN_CHUNK_CHARS,
    chunk_markdown,
    chunk_text,
)

VAULT = Path(
    "/home/vicente/Documents/ApexVault/Building Applications with AI Agents"
)
requires_vault = pytest.mark.skipif(
    not VAULT.is_dir(), reason="bóveda no disponible en esta máquina"
)


# ── Reglas de troceado (unitarios, sin bóveda) ──

def test_comentario_python_en_fence_no_es_heading():
    """El fallo que parte un capítulo por la mitad.

    '# pip install rank_bm25' es un comentario dentro de un bloque de código
    (Cap. 6, línea 35). Si se tomara por heading, la cita apuntaría a una
    sección inexistente.
    """
    text = (
        "# Traditional Full-Text Search\n\n"
        "BM25 weights each passage by term frequency.\n\n"
        "```python\n"
        "# pip install rank_bm25\n"
        "from rank_bm25 import BM25Okapi\n"
        "```\n\n"
        "In this example, we built a simple BM25-powered index.\n"
    )
    chunks = chunk_text(text)
    paths = {c.heading_path for c in chunks}

    assert paths == {"Traditional Full-Text Search"}
    assert not any("pip install" in p for p in paths)
    joined = "\n".join(c.content for c in chunks)
    assert "# pip install rank_bm25" in joined  # el texto se conserva


def test_heading_tras_cerrar_fence_si_cuenta():
    """Cerrado el bloque, un '#' vuelve a ser heading."""
    text = (
        "# GraphRAG\n\n"
        + "Knowledge graphs encode entities and relations. " * 20
        + "\n\n```\n# not a heading\n```\n\n"
        "## Using Knowledge Graphs\n\n"
        + "Traversing the graph retrieves connected facts. " * 20
    )
    paths = {c.heading_path for c in chunk_text(text)}
    assert "GraphRAG > Using Knowledge Graphs" in paths


def test_heading_path_es_jerarquico():
    text = (
        "# Foundational Approaches to Memory\n\n"
        + "We begin with the simplest approaches. " * 20
        + "\n\n## Managing Context Windows\n\n"
        + "The context window is the working memory for a request. " * 20
    )
    paths = [c.heading_path for c in chunk_text(text)]
    assert "Foundational Approaches to Memory > Managing Context Windows" in paths


def test_h2_hermanos_no_se_anidan():
    """Un H2 sustituye al H2 previo en la pila, no se apila bajo él."""
    text = (
        "# Memory\n\n" + "Intro. " * 20
        + "\n\n## Short-Term Memory\n\n" + "Recent turns. " * 20
        + "\n\n## Long-Term Memory\n\n" + "Durable facts. " * 20
    )
    paths = {c.heading_path for c in chunk_text(text)}
    assert "Memory > Long-Term Memory" in paths
    assert not any("Short-Term Memory > Long-Term" in p for p in paths)


def test_tabla_no_se_separa_de_su_cabecera():
    """Una fila sin cabecera es ilegible y su embedding, ruido."""
    filler = "Model comparison across benchmarks. " * 60
    table = (
        "|Model|Maintainer|MMLU|\n"
        "|---|---|---|\n"
        "|Llama 3.1 Instruct Turbo|Meta|0.68|\n"
        "|Claude 3.7 Sonnet|Anthropic|0.80|\n"
    )
    text = f"# Model Selection\n\n{filler}\n\n{table}\n"
    chunks = chunk_text(text)
    con_fila = [c for c in chunks if "Llama 3.1 Instruct Turbo" in c.content]
    assert con_fila, "la fila de la tabla desapareció"
    assert "|Model|Maintainer|MMLU|" in con_fila[0].content


def test_secciones_cortas_NO_se_funden_entre_headings_distintos():
    """La citabilidad manda sobre el tamaño.

    Fundir 'A' con 'B' produciría un fragmento que no puede atribuirse a
    ninguna de las dos secciones. Antes corto que sin procedencia.
    """
    text = (
        "# A\n\nUna línea corta.\n\n"
        "# B\n\nOtra línea corta.\n\n"
        "# C\n\nY una tercera.\n"
    )
    chunks = chunk_text(text)
    assert len(chunks) == 3
    assert [c.heading_path for c in chunks] == ["A", "B", "C"]


def test_colas_del_mismo_heading_si_se_funden():
    """Dentro de un heading, una cola breve se pega a su hermana.

    Aquí sí es correcto: ambos fragmentos vienen de la misma sección, así que
    la cita no se falsea.
    """
    long_section = "Semantic retrieval maps text into a vector space. " * 200
    text = f"# Semantic Memory\n\n{long_section}\n\nCola breve final.\n"
    chunks = chunk_text(text)

    assert len(chunks) > 1, "la sección debía partirse"
    assert {c.heading_path for c in chunks} == {"Semantic Memory"}
    # Todos por debajo del máximo: el párrafo gigante se cortó por frase.
    assert all(len(c.content) <= MAX_CHUNK_CHARS for c in chunks)
    # La cola conserva su procedencia aunque quede corta: fundirla con el
    # fragmento anterior (2449 ch) desbordaría el máximo.
    assert "Cola breve final." in chunks[-1].content


def test_cola_corta_se_funde_si_cabe():
    """Cuando el hermano anterior tiene hueco, la cola sí se funde."""
    text = "# Sección\n\n" + "Frase de relleno. " * 30 + "\n\nBreve.\n"
    chunks = chunk_text(text)
    assert len(chunks) == 1
    assert "Breve." in chunks[0].content


def test_seq_es_consecutivo_desde_cero():
    text = "".join(
        f"# H{i}\n\n" + "Contenido suficientemente largo. " * 40 + "\n\n"
        for i in range(4)
    )
    chunks = chunk_text(text)
    assert [c.seq for c in chunks] == list(range(len(chunks)))


def test_texto_vacio_no_produce_chunks():
    assert chunk_text("") == []
    assert chunk_text("\n\n   \n") == []


def test_texto_sin_headings_produce_chunk_con_path_vacio():
    """El Cap. 6 abre con varios párrafos antes del primer heading."""
    text = "Now that your agent has tools and orchestration. " * 30
    chunks = chunk_text(text)
    assert len(chunks) >= 1
    assert chunks[0].heading_path == ""
    assert "Now that your agent" in chunks[0].content


# ── Contra el corpus real ──

@requires_vault
def test_corpus_real_recuento_y_limites():
    """Propiedades del troceado sobre el corpus real.

    No fijamos un conteo exacto (dependería de los parámetros de tamaño), sino
    propiedades que deben cumplirse sea cual sea el ajuste: cada capítulo
    produce fragmentos, ninguno vacío, y ninguno desbocado.
    """
    por_capitulo = {
        md.parent.name: chunk_markdown(md)
        for md in sorted(VAULT.glob("*/*.md"))
    }
    todos = [c for cs in por_capitulo.values() for c in cs]

    assert len(por_capitulo) == 7, "deben verse los 7 capítulos"
    assert all(cs for cs in por_capitulo.values()), "un capítulo sin fragmentos"
    assert all(c.content.strip() for c in todos), "hay fragmentos vacíos"
    assert 150 <= len(todos) <= 400, f"conteo implausible: {len(todos)}"

    # El máximo es un límite blando: se permite superarlo sólo cuando el
    # fragmento es una frase única que no puede cortarse sin romperla.
    desbocados = [c for c in todos if len(c.content) > MAX_CHUNK_CHARS * 1.5]
    assert not desbocados, (
        f"{len(desbocados)} fragmentos desbocados, mayor="
        f"{max((len(c.content) for c in desbocados), default=0)}"
    )


@requires_vault
def test_corpus_real_ningun_heading_es_comentario_de_codigo():
    """Los 3 falsos headings del corpus real no aparecen como sección."""
    falsos = [
        "pip install rank_bm25",           # Cap. 6:35
        "Load DPO dataset with ranked pairs",  # Cap. 7:294
        "Initialize the LLM",              # Cap. 5:151
        "Minimal evaluation check",        # Cap. 2:35
        "4️⃣ Trainer",                      # Cap. 7:300
    ]
    for md in sorted(VAULT.glob("*/*.md")):
        for c in chunk_markdown(md):
            for falso in falsos:
                assert falso not in c.heading_path, (
                    f"{md.name}: comentario de código tomado por heading "
                    f"en {c.heading_path!r}"
                )


@requires_vault
def test_corpus_real_headings_reales_si_aparecen():
    """Secciones que deben existir tras el troceado, una por capítulo."""
    esperados = {
        "Introduction to Agents.md": "Agentic Frameworks > LangGraph",
        "Knowledge and Memory.md": "GraphRAG > Building Knowledge Graphs",
        "Tool Use.md": "LangChain Fundamentals > Model Context Protocol",
        "Learning in Agentic Systems.md": (
            "Parametric Learning: Fine-Tuning > Direct Preference Optimization"
        ),
    }
    for nombre, path_esperado in esperados.items():
        matches = list(VAULT.glob(f"*/{nombre}"))
        assert matches, f"no encontrado: {nombre}"
        paths = {c.heading_path for c in chunk_markdown(matches[0])}
        assert path_esperado in paths, (
            f"{nombre}: falta {path_esperado!r}. Presentes: {sorted(paths)[:8]}"
        )


@requires_vault
def test_corpus_real_contenido_contiguo_no_se_separa():
    """'Scalability' y 'cumbersome' están en la misma sección del Cap. 4."""
    md = next(VAULT.glob("*/Tool Use.md"))
    chunks = chunk_markdown(md)
    con_scalability = [c for c in chunks if "Scalability" in c.content]
    assert con_scalability, "'Scalability' desapareció del Cap. 4"


@requires_vault
def test_corpus_real_no_pierde_texto():
    """Sanidad global: el troceado conserva TODO el texto del capítulo.

    Incluidos los headings, que van en el cuerpo del chunk además de en el
    heading_path. Comparamos caracteres no-espacio porque el troceado
    normaliza los saltos de línea.
    """
    for md in sorted(VAULT.glob("*/*.md")):
        original = md.read_text(encoding="utf-8")
        troceado = "\n".join(c.content for c in chunk_markdown(md))
        orig_n = len("".join(original.split()))
        troz_n = len("".join(troceado.split()))
        assert troz_n >= orig_n, (
            f"{md.name}: se perdió texto ({troz_n} vs {orig_n})"
        )
