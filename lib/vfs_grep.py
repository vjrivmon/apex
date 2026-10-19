"""APEX VFS — grep recursivo con flags POSIX y pre-filtro FTS5 opcional.

Implementa el subset de flags `-i`, `-r`, `-n`, `-l`, `-E` requeridos por
el blueprint del Sprint 17. Devuelve `list[GrepHit]` con paths virtuales
(no reales del filesystem), ordenados por (path, line).

El pre-filtro FTS5 es **best-effort**: si el pattern es traducible a una
query MATCH simple (sin regex specials), consulta `context_fts` del
proyecto resuelto y restringe el scan a los archivos candidatos. Si el
pattern no es traducible (regex), el pre-filtro se salta y el scan se
ejecuta sobre todos los archivos del directorio — avisando de ello.

Riesgo R2 del blueprint: un `grep -r` en frío sobre 11 proyectos puede
tardar más de 2s. Por eso el pre-filtro es obligatorio y su estado se
reporta en `GrepOutcome.prefilter` / `GrepOutcome.warnings`: el agente
sabe si el resultado vino de un escaneo acotado o de uno completo.
"""
from __future__ import annotations

import re
import shlex
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from vfs import (
    GREP_FLAG_CHARS,
    VFSError,
    VFSNotImplementedError,
    VirtualFS,
)


#: Caracteres que impiden traducir un patrón a una query FTS5 MATCH.
_FTS_REGEX_SPECIALS = set(r"()*+?[]\^${}|.")

#: Tope de ficheros escaneados en una sola llamada. Evita que un
#: `grep -r /projects/` en frío secoma el tiempo del agente.
MAX_SCANNED_FILES = 5000

#: Categorías con cobertura del índice FTS5 del proyecto (`context_fts`
#: indexa páginas de wiki con su slug, que es la ruta relativa a `wiki/`).
_FTS_COVERED_CATEGORIES = frozenset({"wiki", "decisions"})


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


@dataclass(frozen=True)
class GrepOutcome:
    """Resultado del grep con el estado del pre-filtro.

    `prefilter`:
      - `"fts5"`: el escaneo se restringió a los candidatos del índice FTS5.
      - `"completo"`: se escaneó todo (patrón no traducible o sin índice).
      - `"no-aplicable"`: la categoría no tiene cobertura FTS5.
    """

    hits: list[GrepHit] = field(default_factory=list)
    warnings: tuple[str, ...] = ()
    prefilter: str = "none"


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
            if c not in GREP_FLAG_CHARS:
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
    return grep_detailed(
        vfs, pattern, virtual_path, flags, use_fts_prefilter
    ).hits


