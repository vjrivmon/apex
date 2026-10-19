"""Errores cross-project con recurrencia REAL, calculada al leer.

Por qué existe esto
-------------------
`hub.db.errors.recurrence_count` es la recurrencia LOCAL: `add_error` en el
proyecto la incrementa sólo cuando el mismo error se vuelve a registrar en la
MISMA `context.db`. El escáner de apex-hub copia ese valor tal cual
(`backend/scanner.py:121`), así que en la práctica las 367 filas de `hub.db`
tienen `recurrence_count = 1`.

Consecuencia medida (auditoría 2026-10-19): el `ORDER BY recurrence_count DESC`
de `session-start.py` era DEGENERADO. Con todos los valores empatados a 1 no
ordenaba nada, y el `LIMIT 5` devolvía siempre los mismos errores (los
`focusnow` de mayor severidad, por orden de rowid). El hook anunciaba
"errores recurrentes" y devolvía errores que no lo eran.

La recurrencia que sí importa aquí es la CROSS-PROJECT: un error que se repite
en N proyectos distintos es una lección del ecosistema, no de un proyecto. Esa
se calcula al leer, agrupando por firma normalizada y contando proyectos
distintos. No requiere escribir en `hub.db` (que el MCP lee en modo read-only).

Este módulo es read-only y best-effort: cualquier error devuelve lista vacía.
"""
from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path

# Severidad de menor a mayor. El orden es explícito: el `CASE` de SQL sobre
# severidad no era determinista entre empates.
_SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}

# Cuántos errores cross-project se inyectan al abrir sesión.
DEFAULT_MAX_ERRORS = 5

# Firma de un error: minúsculas, sin puntuación, sin espacios dobles, truncada.
# Truncar a 120 caracteres evita que dos descripciones del mismo error con
# coletillas distintas se separen en clusters distintos.
_SIGNATURE_CHARS = 120

_WS_RE = re.compile(r"\s+")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9 ]+")


def normalize_signature(description: str | None) -> str:
    """Firma canónica de una descripción de error.

    Minúsculas, sin puntuación, espacios colapsados, truncada. Dos errores
    "casi iguales" en proyectos distintos deben colapsar en el mismo cluster.
    """
    text = (description or "").lower().strip()
    text = _NON_ALNUM_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text).strip()
    return text[:_SIGNATURE_CHARS].strip()


def max_errors() -> int:
    """Límite de errores inyectados, configurable por env."""
    raw = os.environ.get("APEX_CROSS_PROJECT_ERRORS", "")
    if raw.isdigit() and int(raw) > 0:
        return int(raw)
    return DEFAULT_MAX_ERRORS


def load_errors(hub_db: Path | str) -> list[dict]:
    """Lee la tabla `errors` de hub.db. Devuelve [] si no es accesible."""
    path = Path(hub_db)
    if not path.exists():
        return []
    conn = None
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2.0)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT project_id, description, lesson, severity, recurrence_count, "
            "phase, created_at FROM errors"
        ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.Error:
        return []
    finally:
        if conn is not None:
            try:
                conn.close()
            except sqlite3.Error:
                pass


def cluster_errors(rows: list[dict]) -> list[dict]:
    """Agrupa errores por firma y calcula la recurrencia cross-project.

    Cada cluster lleva:
      - `projects`: lista de project_id donde apareció
      - `project_count`: cuántos proyectos DISTINTOS (la recurrencia real)
      - `recurrence_count`: la recurrencia local máxima dentro de un proyecto
      - `severity`: la más alta del cluster
      - `description`/`lesson`: el de mayor severidad como representante
    """
    clusters: dict[str, dict] = {}
    for row in rows:
        signature = normalize_signature(row.get("description"))
        if not signature:
            continue
        project_id = row.get("project_id") or "?"
        cluster = clusters.get(signature)
        if cluster is None:
            cluster = {
                "signature": signature,
                "description": row.get("description") or "",
                "lesson": row.get("lesson") or "",
                "severity": row.get("severity") or "medium",
                "phase": row.get("phase"),
                "projects": [],
                "project_count": 0,
                "recurrence_count": 1,
                "last_seen": row.get("created_at") or "",
            }
            clusters[signature] = cluster
        if project_id not in cluster["projects"]:
            cluster["projects"].append(project_id)
        cluster["project_count"] = len(cluster["projects"])
        cluster["recurrence_count"] = max(
            cluster["recurrence_count"], int(row.get("recurrence_count") or 1)
        )
        # El representante es el de mayor severidad; a igualdad, el más reciente.
        if _severity_rank(row.get("severity")) < _severity_rank(cluster["severity"]):
            cluster["severity"] = row.get("severity") or "medium"
            cluster["description"] = row.get("description") or ""
            cluster["lesson"] = row.get("lesson") or ""
        if (row.get("created_at") or "") > cluster["last_seen"]:
            cluster["last_seen"] = row.get("created_at") or ""
    return list(clusters.values())


def rank_errors(clusters: list[dict]) -> list[dict]:
    """Ordena por recurrencia cross-project, luego severidad, luego recencia.

    El criterio es el que el hook ANUNCIABA: "errores recurrentes de OTROS
    proyectos". Antes devolvía cualquier cosa; ahora lo primero que ordena es
    cuántos proyectos distintos repiten el mismo error.
    """
    return sorted(
        clusters,
        key=lambda c: (
            -c["project_count"],
            _severity_rank(c.get("severity")),
            # `last_seen` es texto ISO; invertirlo en la clave es lo que
            # queremos (más reciente primero), pero `sorted` es ascendente, así
            # que se usa la negación del ordinal para no complicar la clave.
            _recency_key(c.get("last_seen")),
        ),
    )


def _recency_key(last_seen: str) -> tuple:
    """Clave que ordena de MÁS reciente a MENOS reciente.

    `last_seen` es un string de fecha. Los strings no se pueden negar, así que
    se invierte componente a componente (año, mes, día, ...) para que el
    orden ascendente de `sorted` place el más reciente primero.
    """
    parts = re.split(r"[-T: ]", last_seen or "")
    nums = []
    for part in parts[:6]:
        nums.append(int(part) if part.isdigit() else 0)
    while len(nums) < 6:
        nums.append(0)
    return tuple(-n for n in nums)


def _severity_rank(severity: str | None) -> int:
    return _SEVERITY_RANK.get((severity or "").lower(), 2)


def top_errors(
    hub_db: Path | str,
    exclude_project: str | None = None,
    limit: int | None = None,
) -> list[dict]:
    """Top errores cross-project, ya agrupados, ordenados y sin el proyecto actual.

    `exclude_project` descarta los errores del proyecto desde el que se llama:
    el hook se ejecuta con el cwd del proyecto activo y no tiene sentido
    recordarle al agente los errores de ese mismo proyecto.
    """
    rows = load_errors(hub_db)
    if exclude_project:
        rows = [r for r in rows if (r.get("project_id") or "") != exclude_project]
    clusters = cluster_errors(rows)
    ranked = rank_errors(clusters)
    if limit is None:
        limit = max_errors()
    return ranked[:limit]
