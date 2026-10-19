"""Resolución del proyecto APEX: UNA sola implementación.

Por qué existe
--------------
Hasta el 2026-10-19 había 13 copias de "buscar la raíz del proyecto"
(6 en `.claude/hooks/`, 6 en `.codex/hooks/`, una en `mcp/apex_server.py` y
otra en `mcp/handlers/_common.py`), cada una con reglas distintas:

- unas buscan `.apex/context.db`, otras `.apex/` o `.git/`;
- unas cortan al llegar al home y otras no;
- unas devuelven `None` y otras el CWD como fallback.

La divergencia tenía consecuencias reales: una ejecución desde el home
resolvía `~/.apex/context.db` —la memoria global de errores graves— como si
fuera el contexto de un proyecto. Eso fue lo que escribió el estado del
proyecto "Motor Fisico 2D Propio" en la BD global (2026-09-22), y lo que
metió en la memoria global el estado de `bookmarks-rag` y los logs de
sesión de TFG-SMA-Writer y gti-orienta.

La regla que se違反 con todas las variantes es la misma: **el home NUNCA es
un proyecto**. `~/.apex/` es memoria global append-only, no el contexto de
ningún proyecto.

Contrato
--------
- `find_project_root()`: devuelve la raíz del proyecto o `None`. `None`
  significa "esto no es un proyecto APEX" y quien llama decide.
- `resolve_project_root()`: como el anterior, pero cae al CWD si no hay
  proyecto. Es lo que necesita el servidor MCP, que avisa después.
- `is_global_memory(path)`: `True` si la ruta apunta a la memoria global.
- `assert_not_global_memory(path)`: lanza si lo apunta.

Uso:
    from lib.project_root import find_project_root
    root = find_project_root()          # None si no hay proyecto
"""
from __future__ import annotations

import os
from pathlib import Path


# La memoria global de errores graves. NUNCA es el contexto de un proyecto.
GLOBAL_MEMORY_DIRNAME = ".apex"


class GlobalMemoryError(RuntimeError):
    """La ruta apunta a la memoria global de APEX, no a un proyecto."""


def _home() -> Path:
    """El home del usuario, resuelto en cada llamada.

    Se resuelve en cada llamada (no en import) porque los tests monkeypatchean
    HOME y porque `Path.home()` puede cambiar entre invocaciones del MCP.
    """
    return Path(os.path.expanduser("~")).resolve()


def is_global_memory(path: Path | str) -> bool:
    """¿La ruta apunta a la memoria global `~/.apex`?

    True si la ruta ES el directorio `~/.apex` o está dentro de él. La
    comparación se hace sobre rutas resueltas, para que un symlink no la
    esquive.
    """
    try:
        objetivo = Path(path).expanduser().resolve()
    except (OSError, RuntimeError):
        return False
    global_dir = (_home() / GLOBAL_MEMORY_DIRNAME).resolve()
    return objetivo == global_dir or global_dir in objetivo.parents


def assert_not_global_memory(path: Path | str) -> None:
    """Lanza `GlobalMemoryError` si la ruta apunta a la memoria global."""
    if is_global_memory(path):
        raise GlobalMemoryError(
            f"{path} está dentro de la memoria global de APEX "
            f"({_home() / GLOBAL_MEMORY_DIRNAME}). Ese directorio es memoria "
            f"append-only de errores graves cross-project, nunca el contexto "
            f"de un proyecto."
        )


def _is_project_dir(parent: Path) -> bool:
    """¿Este directorio es la raíz de un proyecto APEX?

    Vale si tiene `.apex/` (con o sin `context.db`) o `.git/`. Un repo git
    sin `.apex/` todavía es un proyecto candidato: el flujo lo inicializa.
    """
    if (parent / GLOBAL_MEMORY_DIRNAME).is_dir():
        return True
    if (parent / ".git").exists():
        return True
    return False


def find_project_root(start: Path | str | None = None) -> Path | None:
    """Raíz del proyecto APEX que contiene `start`, o `None`.

    Sube desde `start` (por defecto, el CWD) buscando `.apex/` o `.git/`.

    REGLAS:
    - El home NUNCA es un proyecto: al alcanzarlo, la búsqueda para. Así
      `~/.apex/` (memoria global) queda fuera por construcción.
    - `None` significa "no hay proyecto". Quien llama decide si eso es un
      error (el servidor MCP) o un "no hago nada" (los hooks).
    """
    inicio = Path(start) if start is not None else Path.cwd()
    try:
        inicio = inicio.expanduser().resolve()
    except (OSError, RuntimeError):
        return None

    home = _home()
    for parent in [inicio, *inicio.parents]:
        if parent == home:
            # El home y sus subdirectorios no son proyecto. En particular
            # `~/.apex/`, que es la memoria global.
            return None
        if _is_project_dir(parent):
            return parent
        if parent == parent.parent:
            break
    return None


def resolve_project_root(start: Path | str | None = None) -> Path:
    """Raíz del proyecto, o el CWD si no hay ninguno.

    Es el comportamiento que espera el servidor MCP: `_get_db()` avisa
    después si el resultado no tiene `.apex/` propio.
    """
    root = find_project_root(start)
    if root is not None:
        return root
    base = Path(start) if start is not None else Path.cwd()
    try:
        return base.expanduser().resolve()
    except (OSError, RuntimeError):
        return base


def project_db_path(start: Path | str | None = None) -> Path | None:
    """Ruta de la `context.db` del proyecto, o `None` si no hay proyecto.

    Nunca devuelve la de la memoria global: si el resultado fuera ésa, se
    trata como "no hay proyecto".
    """
    root = find_project_root(start)
    if root is None:
        return None
    db_path = root / GLOBAL_MEMORY_DIRNAME / "context.db"
    if is_global_memory(db_path):
        return None
    return db_path
