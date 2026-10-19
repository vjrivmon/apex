"""APEX VFS — materialización SQL→markdown de las categorías virtuales.

El 20% del filesystem virtual no existe en disco: se renderiza desde SQL
sobre demand. Este módulo implementa (blueprint S17 §3):

- `errors_to_md(slug)`          — errores de `<slug>/.apex/context.db`
- `skills_history_to_md(slug)`  — `role_invocations` + `grader_verdicts`
- `lessons_to_md(severity)`     — lecciones cross-project de `hub.db`

y el acceso CRUD a las dos tablas que el Sprint 17 creó pero nadie usó:
`vfs_render_cache` (caché de renders) y `vfs_query_log` (telemetría).

Mecanismo de invalidación del caché (riesgo R1 del blueprint)
--------------------------------------------------------------
1. **Clave direccionada por contenido**: `cache_key = sha256(query + rows)`.
   Si los datos fuente cambian, la clave cambia, así que una entrada vieja
   nunca se reutiliza por accidente. La invalidación es intrínseca: no
   depende de que alguien se acuerde de invalidar.
2. **`source_hash = sha256(rows)`**: permite invalidación selectiva
   (`invalidate_by_source_hash`) y detección de drift (`prune_stale`).
3. **Invalidación explícita**: `invalidate_all()` (tras un doctor run o
   cualquier escritura en la BD fuente) y `prune(keep_keys)` (limpia los
   huérfanos que deja la regla 1).
4. **TTL opcional** en la lectura (`max_age_seconds`): pasado el plazo la
   entrada se regenera aunque la clave no haya cambiado.

El caché ahorra el renderizado (formatear cientos de filas a markdown), no
la lectura SQL: para computar la clave hay que conocer las filas, y esa
lectura es la que garantiza que el contenido servido es fresco. Es un
intercambio deliberado: preferimos serving correcto a serving rápido.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

try:  # pragma: no cover - el import depende de cómo se cargue el módulo
    from lib.db_utils import get_sync_db
except ImportError:  # pragma: no cover
    from db_utils import get_sync_db  # type: ignore[no-redef]


# ── Constantes ───────────────────────────────────────────────────────────

CACHE_TABLE = "vfs_render_cache"
QUERY_LOG_TABLE = "vfs_query_log"

#: Separador de secciones del markdown renderizado. Cada sección empieza
#: por "\n## <id>" y el materializer la usa para exponer un fichero virtual
#: por item (`error-12.md`, `lesson-accent-obert-7.md`, ...).
SECTION_MARKER = "\n## "

_UNSAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")

ERRORS_QUERY = (
    "SELECT id, source, phase, description, cause, fix, lesson, severity, "
    "recurrence_count, created_at FROM errors ORDER BY id"
)
SKILLS_QUERY = (
    "SELECT id, role, phase, fired_at, context_summary, status "
    "FROM role_invocations ORDER BY id"
)
SKILLS_VERDICTS_QUERY = (
    "SELECT id, phase, quality, category, should_block, reasoning, created_at "
    "FROM grader_verdicts ORDER BY id"
)
LESSONS_QUERY = (
    "SELECT id, project_id, description, lesson, severity, recurrence_count, "
    "created_at FROM errors ORDER BY id"
)


# ── Utilidades ──────────────────────────────────────────────────────────


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _rows_digest(rows: Sequence[dict]) -> str:
    """Hash estable del contenido de las filas (independiente del orden de
    las claves, sensible al orden de las filas)."""
    payload = json.dumps(rows, sort_keys=True, default=str, ensure_ascii=False)
    return _sha256(payload)


def cache_key_for(query: str, rows: Sequence[dict]) -> str:
    """`sha256(query + rows)` — la clave del blueprint S17 §3."""
    return _sha256(query + "\n" + _rows_digest(rows))


def _safe_name(name: str) -> str:
    """Nombre de fichero virtual seguro (sin separadores de path)."""
    return _UNSAFE_NAME.sub("_", name)


def _open_ro(db_path: Path | str | None) -> sqlite3.Connection | None:
    """Abre una BD en modo solo-lectura. None si no existe o no se puede."""
    if db_path is None:
        return None
    path = Path(db_path)
    if not path.exists() or not path.is_file():
        return None
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.OperationalError:
        return None
    conn.row_factory = sqlite3.Row
    return conn


def _query_rows(
    db_path: Path | str | None, query: str, params: Sequence[Any] = ()
) -> list[dict]:
    """Ejecuta `query` en solo-lectura y devuelve las filas como dicts.

    Si la BD no existe, la tabla no existe o la query falla, devuelve []
    (best-effort: una categoría virtual vacía no es un error).
    """
    conn = _open_ro(db_path)
    if conn is None:
        return []
    try:
        cur = conn.execute(query, tuple(params))
        return [dict(row) for row in cur.fetchall()]
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()


# ── Caché de renders (CRUD sobre `vfs_render_cache`) ────────────────────


class RenderCache:
    """CRUD de `vfs_render_cache` en la `context.db` del proyecto actual.

    La tabla vive en la BD del proyecto desde el que se llama a la tool
    (no en la de los proyectos consultados): el hub y los `context.db`
    ajenos se abren siempre en solo-lectura.
    """

    def __init__(self, db_path: Path | str | None) -> None:
        self.db_path = Path(db_path) if db_path is not None else None
        self._enabled = bool(
            self.db_path is not None and self.db_path.exists()
        )

    # --- lectura ---------------------------------------------------------

    def get(
        self, cache_key: str, max_age_seconds: int | None = None
    ) -> tuple[str, str] | None:
        """Devuelve `(rendered, source_hash)` si la clave existe y no ha
        expirado; None si no hay entrada o si la BD no está disponible."""
        if not self._enabled or self.db_path is None:
            return None
        try:
            with get_sync_db(self.db_path) as conn:
                cur = conn.execute(
                    f"SELECT rendered, source_hash, generated_at FROM {CACHE_TABLE} "
                    "WHERE cache_key = ?",
                    (cache_key,),
                )
                row = cur.fetchone()
        except sqlite3.OperationalError:
            return None
        if row is None:
            return None
        rendered, source_hash, generated_at = row[0], row[1], row[2]
        if max_age_seconds is not None and generated_at:
            if _is_expired(generated_at, max_age_seconds):
                return None
        return rendered, (source_hash or "")

    def keys(self) -> set[str]:
        """Claves presentes en el caché."""
        if not self._enabled or self.db_path is None:
            return set()
        try:
            with get_sync_db(self.db_path) as conn:
                cur = conn.execute(f"SELECT cache_key FROM {CACHE_TABLE}")
                return {row[0] for row in cur.fetchall()}
        except sqlite3.OperationalError:
            return set()

    def count(self) -> int:
        """Número de entradas en el caché."""
        if not self._enabled or self.db_path is None:
            return 0
        try:
            with get_sync_db(self.db_path) as conn:
                cur = conn.execute(f"SELECT COUNT(*) FROM {CACHE_TABLE}")
                row = cur.fetchone()
        except sqlite3.OperationalError:
            return 0
        return int(row[0]) if row else 0

    # --- escritura -------------------------------------------------------

    def put(self, cache_key: str, rendered: str, source_hash: str) -> bool:
        """Inserta o reemplaza una entrada. False si no se pudo escribir."""
        if not self._enabled or self.db_path is None:
            return False
        try:
            with get_sync_db(self.db_path) as conn:
                conn.execute(
                    f"INSERT OR REPLACE INTO {CACHE_TABLE} "
                    "(cache_key, rendered, source_hash) VALUES (?, ?, ?)",
                    (cache_key, rendered, source_hash),
                )
                conn.commit()
        except sqlite3.OperationalError:
            return False
        return True

    def delete(self, cache_key: str) -> bool:
        """Borra una entrada por clave."""
        if not self._enabled or self.db_path is None:
            return False
        try:
            with get_sync_db(self.db_path) as conn:
                cur = conn.execute(
                    f"DELETE FROM {CACHE_TABLE} WHERE cache_key = ?", (cache_key,)
                )
                conn.commit()
        except sqlite3.OperationalError:
            return False
        return cur.rowcount > 0

    def invalidate_all(self) -> int:
        """Vacía el caché. Se usa tras escrituras masivas (doctor run,
        `apex_add_error`, sprints nuevos). Devuelve las filas borradas."""
        if not self._enabled or self.db_path is None:
            return 0
        try:
            with get_sync_db(self.db_path) as conn:
                cur = conn.execute(f"DELETE FROM {CACHE_TABLE}")
                conn.commit()
        except sqlite3.OperationalError:
            return 0
        return cur.rowcount

    def invalidate_by_source_hash(self, source_hash: str) -> int:
        """Invalidación selectiva: borra las entradas generadas por una
        fuente concreta (por ejemplo, los renders de un proyecto)."""
        if not self._enabled or self.db_path is None:
            return 0
        try:
            with get_sync_db(self.db_path) as conn:
                cur = conn.execute(
                    f"DELETE FROM {CACHE_TABLE} WHERE source_hash = ?", (source_hash,)
                )
                conn.commit()
        except sqlite3.OperationalError:
            return 0
        return cur.rowcount

    def prune(self, keep_keys: Iterable[str]) -> int:
        """Borra las entradas cuya clave no está en `keep_keys`.

        Es la limpieza de los huérfanos que deja la regla 1 (clave
        direccionada por contenido): cuando los datos cambian, la entrada
        vieja deja de ser alcanzable pero sigue ocupando sitio.
        """
        if not self._enabled or self.db_path is None:
            return 0
        keep = set(keep_keys)
        try:
            with get_sync_db(self.db_path) as conn:
                cur = conn.execute(f"SELECT cache_key FROM {CACHE_TABLE}")
                stale = [row[0] for row in cur.fetchall() if row[0] not in keep]
                if stale:
                    conn.executemany(
                        f"DELETE FROM {CACHE_TABLE} WHERE cache_key = ?",
                        [(key,) for key in stale],
                    )
                    conn.commit()
        except sqlite3.OperationalError:
            return 0
        return len(stale)

    def prune_stale(self, valid_source_hashes: Iterable[str]) -> int:
        """Borra las entradas cuyo `source_hash` ya no corresponde a
        ninguna fuente viva. Detecta drift del caché."""
        if not self._enabled or self.db_path is None:
            return 0
        valid = set(valid_source_hashes)
        try:
            with get_sync_db(self.db_path) as conn:
                cur = conn.execute(f"SELECT cache_key, source_hash FROM {CACHE_TABLE}")
                stale = [
                    row[0] for row in cur.fetchall()
                    if (row[1] or "") not in valid
                ]
                if stale:
                    conn.executemany(
                        f"DELETE FROM {CACHE_TABLE} WHERE cache_key = ?",
                        [(key,) for key in stale],
                    )
                    conn.commit()
        except sqlite3.OperationalError:
            return 0
        return len(stale)


def _is_expired(generated_at: str, max_age_seconds: int) -> bool:
    """True si la entrada del caché es más vieja que `max_age_seconds`."""
    from datetime import datetime, timezone

    try:
        stamp = datetime.fromisoformat(str(generated_at).replace("Z", "+00:00"))
    except ValueError:
        return False
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - stamp).total_seconds()
    return age > max_age_seconds


# ── Telemetría (CRUD sobre `vfs_query_log`) ─────────────────────────────


class QueryLog:
    """CRUD de `vfs_query_log`: una fila por consulta al VFS.

    Sirve para detectar paths calientes (futuro: caché más agresivo) y
    para auditar qué se le pidió al filesystem virtual.
    """

    def __init__(self, db_path: Path | str | None) -> None:
        self.db_path = Path(db_path) if db_path is not None else None
        self._enabled = bool(
            self.db_path is not None and self.db_path.exists()
        )

    def record(
        self,
        command: str,
        project_slug: str | None = None,
        hits: int = 0,
        latency_ms: int = 0,
    ) -> bool:
        """Registra una consulta. False si no se pudo escribir."""
        if not self._enabled or self.db_path is None:
            return False
        try:
            with get_sync_db(self.db_path) as conn:
                conn.execute(
                    f"INSERT INTO {QUERY_LOG_TABLE} "
                    "(command, project_slug, hits, latency_ms) VALUES (?, ?, ?, ?)",
                    (command, project_slug, int(hits), int(latency_ms)),
                )
                conn.commit()
        except sqlite3.OperationalError:
            return False
        return True

    def count(self) -> int:
        """Número de consultas registradas."""
        if not self._enabled or self.db_path is None:
            return 0
        try:
            with get_sync_db(self.db_path) as conn:
                cur = conn.execute(f"SELECT COUNT(*) FROM {QUERY_LOG_TABLE}")
                row = cur.fetchone()
        except sqlite3.OperationalError:
            return 0
        return int(row[0]) if row else 0

    def recent(self, limit: int = 20) -> list[dict]:
        """Últimas consultas registradas (más recientes primero)."""
        if not self._enabled or self.db_path is None:
            return []
        try:
            with get_sync_db(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.execute(
                    f"SELECT ts, command, project_slug, hits, latency_ms "
                    f"FROM {QUERY_LOG_TABLE} ORDER BY id DESC LIMIT ?",
                    (int(limit),),
                )
                return [dict(row) for row in cur.fetchall()]
        except sqlite3.OperationalError:
            return []


# ── Renderizadores ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class RenderResult:
    """Resultado de un render: el markdown, su clave de caché y si salió
    del caché o se acaba de generar."""

    markdown: str
    cache_key: str
    source_hash: str
    cached: bool
    rows: int

    @property
    def items(self) -> list[tuple[str, str]]:
        """`(nombre_de_fichero, markdown)` por sección del documento."""
        return split_sections(self.markdown)


def cached_render(
    query: str,
    rows: Sequence[dict],
    render: Callable[[Sequence[dict]], str],
    cache: RenderCache | None = None,
    max_age_seconds: int | None = None,
) -> RenderResult:
    """Renderiza `rows` cacheando el resultado por contenido.

    La clave es `sha256(query + rows)`: si los datos cambian, la clave
    cambia y el render viejo deja de ser alcanzable (invalidación
    intrínseca, riesgo R1 del blueprint).
    """
    key = cache_key_for(query, rows)
    source_hash = _rows_digest(rows)
    if cache is not None:
        hit = cache.get(key, max_age_seconds=max_age_seconds)
        if hit is not None:
            return RenderResult(
                markdown=hit[0],
                cache_key=key,
                source_hash=hit[1] or source_hash,
                cached=True,
                rows=len(rows),
            )
    markdown = render(rows)
    if cache is not None:
        cache.put(key, markdown, source_hash)
    return RenderResult(
        markdown=markdown,
        cache_key=key,
        source_hash=source_hash,
        cached=False,
        rows=len(rows),
    )


def split_sections(markdown: str) -> list[tuple[str, str]]:
    """Divide un markdown renderizado en secciones `## <id>`.

    Devuelve `[(id, texto_de_la_sección)]`. El texto incluye la línea
    `## <id>` para que el fichero virtual sea legible por sí solo.
    """
    sections: list[tuple[str, str]] = []
    current_id: str | None = None
    buffer: list[str] = []
    for line in markdown.splitlines(keepends=True):
        if line.startswith("## "):
            if current_id is not None:
                sections.append((current_id, "".join(buffer).strip() + "\n"))
            current_id = line[3:].strip()
            buffer = [line]
        elif current_id is not None:
            buffer.append(line)
    if current_id is not None:
        sections.append((current_id, "".join(buffer).strip() + "\n"))
    return sections


def _fmt(value: Any, default: str = "—") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def _render_errors(slug: str, rows: Sequence[dict]) -> str:
    """Markdown de los errores de un proyecto."""
    severities: dict[str, int] = {}
    for row in rows:
        sev = _fmt(row.get("severity"), "medium")
        severities[sev] = severities.get(sev, 0) + 1
    resumen = (
        ", ".join(f"{k}={v}" for k, v in sorted(severities.items()))
        if severities
        else "—"
    )
    lines = [
        f"# Errores de {slug}",
        "",
        f"- **Total:** {len(rows)}",
        f"- **Severidades:** {resumen}",
        "",
    ]
    if not rows:
        lines.append("_Sin errores registrados._")
        lines.append("")
        return "\n".join(lines)
    for row in rows:
        lines.append(f"## error-{row.get('id')}")
        lines.append("")
        lines.append(f"- **Severidad:** {_fmt(row.get('severity'))}")
        lines.append(f"- **Repeticiones:** {_fmt(row.get('recurrence_count'), '1')}")
        lines.append(f"- **Fase:** {_fmt(row.get('phase'))}")
        lines.append(f"- **Origen:** {_fmt(row.get('source'))}")
        lines.append(f"- **Creado:** {_fmt(row.get('created_at'))}")
        lines.append(f"- **Descripción:** {_fmt(row.get('description'))}")
        lines.append(f"- **Causa:** {_fmt(row.get('cause'), '—')}")
        lines.append(f"- **Arreglo:** {_fmt(row.get('fix'), '—')}")
        lines.append(f"- **Lección:** {_fmt(row.get('lesson'), '—')}")
        lines.append("")
    return "\n".join(lines)


def _render_skills_history(slug: str, rows: Sequence[dict]) -> str:
    """Markdown del historial de skills de un proyecto.

    `rows` mezcla invocaciones de roles y verdicts del grader; cada item
    lleva su prefijo para que el id sea único.
    """
    invocaciones = [r for r in rows if r.get("kind") == "invocation"]
    verdicts = [r for r in rows if r.get("kind") == "verdict"]
    lines = [
        f"# Historial de skills de {slug}",
        "",
        f"- **Invocaciones:** {len(invocaciones)}",
        f"- **Verdicts del grader:** {len(verdicts)}",
        "",
    ]
    if not rows:
        lines.append("_Sin historial registrado._")
        lines.append("")
        return "\n".join(lines)
    for row in rows:
        if row.get("kind") == "invocation":
            lines.append(f"## invocation-{row.get('id')}")
            lines.append("")
            lines.append(f"- **Rol:** {_fmt(row.get('role'))}")
            lines.append(f"- **Fase:** {_fmt(row.get('phase'))}")
            lines.append(f"- **Invocado:** {_fmt(row.get('fired_at'))}")
            lines.append(f"- **Estado:** {_fmt(row.get('status'))}")
            lines.append(f"- **Contexto:** {_fmt(row.get('context_summary'), '—')}")
        else:
            lines.append(f"## verdict-{row.get('id')}")
            lines.append("")
            lines.append(f"- **Fase:** {_fmt(row.get('phase'))}")
            lines.append(f"- **Calidad:** {_fmt(row.get('quality'))}/4")
            lines.append(f"- **Categoría:** {_fmt(row.get('category'))}")
            lines.append(
                f"- **Bloquea:** {'sí' if row.get('should_block') else 'no'}"
            )
            lines.append(f"- **Creado:** {_fmt(row.get('created_at'))}")
            lines.append(f"- **Razonamiento:** {_fmt(row.get('reasoning'))}")
        lines.append("")
    return "\n".join(lines)


def _render_lessons(severity: str | None, rows: Sequence[dict]) -> str:
    """Markdown de las lecciones cross-project del hub."""
    projects = sorted({_fmt(r.get("project_id"), "—") for r in rows})
    titulo = f" (severidad: {severity})" if severity else ""
    lines = [
        f"# Lecciones cross-project{titulo}",
        "",
        f"- **Total:** {len(rows)}",
        f"- **Proyectos:** {len(projects)}",
        "",
    ]
    if not rows:
        lines.append("_Sin lecciones registradas._")
        lines.append("")
        return "\n".join(lines)
    for row in rows:
        project = _safe_name(_fmt(row.get("project_id"), "desconocido"))
        lines.append(f"## lesson-{project}-{row.get('id')}")
        lines.append("")
        lines.append(f"- **Proyecto:** {_fmt(row.get('project_id'))}")
        lines.append(f"- **Severidad:** {_fmt(row.get('severity'))}")
        lines.append(f"- **Repeticiones:** {_fmt(row.get('recurrence_count'), '1')}")
        lines.append(f"- **Creado:** {_fmt(row.get('created_at'))}")
        lines.append(f"- **Descripción:** {_fmt(row.get('description'))}")
        lines.append(f"- **Lección:** {_fmt(row.get('lesson'), '—')}")
        lines.append("")
    return "\n".join(lines)


# ── API pública de renderizado ──────────────────────────────────────────


def errors_to_md(
    slug: str,
    source_db: Path | str | None,
    cache: RenderCache | None = None,
) -> str:
    """Errores de `<slug>` en markdown. Idempotente: mismos datos → mismo
    markdown, byte a byte."""
    rows = _query_rows(source_db, ERRORS_QUERY)
    return cached_render(ERRORS_QUERY, rows, lambda r: _render_errors(slug, r), cache).markdown


def skills_history_to_md(
    slug: str,
    source_db: Path | str | None,
    cache: RenderCache | None = None,
) -> str:
    """Historial de skills (`role_invocations` + `grader_verdicts`) en markdown."""
    rows = _query_rows(source_db, SKILLS_QUERY)
    for row in rows:
        row["kind"] = "invocation"
    verdicts = _query_rows(source_db, SKILLS_VERDICTS_QUERY)
    for row in verdicts:
        row["kind"] = "verdict"
    combined = rows + verdicts
    return cached_render(
        SKILLS_QUERY + "|" + SKILLS_VERDICTS_QUERY,
        combined,
        lambda r: _render_skills_history(slug, r),
        cache,
    ).markdown


def lessons_to_md(
    severity: str | None,
    hub_db: Path | str | None,
    cache: RenderCache | None = None,
    project: str | None = None,
) -> str:
    """Lecciones cross-project del hub en markdown.

    Fuente: `hub.db.cross_project_lessons` si existe; si no, la tabla
    `errors` del hub (que es de donde el hub agrega las lecciones de
    todos los proyectos). `severity` filtra por severidad; `project` por
    proyecto.
    """
    rows = _lessons_rows(hub_db, severity, project)
    return cached_render(
        LESSONS_QUERY,
        rows,
        lambda r: _render_lessons(severity, r),
        cache,
    ).markdown


def _lessons_rows(
    hub_db: Path | str | None, severity: str | None, project: str | None
) -> list[dict]:
    """Filas de lecciones, con el filtro de severidad y proyecto aplicado."""
    rows = _query_rows(hub_db, LESSONS_QUERY)
    if severity:
        sev = severity.lower()
        rows = [r for r in rows if _fmt(r.get("severity"), "").lower() == sev]
    if project:
        rows = [r for r in rows if _fmt(r.get("project_id"), "") == project]
    return rows


# ── Materializador para el VirtualFS ─────────────────────────────────────


class SqlMaterializer:
    """Materializa las categorías virtuales del VirtualFS.

    Contrato con `lib.vfs.VirtualFS` (duck-typed, para no crear un import
    circular):

    - `stat(resolved) -> dict | None`
        `{"kind": "file"|"dir", "size_bytes": int}` o None si no existe.
    - `list_dir(resolved) -> list[dict]`
        `[{"name": str, "kind": "file"|"dir", "size_bytes": int}]`
    - `read_file(resolved) -> str`
        Contenido markdown del fichero.
    - `list_files(resolved) -> list[str]`
        Paths virtuales de los ficheros de la categoría.
    """

    def __init__(
        self,
        vfs: Any,
        cache_db_path: Path | str | None = None,
        hub_db_path: Path | str | None = None,
    ) -> None:
        self.vfs = vfs
        self.cache = RenderCache(cache_db_path)
        self.hub_db_path = Path(hub_db_path) if hub_db_path is not None else None

    # --- helpers ---------------------------------------------------------

    def _project_db(self, slug: str) -> Path | None:
        getter = getattr(self.vfs, "project_db_path", None)
        if getter is None:
            return None
        return getter(slug)

    def _render(self, category: str, slug: str | None) -> tuple[str, list[tuple[str, str]]]:
        """Devuelve (markdown_agregado, [(nombre, markdown_de_la_sección)])."""
        if category == "errors":
            if not slug:
                return "", []
            db = self._project_db(slug)
            markdown = errors_to_md(slug, db, self.cache)
        elif category == "skills-history":
            if not slug:
                return "", []
            db = self._project_db(slug)
            markdown = skills_history_to_md(slug, db, self.cache)
        elif category == "lessons-critical":
            markdown = lessons_to_md(
                "critical", self.hub_db_path, self.cache
            )
        elif category == "lessons-by-project":
            if slug:
                markdown = lessons_to_md(
                    None, self.hub_db_path, self.cache, project=slug
                )
            else:
                markdown = ""
        else:
            return "", []
        return markdown, split_sections(markdown)

    def _item_names(self, category: str, sections: list[tuple[str, str]]) -> list[str]:
        """Nombre de fichero virtual por sección, según la categoría."""
        return [f"{_safe_name(name)}.md" for name, _ in sections]

    @staticmethod
    def _file_name(resolved: Any) -> str:
        """Nombre del fichero virtual pedido (último segmento del subpath).

        El resolver devuelve el subpath completo: para
        `/lessons/by-project/apex.md` es `by-project/apex.md`.
        """
        subpath = (resolved.subpath or "").strip("/")
        return subpath.rsplit("/", 1)[-1] if subpath else ""

    # --- contrato con VirtualFS ------------------------------------------

    def stat(self, resolved: Any) -> dict | None:
        """Metadatos del path virtual resuelto."""
        category = resolved.category
        subpath = self._file_name(resolved)
        if not subpath:
            return {"kind": "dir", "size_bytes": 0}
        if category == "lessons-by-project":
            # Cada proyecto es un único fichero agregado: `<slug>.md`.
            if not subpath.endswith(".md") or not resolved.slug:
                return None
            markdown = lessons_to_md(
                None, self.hub_db_path, self.cache, project=resolved.slug
            )
            return {"kind": "file", "size_bytes": len(markdown.encode("utf-8"))}
        _markdown, sections = self._render(category, resolved.slug)
        names = self._item_names(category, sections)
        for name, (_id, text) in zip(names, sections):
            if name == subpath:
                return {"kind": "file", "size_bytes": len(text.encode("utf-8"))}
        return None

    def list_dir(self, resolved: Any) -> list[dict]:
        """Entries del directorio virtual."""
        category = resolved.category
        if category == "lessons-by-project" and not self._file_name(resolved):
            return self._list_lessons_by_project()
        _markdown, sections = self._render(category, resolved.slug)
        names = self._item_names(category, sections)
        entries: list[dict] = []
        for name, (_id, text) in zip(names, sections):
            entries.append(
                {
                    "name": name,
                    "kind": "file",
                    "size_bytes": len(text.encode("utf-8")),
                }
            )
        return entries

    def list_files(self, resolved: Any) -> list[str]:
        """Paths virtuales de los ficheros de la categoría."""
        category = resolved.category
        subpath = self._file_name(resolved)
        if category == "lessons-by-project":
            if subpath:
                return [f"/lessons/by-project/{subpath}"]
            return [
                f"/lessons/by-project/{entry['name']}"
                for entry in self._list_lessons_by_project()
            ]
        _markdown, sections = self._render(category, resolved.slug)
        names = self._item_names(category, sections)
        base = self._base_path(category, resolved.slug)
        return [f"{base}/{name}" for name in names]

    def read_file(self, resolved: Any) -> str:
        """Contenido markdown del fichero virtual."""
        category = resolved.category
        subpath = self._file_name(resolved)
        if category == "lessons-by-project":
            if not subpath:
                return ""
            return lessons_to_md(
                None, self.hub_db_path, self.cache, project=resolved.slug
            )
        _markdown, sections = self._render(category, resolved.slug)
        names = self._item_names(category, sections)
        for name, (_id, text) in zip(names, sections):
            if name == subpath:
                return text
        raise KeyError(subpath)

    # --- internos --------------------------------------------------------

    @staticmethod
    def _base_path(category: str, slug: str | None) -> str:
        if category == "errors":
            return f"/projects/{slug}/errors"
        if category == "skills-history":
            return f"/projects/{slug}/skills-history"
        if category == "lessons-critical":
            return "/lessons/critical"
        if category == "lessons-by-project":
            return "/lessons/by-project"
        return "/lessons"

    def _list_lessons_by_project(self) -> list[dict]:
        """Ficheros `by-project/<slug>.md`: un proyecto por lección."""
        rows = _lessons_rows(self.hub_db_path, None, None)
        projects = sorted({_fmt(r.get("project_id"), "") for r in rows if r.get("project_id")})
        entries: list[dict] = []
        for project in projects:
            markdown = lessons_to_md(
                None, self.hub_db_path, self.cache, project=project
            )
            entries.append(
                {
                    "name": f"{_safe_name(project)}.md",
                    "kind": "file",
                    "size_bytes": len(markdown.encode("utf-8")),
                }
            )
        return entries
