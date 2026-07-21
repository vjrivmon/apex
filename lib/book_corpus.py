"""APEX Book Corpus — biblioteca vectorial de libros técnicos, cross-project.

`~/.apex/library.db` guarda los libros que Vicente lee (una carpeta por libro,
donde él quiera en el disco) troceados en fragmentos citables con su vector
nomic-embed-text. Se consulta desde CUALQUIER proyecto APEX o sin proyecto.

Diseño:
- BD propia, separada de `~/.apex/context.db` (memoria append-only de errores
  graves) porque la biblioteca es mutable y re-indexable. Sigue el patrón de
  `lib/global_memory.py`: sqlite3 síncrono, `_SCHEMA`, `_ensure_schema`.
- Un solo índice con `book_id`, no un índice por libro: permite preguntar
  cruzando varios títulos y filtrar a uno concreto cuando interese.
- `content_sha` por capítulo: reindexar solo toca lo que cambió. Añadir el
  Capítulo 8 cuesta sus ~30 embeds, no los 228 del libro entero.
- `embed_model` / `embed_dim` por fila: si el modelo cambia bajo los pies, se
  detecta en vez de devolver resultados de otro espacio vectorial.
- El texto se guarda VERBATIM. La cita se construye en SQL con columnas
  NOT NULL, no la redacta el modelo.
"""
from __future__ import annotations

import hashlib
import re
import sqlite3
import struct
from dataclasses import dataclass
from pathlib import Path

from book_chunker import chunk_markdown
from embeddings import EMBED_DIM, EMBED_MODEL, embed_batch, embed_query

# Por debajo de esta similitud, un pasaje no se considera respuesta. Calibrado
# midiendo el corpus real: preguntas cubiertas por el libro puntúan 0.69-0.82,
# preguntas ajenas (Kubernetes, IVA, pan) se quedan en 0.45-0.58.
SIMILARITY_THRESHOLD = 0.66

_SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS books (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    author TEXT NOT NULL DEFAULT '',
    root_path TEXT NOT NULL,
    indexed_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS book_chapters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    chapter_number INTEGER,
    chapter_title TEXT NOT NULL,
    rel_path TEXT NOT NULL,
    content_sha TEXT NOT NULL,
    UNIQUE(book_id, rel_path)
);

CREATE TABLE IF NOT EXISTS book_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chapter_id INTEGER NOT NULL REFERENCES book_chapters(id) ON DELETE CASCADE,
    book_id INTEGER NOT NULL,
    seq INTEGER NOT NULL,
    heading_path TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL,
    embed_model TEXT NOT NULL DEFAULT '',
    embed_dim INTEGER NOT NULL DEFAULT 0,
    vector BLOB,
    UNIQUE(chapter_id, seq)
);

