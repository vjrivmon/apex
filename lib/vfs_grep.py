"""APEX VFS — grep recursivo con flags POSIX y pre-filtro FTS5 opcional.

Implementa el subset de flags `-i`, `-r`, `-n`, `-l`, `-E` requeridos por
el blueprint del Sprint 17. Devuelve `list[GrepHit]` con paths virtuales
(no reales del filesystem), ordenados por (path, line).

El pre-filtro FTS5 es **best-effort**: si el pattern es traducible a una
query MATCH simple (sin regex specials), consulta `context_fts` del
proyecto resuelto y restringe el scan a los archivos candidatos. Si el
pattern no es traducible (regex), el pre-filtro se salta silenciosamente
y el scan se ejecuta sobre todos los archivos del directorio.
"""
from __future__ import annotations

import re
import shlex
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from vfs import VFSNotImplementedError, VirtualFS, _PROJECT_REAL_MOUNTS


_VALID_FLAGS = frozenset({"i", "r", "n", "l", "E"})

_FTS_REGEX_SPECIALS = set(r"()*+?[]\^${}|.")


@dataclass(frozen=True)
class GrepFlags:
    ignore_case: bool = False
    recursive: bool = False
    line_number: bool = False
    files_with_matches: bool = False
    extended_regex: bool = False


@dataclass(frozen=True)
class GrepHit:
    virtual_path: str
    line_num: int  # 1-based; 0 si no se pidió `-n` o si es -l
    line: str  # vacío si flag `-l`


def parse_grep_flags(flags: str) -> GrepFlags:
    """Traduce una string de flags POSIX (`-i`, `-rn`, `-r -n`) a `GrepFlags`.

    Acepta tanto agrupados (`-rn`) como separados (`-r -n`). Lanza
    `ValueError` si encuentra un flag fuera del subset permitido.
    """
    if not flags:
        return GrepFlags()
    tokens = shlex.split(flags)
    seen: set[str] = set()
    for token in tokens:
        if not token.startswith("-"):
            raise ValueError(f"unknown grep flag (must start with '-'): {token}")
        chars = token[1:]
        if not chars:
            raise ValueError(f"empty grep flag: {token}")
        for c in chars:
            if c not in _VALID_FLAGS:
                raise ValueError(f"unknown grep flag '-{c}'")
            seen.add(c)
    return GrepFlags(
        ignore_case="i" in seen,
        recursive="r" in seen,
        line_number="n" in seen,
        files_with_matches="l" in seen,
        extended_regex="E" in seen,
    )


def grep(
    vfs: VirtualFS,
    pattern: str,
    virtual_path: str,
    flags: str = "",
    use_fts_prefilter: bool = False,
) -> list[GrepHit]:
    """Ejecuta grep sobre `virtual_path` y devuelve hits ordenados.

    `use_fts_prefilter`: si True y el pattern es traducible a FTS5,
    consulta `context_fts` del proyecto resuelto y limita el scan a los
    archivos candidatos. Best-effort: cualquier fallo (BD inexistente,
    pattern no traducible, query rota) cae en silencio al scan completo.
    """
    parsed = parse_grep_flags(flags)
    resolved = vfs._resolve(virtual_path)
    if resolved.kind == "virtual":
        raise VFSNotImplementedError(
            f"grep on virtual category '{resolved.category}' not yet implemented "
            "(scheduled for S17.6)"
        )

    real = resolved.real_path
    assert real is not None
    re_flags = re.IGNORECASE if parsed.ignore_case else 0
    try:
        regex = re.compile(pattern, re_flags)
    except re.error as exc:
        raise ValueError(f"invalid regex pattern: {exc}") from exc

    # Determine target files (virtual paths)
    if real.is_file():
        target_files = [virtual_path]
    else:
        target_files = vfs.find(virtual_path)

    # Optional FTS5 pre-filter
    if use_fts_prefilter and resolved.slug and resolved.category == "wiki":
        candidates = _fts_prefilter_wiki(vfs, resolved.slug, pattern)
        if candidates is not None:
            # Restringir target a la intersección con candidatos.
            # Match conservador: el slug de wiki_pages se usa como hint
            # textual; si el path virtual contiene cualquiera de los slugs,
            # se conserva. Si no, se descarta.
            kept = []
            for vp in target_files:
                if any(_path_matches_wiki_slug(vp, s) for s in candidates):
                    kept.append(vp)
            # Si el pre-filter descarta TODO, asume falso negativo y vuelve al
            # scan completo (preferimos correctness sobre speedup).
            if kept:
                target_files = kept

    # Scan
    hits: list[GrepHit] = []
    for vp in target_files:
        try:
            content = vfs.cat(vp)
        except Exception:  # noqa: BLE001 — best-effort lectura
            continue
        for i, line in enumerate(content.splitlines(), 1):
            if not regex.search(line):
                continue
            if parsed.files_with_matches:
                hits.append(GrepHit(virtual_path=vp, line_num=0, line=""))
                break
            hits.append(
                GrepHit(
                    virtual_path=vp,
                    line_num=i if parsed.line_number else 0,
                    line=line,
                )
            )

    return sorted(hits, key=lambda h: (h.virtual_path, h.line_num))


# --- helpers privados -----------------------------------------------------


def _to_fts_match_query(pattern: str) -> str | None:
    """Traduce un pattern a una query FTS5 MATCH simple. None si tiene
    regex specials que no podemos traducir conservadoramente.
    """
    if any(c in pattern for c in _FTS_REGEX_SPECIALS):
        return None
    text = pattern.strip()
    if not text:
        return None
    # Doble comilla escapa quotes internos en FTS5.
    return '"' + text.replace('"', '""') + '"'


def _fts_prefilter_wiki(
    vfs: VirtualFS, slug: str, pattern: str
) -> set[str] | None:
    """Devuelve set de slugs de wiki_pages que matchean el pattern vía FTS5,
    o None si no hay BD / pattern no traducible / cualquier error."""
    fts_query = _to_fts_match_query(pattern)
    if fts_query is None:
        return None
    db_path = _project_db_path(vfs, slug)
    if db_path is None or not db_path.exists():
        return None
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.OperationalError:
        return None
    try:
        rows = conn.execute(
            "SELECT source_id FROM context_fts "
            "WHERE source='wiki' AND content MATCH ?",
            (fts_query,),
        ).fetchall()
        return {r[0] for r in rows}
    except sqlite3.OperationalError:
        return None
    finally:
        conn.close()


def _project_db_path(vfs: VirtualFS, slug: str) -> Path | None:
    for root in vfs.allowed_roots:
        base = root / slug
        candidate = base / ".apex" / "context.db"
        if candidate.exists():
            return candidate
    return None


def _path_matches_wiki_slug(virtual_path: str, slug: str) -> bool:
    """Heurística: el slug de wiki_pages (e.g. 'entities/concepts/tdd') se
    encuentra como sufijo del path virtual, ignorando extensión."""
    suffix = virtual_path.rsplit("/projects/", 1)[-1]
    suffix_no_ext = suffix.rsplit(".", 1)[0] if "." in suffix.rsplit("/", 1)[-1] else suffix
    return slug in virtual_path or slug in suffix_no_ext
