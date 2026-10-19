"""Pipeline QUERY → INGEST — Procesa fuentes brutas y alimenta wiki.

Implementa los 8 pasos del diagrama Thomas Frank adaptados a desarrollo:

0. **sort clips** — agrupar archivos por categoría según dir (research/,
   socratic/, papers/, decisions-log/) o por keywords si están en la raíz.
1. **resolve URLs** — detectar enlaces externos en el texto; si es un
   repositorio, paper, o artículo conocido, anotar source_type.
2. **extract media** — extraer bloques clave (headings, listas, código,
   citas) como "señales" atómicas.
3. **classify** — decidir tipo de página wiki (entity/concept/comparison/
   query) según el contenido.
4. **compile pages** — construir páginas wiki con frontmatter YAML y el
   contenido re-estructurado.
5. **cross-link** — buscar otras wiki pages con overlap semántico y
   añadir wikilinks bidireccionales.
6. **bias check** — heurísticas simples para detectar exageraciones
   ("always", "never", adjetivos sin datos).
7. **update index** — llamar `wiki_scaffold.update_index()` + log entry.

Uso CLI:
    python -m lib.ingest --source .apex/raw/research/competitors.md
    python -m lib.ingest --source .apex/raw/ --recursive
    python -m lib.ingest --source PATH --project-root /proj --no-wiki-write

Uso programático:
    from lib.ingest import ingest
    result = ingest(source=Path("..."), project_root=Path("..."))
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


# --- Step 1: URL resolver ---

URL_RE = re.compile(r"https?://[^\s)\]]+", re.IGNORECASE)

SOURCE_TYPE_HINTS = [
    ("github.com", "repository"),
    ("arxiv.org", "paper"),
    ("docs.anthropic.com", "docs"),
    ("platform.claude.com", "docs"),
    ("mdn.org", "docs"),
    ("developer.mozilla.org", "docs"),
    ("youtube.com", "video"),
    ("youtu.be", "video"),
    ("medium.com", "article"),
    ("substack.com", "article"),
]


def _resolve_urls(text: str) -> list[dict]:
    urls = URL_RE.findall(text)
    out = []
    for u in urls:
        u = u.rstrip(".,;:\"'")
        stype = next((t for host, t in SOURCE_TYPE_HINTS if host in u.lower()), "link")
        out.append({"url": u, "source_type": stype})
    return out


# --- Step 2: Signal extraction ---

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
LIST_RE = re.compile(r"^\s*[-*+]\s+(.+)$", re.MULTILINE)
CODE_BLOCK_RE = re.compile(r"```(\w+)?\n(.*?)\n```", re.DOTALL)
QUOTE_RE = re.compile(r'^\s*>\s*["“](.+?)["”]\s*$', re.MULTILINE)


@dataclass
class Signal:
    """Unidad atómica extraída de una fuente."""
    kind: str          # heading | list-item | code | quote | paragraph
    level: int = 0     # heading level (1-6) o 0
    content: str = ""
    lang: str = ""     # para code blocks


def _extract_signals(text: str) -> list[Signal]:
    signals: list[Signal] = []
    for m in HEADING_RE.finditer(text):
        level = len(m.group(1))
        signals.append(Signal(kind="heading", level=level, content=m.group(2).strip()))
    for m in LIST_RE.finditer(text):
        signals.append(Signal(kind="list-item", content=m.group(1).strip()))
    for m in CODE_BLOCK_RE.finditer(text):
        signals.append(Signal(kind="code", lang=m.group(1) or "", content=m.group(2).strip()))
    for m in QUOTE_RE.finditer(text):
        signals.append(Signal(kind="quote", content=m.group(1).strip()))
    return signals


# --- Step 3: Classification ---

def _classify(text: str, source_dir: str | None) -> str:
    """Devuelve el tipo de página wiki a generar: entity | concept | comparison | query | raw."""
    lower = text.lower()
    if source_dir == "papers":
        return "raw"
    if source_dir == "decisions-log":
        return "concept"
    if source_dir == "socratic":
        return "query"
    # Heurísticas por contenido
    if re.search(r"\b(vs|versus|comparativa|comparison)\b", lower):
        return "comparison"
    if "?" in text.split("\n")[0] or lower.startswith("¿") or lower.startswith("how "):
        return "query"
    if re.search(r"\b(concept|pattern|principle|principio|patrón)\b", lower):
        return "concept"
    return "entity"


# --- Step 6: Bias check ---

BIAS_TERMS = [
    (r"\balways\b", "universal claim — añadir condiciones o eliminar"),
    (r"\bnever\b", "claim absoluto — idem"),
    (r"\bsiempre\b", "universal en español — revisar"),
    (r"\bnunca\b", "absoluto en español — revisar"),
    (r"\bbest\b", "superlativo sin métrica — añadir benchmark"),
    (r"\bobviously\b", "condescendiente — reformular"),
    (r"\bsimply\b", "minimiza complejidad — eliminar"),
]


def _bias_check(text: str) -> list[str]:
    flags: list[str] = []
    for pattern, msg in BIAS_TERMS:
        if re.search(pattern, text, re.IGNORECASE):
            flags.append(msg)
    return flags


# --- Step 5: Cross-link (reads existing wiki) ---

def _find_cross_links(wiki_dir: Path, new_content: str, exclude_slug: str) -> list[str]:
    """Busca slugs de páginas wiki existentes cuyo título aparezca en new_content."""
    if not wiki_dir.exists():
        return []
    links: list[str] = []
    for md in wiki_dir.rglob("*.md"):
        rel = md.relative_to(wiki_dir).with_suffix("").as_posix()
        if rel in ("SCHEMA", "index", "log", exclude_slug):
            continue
        title = md.stem.replace("-", " ").lower()
        if len(title) < 4:
            continue
        if title in new_content.lower():
            links.append(rel)
    return links[:8]


# --- Main pipeline ---

@dataclass
class IngestResult:
    source: Path
    slug: str
    page_type: str
    urls: list[dict] = field(default_factory=list)
    signals_count: int = 0
    wikilinks: list[str] = field(default_factory=list)
    bias_flags: list[str] = field(default_factory=list)
    wiki_page_path: Path | None = None
    wrote_to_db: bool = False


def _slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or "untitled"


def _source_dir_tag(source: Path, project_root: Path) -> str | None:
    """Si source está bajo .apex/raw/<category>/..., devuelve <category>."""
    try:
        rel = source.resolve().relative_to((project_root / ".apex" / "raw").resolve())
    except ValueError:
        return None
    parts = rel.parts
    return parts[0] if parts else None


def _compile_page_md(
    *,
    title: str,
    page_type: str,
    source: Path,
    signals: list[Signal],
    urls: list[dict],
    wikilinks: list[str],
    bias_flags: list[str],
    project_root: Path,
) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    tags = [page_type]
    source_tag = _source_dir_tag(source, project_root)
    if source_tag:
        tags.append(source_tag)

    fm_lines = [
        "---",
        f"title: {json.dumps(title, ensure_ascii=False)}",
        f"created: {now}",
        f"updated: {now}",
        f"type: {page_type}",
        "tags:",
        *[f"  - {t}" for t in tags],
        f"source: {json.dumps(str(source), ensure_ascii=False)}",
    ]
    if wikilinks:
        fm_lines.append("wikilinks:")
        fm_lines.extend(f"  - {w}" for w in wikilinks)
    if bias_flags:
        fm_lines.append("bias_flags:")
        fm_lines.extend(f"  - {json.dumps(f, ensure_ascii=False)}" for f in bias_flags)
    fm_lines.append("---")

    body = [f"# {title}", ""]
    if urls:
        body.append("## Fuentes externas")
        for u in urls[:12]:
            body.append(f"- [{u['source_type']}] <{u['url']}>")
        body.append("")

    # Headings de la fuente
    headings = [s for s in signals if s.kind == "heading" and s.level <= 3]
    if headings:
        body.append("## Estructura detectada")
        for h in headings[:20]:
            body.append(f"{'  ' * (h.level - 1)}- {h.content}")
        body.append("")

    # Citas
    quotes = [s.content for s in signals if s.kind == "quote"]
    if quotes:
        body.append("## Citas clave")
        for q in quotes[:10]:
            body.append(f"> {q}")
            body.append("")

    # Lista de signals "importantes" (list-items largos)
    items = [s.content for s in signals if s.kind == "list-item" and len(s.content) > 20]
    if items:
        body.append("## Puntos extraídos")
        for i in items[:15]:
            body.append(f"- {i}")
        body.append("")

    # Wikilinks
    if wikilinks:
        body.append("## Relacionado")
        for w in wikilinks:
            body.append(f"- [[{w}]]")
        body.append("")

    # Bias flags warning
    if bias_flags:
        body.append("## ⚠️  Revisión de sesgos")
        body.extend(f"- {f}" for f in bias_flags)
        body.append("")

    return "\n".join(fm_lines) + "\n\n" + "\n".join(body)


def _write_wiki_page(
    project_root: Path, page_type: str, slug: str, md: str
) -> Path:
    wiki_dir = project_root / ".apex" / "wiki"
    subdir_map = {
        "entity": "entities",
        "concept": "concepts",
        "comparison": "comparisons",
        "query": "queries",
        "raw": "raw",
        "synthesis": "synthesis",
    }
    target_dir = wiki_dir / subdir_map.get(page_type, "entities")
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"{slug}.md"
    path.write_text(md, encoding="utf-8")
    return path


def _log_to_context_db(
    project_root: Path, slug: str, page_type: str, source: Path
) -> bool:
    db_path = project_root / ".apex" / "context.db"
    if not db_path.exists():
        return False
    try:
        conn = sqlite3.connect(str(db_path))
        # Insertar en wiki_pages si la tabla existe
        try:
            conn.execute(
                "INSERT OR REPLACE INTO wiki_pages (slug, title, content, page_type, tags, updated_at) "
                "VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
                (
                    slug,
                    slug.replace("-", " ").title(),
                    f"[auto-ingest from {source.name}]",
                    page_type,
                    json.dumps([page_type, "auto-ingest"]),
                ),
            )
            conn.commit()
            return True
        except sqlite3.OperationalError:
            return False
    finally:
        conn.close()


def ingest(
    source: Path,
    project_root: Path | None = None,
    write_wiki: bool = True,
    write_db: bool = True,
) -> IngestResult:
    """Ejecuta el pipeline completo sobre UNA fuente (archivo)."""
    if not source.exists() or source.is_dir():
        raise ValueError(f"Source no es un archivo existente: {source}")

    project_root = project_root or _guess_project_root(source)

    text = source.read_text(encoding="utf-8", errors="replace")

    urls = _resolve_urls(text)                            # step 1
    signals = _extract_signals(text)                      # step 2
    source_tag = _source_dir_tag(source, project_root)
    page_type = _classify(text, source_tag)               # step 3
    bias_flags = _bias_check(text)                        # step 6

    # Título: primer heading h1 o stem del archivo
    title = source.stem.replace("-", " ").title()
    for s in signals:
        if s.kind == "heading" and s.level == 1:
            title = s.content
            break

    slug = _slugify(source.stem)
    wiki_dir = project_root / ".apex" / "wiki"
    links = _find_cross_links(wiki_dir, text, exclude_slug=slug)  # step 5

    md = _compile_page_md(                                 # step 4
        title=title,
        page_type=page_type,
        source=source,
        signals=signals,
        urls=urls,
        wikilinks=links,
        bias_flags=bias_flags,
        project_root=project_root,
    )

    result = IngestResult(
        source=source,
        slug=slug,
        page_type=page_type,
        urls=urls,
        signals_count=len(signals),
        wikilinks=links,
        bias_flags=bias_flags,
    )

    if write_wiki:
        result.wiki_page_path = _write_wiki_page(project_root, page_type, slug, md)
        # step 7: actualizar index + log
        from wiki_scaffold import append_log, update_index
        append_log(wiki_dir, f"Ingest: {source.name} → {page_type}/{slug}")
        update_index(wiki_dir)

    if write_db:
        result.wrote_to_db = _log_to_context_db(project_root, slug, page_type, source)

    return result


def _guess_project_root(source: Path) -> Path:
    """Asume .apex/raw/... y sube hasta encontrar .apex/."""
    for parent in [source.parent, *source.parent.parents]:
        if (parent / ".apex").exists():
            return parent
        if (parent / ".git").exists():
            return parent
    return source.parent


def _dentro_de(root: Path, path: Path) -> bool:
    """¿`path` (resuelto, symlinks incluidos) está dentro de `root`?"""
    try:
        return path.resolve().is_relative_to(root.resolve())
    except (OSError, RuntimeError):
        return False


def ingest_dir(
    source_dir: Path,
    project_root: Path | None = None,
    recursive: bool = True,
    **kwargs,
) -> list[IngestResult]:
    """Ejecuta ingest sobre todos los archivos .md / .txt / .markdown del directorio."""
    pattern = "**/*" if recursive else "*"
    exts = {".md", ".markdown", ".txt", ".json"}
    results: list[IngestResult] = []
    for path in source_dir.glob(pattern):
        if not path.is_file() or path.suffix.lower() not in exts:
            continue
        if path.name.lower() == "readme.md":
            continue
        # Un symlink dentro del árbol puede apuntar fuera del proyecto: se
        # comprueba la ruta RESUELTA, que es la que se lee.
        raiz = project_root or _guess_project_root(path)
        if not _dentro_de(raiz, path):
            print(f"WARN: {path}: apunta fuera del proyecto, se ignora", file=sys.stderr)
            continue
        try:
            results.append(ingest(path, project_root=project_root, **kwargs))
        except Exception as e:
            print(f"WARN: {path}: {e}", file=sys.stderr)
    return results


# --- CLI ---

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--source", type=Path, required=True,
                   help="Archivo o directorio a ingerir")
    p.add_argument("--project-root", type=Path, default=None)
    p.add_argument("--recursive", action="store_true", default=True)
    p.add_argument("--no-wiki-write", dest="write_wiki", action="store_false", default=True,
                   help="No escribir páginas wiki (dry-run)")
    p.add_argument("--no-db-write", dest="write_db", action="store_false", default=True)
    args = p.parse_args(argv)

    src = args.source
    if not src.exists():
        print(f"ERROR: source no existe: {src}", file=sys.stderr)
        return 1
    if src.is_dir():
        results = ingest_dir(
            src, project_root=args.project_root, recursive=args.recursive,
            write_wiki=args.write_wiki, write_db=args.write_db,
        )
        print(f"Procesados {len(results)} archivos.")
        for r in results:
            print(f"  {r.source.name} → {r.page_type}/{r.slug} "
                  f"(signals={r.signals_count}, urls={len(r.urls)}, "
                  f"links={len(r.wikilinks)}, bias={len(r.bias_flags)})")
    else:
        r = ingest(
            src, project_root=args.project_root,
            write_wiki=args.write_wiki, write_db=args.write_db,
        )
        print(f"{r.source.name} → {r.page_type}/{r.slug}")
        print(f"  signals: {r.signals_count}, urls: {len(r.urls)}, "
              f"links: {len(r.wikilinks)}, bias: {len(r.bias_flags)}")
        if r.wiki_page_path:
            print(f"  wrote: {r.wiki_page_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
