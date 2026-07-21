"""APEX MCP handler: biblioteca de libros técnicos.

A diferencia del resto de handlers, estos NO reciben un `db` de proyecto: la
biblioteca vive en `~/.apex/library.db` y se consulta desde cualquier
directorio, con o sin `.apex/`. El dispatcher los despacha antes de construir
`db` (ver `LIBRARY_TOOLS` en `apex_server.py`).
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from mcp.types import TextContent

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

import book_corpus  # noqa: E402

# Tools que no requieren proyecto APEX.
LIBRARY_TOOLS = frozenset({
    "apex_book_search", "apex_book_index", "apex_book_list",
})


def _render_passages(pasajes: list, diag: dict, query: str, sync_note: str) -> str:
    """Formatea los pasajes con su cita. El texto va VERBATIM del libro."""
    if diag.get("error"):
        return (
            f"No se pudo consultar la biblioteca: {diag['error']}\n\n"
            "Dilo explícitamente al usuario. NO respondas como si hubieras "
            "consultado el libro."
        )

    if not pasajes:
        libros = diag.get("books", 0)
        if libros == 0:
            return (
                "La biblioteca está vacía: no hay ningún libro indexado.\n"
                "Usa apex_book_index(path=...) para añadir uno."
            )
        return (
            f"Sin pasajes relevantes para {query!r}\n"
            f"({libros} libro(s), {diag.get('chunks', 0)} fragmentos consultados; "
            f"mejor similitud {diag.get('best_score', 0.0):.2f} < umbral "
            f"{diag.get('threshold', 0.0):.2f}).\n\n"
            "La biblioteca NO cubre este tema. Dilo explícitamente al usuario. "
            "Si respondes desde tu conocimiento propio, avisa de que NO viene "
            "de sus libros."
        )

    lineas = [
        f"Biblioteca — {len(pasajes)} pasaje(s) para {query!r} "
        f"({diag.get('books', 0)} libro(s), {diag.get('chunks', 0)} fragmentos):"
    ]
    if sync_note:
        lineas.append(sync_note)
    for p in pasajes:
        lineas.append(f"\n### [{p.citation()}] ({p.score:.2f})")
        lineas.append(p.content)
        lineas.append(f"   (fuente: {p.rel_path})")

    autores = {p.book_author for p in pasajes if p.book_author}
    titulos = {p.book_title for p in pasajes}
    if autores:
        lineas.append(
            f"\nFuente: {', '.join(sorted(autores))} — "
            f"{', '.join(sorted(titulos))}."
        )
    lineas.append(
        "\nResponde SOLO con estos pasajes. Si no bastan, dilo en vez de "
        "completar con conocimiento propio sin avisar."
    )
    return "\n".join(lineas)


async def handle_apex_book_index(db: Any, arguments: dict) -> Any:
    """Indexa una carpeta de libro. `db` se ignora: la biblioteca es global."""
    raw = arguments.get("path", "")
    if not raw:
        return [TextContent(type="text", text="Falta 'path': la carpeta del libro.")]

    try:
        r = book_corpus.index_book(
            Path(raw).expanduser(),
            arguments.get("title", ""),
            arguments.get("author", ""),
            force=bool(arguments.get("force", False)),
        )
    except ValueError as exc:
        return [TextContent(type="text", text=f"No se pudo indexar: {exc}")]

    partes = [
        f"Libro '{r.book_title}' (slug: {r.book_slug}) indexado.",
        f"  capítulos indexados: {r.chapters_indexed}",
        f"  capítulos sin cambios: {r.chapters_skipped}",
        f"  fragmentos escritos: {r.chunks_written}",
    ]
    if r.chapters_removed:
        partes.append(
            f"  capítulos retirados (ya no están en disco): {r.chapters_removed}"
        )
    if r.chunks_without_vector:
        partes.append(
            f"  AVISO: {r.chunks_without_vector} fragmentos SIN vector "
            f"({r.embed_error}). No serán encontrables hasta reindexar "
            f"con Ollama disponible."
        )
    return [TextContent(type="text", text="\n".join(partes))]


async def handle_apex_book_list(db: Any, arguments: dict) -> Any:
    """Lista los libros indexados."""
    libros = book_corpus.list_books()
    if not libros:
        return [TextContent(type="text", text=(
            "No hay libros indexados. Usa apex_book_index(path=...)."
        ))]

    lineas = [f"{len(libros)} libro(s) en la biblioteca:"]
    for b in libros:
        autor = f" — {b['author']}" if b["author"] else ""
        aviso = (
            f"  [{b['chunks_without_vector']} sin vector]"
            if b["chunks_without_vector"] else ""
        )
        lineas.append(
            f"  · {b['title']}{autor} (slug: {b['slug']}): "
            f"{b['chapters']} capítulos, {b['chunks']} fragmentos{aviso}"
        )
        lineas.append(f"    ruta: {b['root_path']}")
    return [TextContent(type="text", text="\n".join(lineas))]


async def handle_apex_book_search(db: Any, arguments: dict) -> Any:
    """Busca pasajes por significado y los devuelve con su cita."""
    query = arguments.get("query", "")
    if not query.strip():
        return [TextContent(type="text", text="Falta 'query'.")]

    # Antes de buscar, comprobar si algún libro cambió en disco. Comparar
    # hashes es local y barato: hace imposible buscar contra un índice viejo.
    sync_note = ""
    try:
        for b in book_corpus.list_books():
            r = book_corpus.sync_book(Path(b["root_path"]), b["title"], b["author"])
            if r and r.changed:
                detalle = []
                if r.chapters_indexed:
                    detalle.append(f"{r.chapters_indexed} nuevo(s) o modificado(s)")
                if r.chapters_removed:
                    detalle.append(f"{r.chapters_removed} borrado(s)")
                sync_note = (
                    f"(Reindexado automático en '{r.book_title}': "
                    f"{', '.join(detalle)}.)"
                )
    except Exception as exc:  # noqa: BLE001 — la búsqueda sigue con lo indexado
        sync_note = f"(Aviso: no se pudo comprobar cambios en disco: {exc})"

    pasajes, diag = book_corpus.search_books(
        query,
        book=arguments.get("book", ""),
        limit=int(arguments.get("limit", 5)),
    )
    return [TextContent(
        type="text", text=_render_passages(pasajes, diag, query, sync_note)
    )]