def grep_detailed(
    vfs: VirtualFS,
    pattern: str,
    virtual_path: str,
    flags: str = "",
    use_fts_prefilter: bool = False,
    max_files: int = MAX_SCANNED_FILES,
) -> GrepOutcome:
    """Como `grep`, pero reporta el estado del pre-filtro y los avisos.

    Los avisos importan (riesgo R2): el agente necesita saber si el
    resultado es de un escaneo acotado por FTS5 o de uno completo, y por
    qué se cayó al completo.
    """
    parsed = parse_grep_flags(flags)
    resolved = vfs._resolve(virtual_path)
    warnings: list[str] = []

    if resolved.kind == "collection":
        return _grep_cross_project(
            vfs, pattern, parsed, use_fts_prefilter, max_files
        )

    if resolved.kind == "virtual":
        if vfs.materializer is None:
            raise VFSNotImplementedError(
                f"grep on virtual category '{resolved.category}' not yet implemented "
                "(scheduled for S17.6)"
            )
        target_files = vfs.find(virtual_path)
        warnings.append(
            f"categoría virtual '{resolved.category}': los datos salen de SQL, "
            "sin índice FTS5 (escaneo completo)"
        )
        prefilter_state = "no-aplicable"
    else:
        real = resolved.real_path
        assert real is not None
        if real.is_file():
            target_files = [virtual_path]
        else:
            target_files = vfs.find(virtual_path)

        prefilter_state = "completo"
        if use_fts_prefilter:
            if resolved.slug and resolved.category in _FTS_COVERED_CATEGORIES:
                candidates = _fts_prefilter(vfs, resolved.slug, pattern)
                if candidates is None:
                    warnings.append(
                        "patrón no traducible a FTS5: se ejecuta un escaneo "
                        "completo (más lento en frío)"
                    )
                else:
                    kept = [
                        vp for vp in target_files
                        if any(_path_matches_wiki_slug(vp, s) for s in candidates)
                    ]
                    if kept:
                        target_files = kept
                        prefilter_state = "fts5"
                    else:
                        warnings.append(
                            "el pre-filtro FTS5 no devolvió candidatos: se "
                            "ejecuta un escaneo completo (más lento en frío)"
                        )
            elif resolved.slug:
                warnings.append(
                    f"categoría '{resolved.category}' sin cobertura FTS5: "
                    "escaneo completo"
                )
                prefilter_state = "no-aplicable"

    if len(target_files) > max_files:
        warnings.append(
            f"escaneo truncado a {max_files} ficheros (de {len(target_files)}): "
            "el resultado puede estar incompleto"
        )
        target_files = target_files[:max_files]

    re_flags = re.IGNORECASE if parsed.ignore_case else 0
    try:
        regex = re.compile(pattern, re_flags)
    except re.error as exc:
        raise ValueError(f"invalid regex pattern: {exc}") from exc

    hits = _scan(vfs, target_files, regex, parsed)
    return GrepOutcome(
        hits=hits,
        warnings=tuple(dict.fromkeys(warnings)),
        prefilter=prefilter_state,
    )


def _grep_cross_project(
    vfs: VirtualFS,
    pattern: str,
    parsed: GrepFlags,
    use_fts_prefilter: bool,
    max_files: int,
) -> GrepOutcome:
    """Grep recursivo sobre todos los proyectos alcanzables.

    Cada proyecto se pre-filtra con su propio índice FTS5 antes del scan
    en memoria; si el patrón no es traducible, cada proyecto avisa y se
    escanea entero (riesgo R2 aceptado y reportado).
    """
    flags = _flags_to_string(parsed)
    hits: list[GrepHit] = []
    warnings: list[str] = []
    states: set[str] = set()
    for slug in vfs.project_slugs():
        for category in ("wiki", "decisions", "handoffs", "raw"):
            path = f"/projects/{slug}/{category}"
            try:
                sub = grep_detailed(
                    vfs,
                    pattern,
                    path,
                    flags,
                    use_fts_prefilter,
                    max_files=max_files,
                )
            except VFSError:
                continue
            hits.extend(sub.hits)
            warnings.extend(sub.warnings)
            states.add(sub.prefilter)
    if not states:
        states.add("no-aplicable")
    prefilter_state = "fts5" if states == {"fts5"} else "completo"
    return GrepOutcome(
        hits=sorted(hits, key=lambda h: (h.virtual_path, h.line_num)),
        warnings=tuple(dict.fromkeys(warnings)),
        prefilter=prefilter_state,
    )


def _flags_to_string(parsed: GrepFlags) -> str:
    """Serializa unos flags a la forma `-rn` que espera `parse_grep_flags`."""
    chars = ""
    if parsed.ignore_case:
        chars += "i"
    if parsed.recursive:
        chars += "r"
    if parsed.line_number:
        chars += "n"
    if parsed.files_with_matches:
        chars += "l"
    if parsed.extended_regex:
        chars += "E"
    return f"-{chars}" if chars else ""


def _scan(
    vfs: VirtualFS,
    target_files: list[str],
    regex: re.Pattern,
    parsed: GrepFlags,
) -> list[GrepHit]:
    """Escaneo en memoria de los ficheros candidatos."""
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


def _fts_prefilter(
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
    getter = getattr(vfs, "project_db_path", None)
    if getter is not None:
        return getter(slug)
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
