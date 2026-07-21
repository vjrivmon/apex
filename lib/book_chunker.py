"""APEX Book Chunker — parte capítulos Markdown en fragmentos citables.

Trocea un fichero `.md` de la bóveda respetando el árbol de headings, de forma
que cada fragmento pueda citarse como `libro · capítulo · sección`.

Reglas que impone el corpus real (medidas sobre los 7 capítulos del libro de
Albada, no supuestas):

- Los `#` dentro de un bloque ``` NO son headings. El corpus tiene comentarios
  de Python (`# pip install rank_bm25`) que un `grep '^#'` confundiría con
  secciones, partiendo el capítulo y dejando la cita apuntando a una sección
  inexistente.
- Las tablas Markdown no se parten: una fila sin su cabecera es ilegible y su
  embedding, ruido.
- Las secciones muy cortas se funden con la siguiente; las muy largas se parten
  por párrafo. El merge corre también DESPUÉS del split, o el split deja colas
  huérfanas.

Uso:
    chunks = chunk_markdown(Path("Chapter 6/Knowledge and Memory.md"))
    for c in chunks:
        print(c.heading_path, len(c.content))
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# Un chunk por debajo de esto se funde con el siguiente: aislado no da
# contexto suficiente para un embedding útil.
MIN_CHUNK_CHARS = 400

# Por encima de esto se parte por párrafos. nomic-embed-text tiene ventana de
# 2048 tokens (~8000 caracteres); nos quedamos holgadamente por debajo.
MAX_CHUNK_CHARS = 2400

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")


@dataclass
class Chunk:
    """Un fragmento citable de un capítulo."""

    seq: int
    heading_path: str
    content: str

    def __post_init__(self) -> None:
        self.content = self.content.strip()


@dataclass
class _Section:
    """Sección intermedia: headings vigentes + líneas acumuladas."""

    heading_path: str
    lines: list[str] = field(default_factory=list)

    def text(self) -> str:
        return "\n".join(self.lines).strip()


def _split_sections(text: str) -> list[_Section]:
    """Parte el markdown por headings, ignorando los que van dentro de fences.

    Mantiene una pila de headings para construir el `heading_path` jerárquico
    ("Foundational Approaches to Memory > Managing Context Windows").
    """
    sections: list[_Section] = []
    stack: list[tuple[int, str]] = []  # (nivel, título)
    current = _Section(heading_path="")
    in_fence = False
    fence_marker = ""

    for line in text.splitlines():
        fence = _FENCE_RE.match(line)
        if fence:
            marker = fence.group(1)
            if not in_fence:
                in_fence, fence_marker = True, marker
            elif marker == fence_marker:
                in_fence = False
            current.lines.append(line)
            continue

        # Dentro de un fence, un '#' es un comentario de código, no un heading.
        if in_fence:
            current.lines.append(line)
            continue

        m = _HEADING_RE.match(line)
        if not m:
            current.lines.append(line)
            continue

        # Heading real: cierra la sección anterior si tenía contenido.
        if current.text():
            sections.append(current)

        level, title = len(m.group(1)), m.group(2).strip()
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, title))
        # El heading abre la nueva sección: va en el cuerpo (da contexto al
        # embedding) además de en el heading_path (que construye la cita).
        current = _Section(
            heading_path=" > ".join(t for _, t in stack), lines=[line]
        )

    if current.text():
        sections.append(current)
    return sections


def _split_paragraph(para: str) -> list[str]:
    """Parte un párrafo que por sí solo excede el máximo, cortando por frase.

    El corpus tiene párrafos de prosa continua de varios miles de caracteres.
    Cortar por caracteres dejaría fragmentos que empiezan a mitad de palabra;
    cortar por frase mantiene cada trozo legible y citable.
    """
    if len(para) <= MAX_CHUNK_CHARS:
        return [para]

    # Corta tras '.', '!' o '?' seguidos de espacio. Mantiene el separador.
    frases = re.split(r"(?<=[.!?])\s+", para)
    out: list[str] = []
    buf: list[str] = []
    for frase in frases:
        # Cerrar ANTES de exceder el máximo, no después: si no, cada bloque lo
        # supera por el largo de su última frase.
        if buf and len(" ".join(buf)) + 1 + len(frase) > MAX_CHUNK_CHARS:
            out.append(" ".join(buf))
            buf = []
        buf.append(frase)
    if buf:
        out.append(" ".join(buf))
    return [o for o in out if o.strip()]


def _split_long_text(text: str) -> list[str]:
    """Parte un texto largo por párrafos, sin romper tablas ni bloques de código."""
    blocks: list[str] = []
    buf: list[str] = []
    in_fence = False
    fence_marker = ""

    for para in text.split("\n\n"):
        # Una tabla o un fence a medias no puede separarse de lo que sigue.
        for line in para.splitlines():
            fence = _FENCE_RE.match(line)
            if fence:
                marker = fence.group(1)
                if not in_fence:
                    in_fence, fence_marker = True, marker
                elif marker == fence_marker:
                    in_fence = False

        buf.append(para)
        joined = "\n\n".join(buf)

        if in_fence:
            continue  # no cortar dentro de un bloque de código
        if _is_table_open(joined):
            continue  # no cortar una tabla de su cabecera
        if len(joined) >= MAX_CHUNK_CHARS:
            # Puede seguir excediendo el máximo si un solo párrafo del bloque
            # ya era gigante: _split_paragraph lo corta por frase.
            blocks.extend(_split_paragraph(joined))
            buf = []

    if buf:
        blocks.extend(_split_paragraph("\n\n".join(buf)))
    return [b.strip() for b in blocks if b.strip()]


def _is_table_open(text: str) -> bool:
    """True si el texto acaba dentro de una tabla Markdown."""
    lines = [ln for ln in text.strip().splitlines() if ln.strip()]
    return bool(lines) and lines[-1].lstrip().startswith("|")


def _merge_short(chunks: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Funde fragmentos cortos SOLO dentro del mismo heading.

    Fundir a través de headings distintos destruiría la cita: un fragmento que
    mezcla "Short-Term Memory" y "Long-Term Memory" no puede atribuirse a
    ninguna de las dos secciones, y la citabilidad es el requisito central.
    Por eso una sección corta se queda corta antes que perder su procedencia.

    Se ejecuta DESPUÉS del split porque partir una sección larga puede dejar
    una cola breve que sí debe fundirse con su hermana del mismo heading.
    """
    if not chunks:
        return []

    merged: list[tuple[str, str]] = []
    for path, content in chunks:
        if merged and merged[-1][0] == path and (
            # el anterior se quedó corto, o el actual lo está y cabe detrás
            len(merged[-1][1]) < MIN_CHUNK_CHARS
            or (
                len(content) < MIN_CHUNK_CHARS
                and len(merged[-1][1]) + len(content) <= MAX_CHUNK_CHARS
            )
        ):
            merged[-1] = (path, f"{merged[-1][1]}\n\n{content}")
        else:
            merged.append((path, content))
    return merged


def chunk_text(text: str) -> list[Chunk]:
    """Parte el contenido de un capítulo en fragmentos citables."""
    pieces: list[tuple[str, str]] = []

    for section in _split_sections(text):
        body = section.text()
        if not body:
            continue
        if len(body) <= MAX_CHUNK_CHARS:
            pieces.append((section.heading_path, body))
        else:
            for block in _split_long_text(body):
                pieces.append((section.heading_path, block))

    return [
        Chunk(seq=i, heading_path=path, content=content)
        for i, (path, content) in enumerate(_merge_short(pieces))
    ]


def chunk_markdown(path: Path) -> list[Chunk]:
    """Lee un `.md` y lo parte en fragmentos citables."""
    return chunk_text(path.read_text(encoding="utf-8"))