CREATE INDEX IF NOT EXISTS idx_bchunks_book ON book_chunks(book_id);
CREATE INDEX IF NOT EXISTS idx_bchapters_book ON book_chapters(book_id);
"""

_CHAPTER_NUM_RE = re.compile(r"(?:chapter|cap[íi]tulo|ch)[\s_-]*(\d+)", re.I)


@dataclass
class Passage:
    """Un pasaje recuperado, con todo lo necesario para citarlo."""

    book_title: str
    book_author: str
    chapter_number: int | None
    chapter_title: str
    heading_path: str
    content: str
    score: float
    rel_path: str

    def citation(self) -> str:
        """Cita legible: `libro · Cap. N: título · sección`."""
        partes = [self.book_title]
        if self.chapter_number is not None:
            partes.append(f"Cap. {self.chapter_number}: {self.chapter_title}")
        else:
            partes.append(self.chapter_title)
        if self.heading_path:
            partes.append(self.heading_path)
        return " · ".join(partes)


@dataclass
class IndexResult:
    """Qué hizo una indexación. Se reporta al usuario tal cual."""

    book_slug: str
    book_title: str
    chapters_indexed: int = 0
    chapters_skipped: int = 0
    chapters_removed: int = 0
    chunks_written: int = 0
    chunks_without_vector: int = 0
    embed_error: str = ""

    @property
    def changed(self) -> bool:
        return self.chapters_indexed > 0 or self.chapters_removed > 0


def library_db_path() -> Path:
    """Ruta canónica de la biblioteca. `~/.apex/library.db`."""
    return Path.home() / ".apex" / "library.db"


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or library_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path), timeout=5)
    # ON DELETE CASCADE es decorativo sin esto, y no persiste en el fichero.
    con.execute("PRAGMA foreign_keys=ON")
    _ensure_schema(con)
    return con


def _ensure_schema(con: sqlite3.Connection) -> None:
    con.executescript(_SCHEMA)


def slugify(text: str) -> str:
    """Slug estable a partir del título o del nombre de carpeta."""
    s = re.sub(r"[^\w\s-]", "", text.lower())
    s = re.sub(r"[\s_]+", "-", s).strip("-")
    return s or "libro"


def _chapter_number(rel_path: str, fallback: int) -> int | None:
    """Extrae el número de capítulo de la ruta, si lo hay.

    El layout `Chapter N/` es un accidente de cómo Vicente exportó este libro;
    otro libro puede no tenerlo. Si no se detecta, se devuelve None y la cita
    degrada a `[Libro · Título de sección]`, que sigue siendo citable.
    """
    m = _CHAPTER_NUM_RE.search(rel_path)
    return int(m.group(1)) if m else None


def _pack(vector: list[float]) -> bytes:
    return struct.pack(f"<{len(vector)}f", *vector)


def _unpack(blob: bytes) -> list[float]:
    return list(struct.unpack(f"<{len(blob) // 4}f", blob))


def _cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ── Indexación ──

def index_book(
    root: Path,
    title: str = "",
    author: str = "",
    *,
    force: bool = False,
    db_path: Path | None = None,
) -> IndexResult:
    """Indexa (o reindexa) una carpeta de libro.

    Solo se reembeben los capítulos cuyo `content_sha` cambió, salvo `force`.
    Si Ollama no responde, los fragmentos se guardan con `vector=NULL` y se
    reporta explícitamente: la biblioteca queda incompleta, pero lo dice.
    """
    root = Path(root).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"no es un directorio: {root}")

    title = title or root.name
    slug = slugify(title)
    result = IndexResult(book_slug=slug, book_title=title)

    markdowns = sorted(p for p in root.rglob("*.md") if p.is_file())
    if not markdowns:
        raise ValueError(f"no hay ficheros .md bajo {root}")

    con = _connect(db_path)
    try:
        con.execute(
            "INSERT INTO books (slug, title, author, root_path) VALUES (?,?,?,?) "
            "ON CONFLICT(slug) DO UPDATE SET title=excluded.title, "
            "author=CASE WHEN excluded.author != '' THEN excluded.author "
            "            ELSE books.author END, "
            "root_path=excluded.root_path, indexed_at=datetime('now')",
            (slug, title, author, str(root)),
        )
        book_id = con.execute(
            "SELECT id FROM books WHERE slug=?", (slug,)
        ).fetchone()[0]

        # Capítulos que ya no están en disco: se borran, o la biblioteca
        # seguiría citando texto que el usuario eliminó o renombró.
        en_disco = {str(p.relative_to(root)) for p in markdowns}
        for (rel_viejo,) in con.execute(
            "SELECT rel_path FROM book_chapters WHERE book_id=?", (book_id,)
        ).fetchall():
            if rel_viejo not in en_disco:
                con.execute(
                    "DELETE FROM book_chapters WHERE book_id=? AND rel_path=?",
                    (book_id, rel_viejo),
                )
                result.chapters_removed += 1

        pendientes: list[tuple[int, list]] = []
        for i, md in enumerate(markdowns, start=1):
            rel = str(md.relative_to(root))
            texto = md.read_text(encoding="utf-8")
            sha = _sha(texto)

            fila = con.execute(
                "SELECT id, content_sha FROM book_chapters "
                "WHERE book_id=? AND rel_path=?",
                (book_id, rel),
            ).fetchone()

            if fila and fila[1] == sha and not force:
                result.chapters_skipped += 1
                continue

            chunks = chunk_markdown(md)
            if not chunks:
                continue

            if fila:
                chapter_id = fila[0]
                con.execute(
                    "UPDATE book_chapters SET content_sha=?, chapter_title=? "
                    "WHERE id=?",
                    (sha, md.stem, chapter_id),
                )
                # Los fragmentos viejos se van; los nuevos se insertan limpios.
                con.execute(
                    "DELETE FROM book_chunks WHERE chapter_id=?", (chapter_id,)
                )
            else:
                cur = con.execute(
                    "INSERT INTO book_chapters "
                    "(book_id, chapter_number, chapter_title, rel_path, content_sha) "
                    "VALUES (?,?,?,?,?)",
                    (book_id, _chapter_number(rel, i), md.stem, rel, sha),
                )
                chapter_id = cur.lastrowid

            pendientes.append((chapter_id, chunks))
            result.chapters_indexed += 1

        # Un solo batch para todo el libro: 228 fragmentos tardan ~2s.
        todos = [c for _, chunks in pendientes for c in chunks]
        vectores: list[list[float] | None] = [None] * len(todos)
        if todos:
            try:
                vectores = embed_batch([c.content for c in todos], is_query=False)
            except Exception as exc:  # noqa: BLE001 — best-effort, se reporta
                result.embed_error = str(exc)

        idx = 0
        for chapter_id, chunks in pendientes:
            for c in chunks:
                vec = vectores[idx] if idx < len(vectores) else None
                idx += 1
                con.execute(
                    "INSERT OR REPLACE INTO book_chunks "
                    "(chapter_id, book_id, seq, heading_path, content, "
                    " embed_model, embed_dim, vector) VALUES (?,?,?,?,?,?,?,?)",
                    (
                        chapter_id, book_id, c.seq, c.heading_path, c.content,
                        EMBED_MODEL if vec else "", len(vec) if vec else 0,
                        _pack(vec) if vec else None,
                    ),
                )
                result.chunks_written += 1
                if not vec:
                    result.chunks_without_vector += 1

        con.commit()
    finally:
        con.close()

    return result


def sync_book(
    root: Path,
    title: str = "",
    author: str = "",
    *,
    db_path: Path | None = None,
) -> IndexResult | None:
    """Reindexa solo si algún capítulo cambió o hay capítulos nuevos.

    Es lo que se llama antes de cada búsqueda: comparar hashes es local y
    barato, así que es imposible buscar contra un índice desactualizado.
    Devuelve None si no había nada que hacer.
    """
    root = Path(root).expanduser().resolve()
    if not root.is_dir():
        return None
    if not _needs_sync(root, title or root.name, db_path=db_path):
        return None
    return index_book(root, title, author, db_path=db_path)


def _needs_sync(root: Path, title: str, *, db_path: Path | None = None) -> bool:
    """True si hay capítulos nuevos, borrados o con el contenido cambiado."""
    slug = slugify(title)
    con = _connect(db_path)
    try:
        fila = con.execute("SELECT id FROM books WHERE slug=?", (slug,)).fetchone()
        if not fila:
            return True
        conocidos = {
            r[0]: r[1]
            for r in con.execute(
                "SELECT rel_path, content_sha FROM book_chapters WHERE book_id=?",
                (fila[0],),
            )
        }
    finally:
        con.close()

    actuales = {
        str(p.relative_to(root)): _sha(p.read_text(encoding="utf-8"))
        for p in sorted(root.rglob("*.md"))
        if p.is_file()
    }
    return actuales != conocidos


# ── Búsqueda ──

def search_books(
    query: str,
    *,
    book: str = "",
    limit: int = 5,
    threshold: float = SIMILARITY_THRESHOLD,
    db_path: Path | None = None,
) -> tuple[list[Passage], dict]:
    """Busca pasajes por significado. Devuelve `(pasajes, diagnóstico)`.

    La lista viene vacía cuando ningún pasaje supera el umbral: el corpus no
    cubre la pregunta. El diagnóstico lleva el mejor score alcanzado para que
    quien llame pueda decirlo con números en vez de callar.
    """
    diag = {
        "books": 0, "chunks": 0, "best_score": 0.0,
        "threshold": threshold, "error": "", "model_mismatch": 0,
    }
    if not query.strip():
        return [], diag

    try:
        qvec = embed_query(query)
    except Exception as exc:  # noqa: BLE001 — se reporta, no se traga
        diag["error"] = f"no se pudo consultar Ollama: {exc}"
        return [], diag

    con = _connect(db_path)
    try:
        diag["books"] = con.execute("SELECT count(*) FROM books").fetchone()[0]
        sql = (
            "SELECT bc.content, bc.heading_path, bc.vector, bc.embed_dim, "
            "       ch.chapter_number, ch.chapter_title, ch.rel_path, "
            "       b.title, b.author "
            "FROM book_chunks bc "
            "JOIN book_chapters ch ON ch.id = bc.chapter_id "
            "JOIN books b ON b.id = bc.book_id "
            "WHERE bc.vector IS NOT NULL"
        )
        params: list = []
        if book:
            sql += " AND b.slug = ?"
            params.append(slugify(book))
        filas = con.execute(sql, params).fetchall()
    finally:
        con.close()

    diag["chunks"] = len(filas)
    scored: list[Passage] = []
    for (content, heading, blob, dim, ch_num, ch_title, rel, title, author) in filas:
        if dim != EMBED_DIM:
            diag["model_mismatch"] += 1
            continue
        score = _cosine(qvec, _unpack(blob))
        diag["best_score"] = max(diag["best_score"], score)
        if score >= threshold:
            scored.append(Passage(
                book_title=title, book_author=author, chapter_number=ch_num,
                chapter_title=ch_title, heading_path=heading, content=content,
                score=score, rel_path=rel,
            ))

    scored.sort(key=lambda p: p.score, reverse=True)
    return scored[:limit], diag


def list_books(db_path: Path | None = None) -> list[dict]:
    """Los libros indexados, con su recuento de capítulos y fragmentos."""
    con = _connect(db_path)
    try:
        filas = con.execute(
            "SELECT b.slug, b.title, b.author, b.root_path, b.indexed_at, "
            "       (SELECT count(*) FROM book_chapters WHERE book_id=b.id), "
            "       (SELECT count(*) FROM book_chunks WHERE book_id=b.id), "
            "       (SELECT count(*) FROM book_chunks "
            "        WHERE book_id=b.id AND vector IS NULL) "
            "FROM books b ORDER BY b.title"
        ).fetchall()
    finally:
        con.close()
    return [
        {
            "slug": r[0], "title": r[1], "author": r[2], "root_path": r[3],
            "indexed_at": r[4], "chapters": r[5], "chunks": r[6],
            "chunks_without_vector": r[7],
        }
        for r in filas
    ]


def forget_book(slug: str, db_path: Path | None = None) -> bool:
    """Borra un libro y todo lo suyo. True si existía."""
    con = _connect(db_path)
    try:
        cur = con.execute("DELETE FROM books WHERE slug=?", (slugify(slug),))
        con.commit()
        return cur.rowcount > 0
    finally:
        con.close()
