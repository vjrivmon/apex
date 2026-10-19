#!/usr/bin/env python3
"""Mantiene fresco el bloque de estado del CLAUDE.md de APEX.

Se dispara en dos momentos (petición de Vicente, 2026-07-21):
  - PostToolUse de `apex_set_phase`: el proyecto cambió de fase, su estado
    cambió con ella.
  - Stop: al cerrar la sesión, si se tocó código.

El problema que resuelve: el CLAUDE.md escrito a mano acumuló ~42 afirmaciones
falsas (decía 695 tests cuando había 722, marcaba sprints cerrados como
pendientes). Una sesión que lo leyera arrancaba con datos falsos.

NO bloquea nunca: si algo falla, avisa por stderr y deja seguir. Regenerar la
documentación no puede tumbar el flujo de trabajo.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

TIMEOUT_SEGUNDOS = 90


def _repo_de(cwd: Path) -> Path | None:
    """Sube buscando el repo de APEX (el que tiene el script y el CLAUDE.md)."""
    for base in [cwd, *cwd.parents]:
        if (base / "scripts/refresh_state.py").is_file() and (
            base / "CLAUDE.md"
        ).is_file():
            return base
    return None


def _toco_codigo(repo: Path) -> bool:
    """True si hay cambios en código o tests respecto a HEAD."""
    try:
        salida = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo, capture_output=True, text=True, timeout=15,
        ).stdout
    except (subprocess.SubprocessError, OSError):
        return False

    for linea in salida.splitlines():
        ruta = linea[3:].strip()
        if ruta.startswith(("lib/", "mcp/", "tests/", "skills/", "commands/")):
            return True
    return False


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        payload = {}

    # Si el payload trae cwd, mandá él: `Path.cwd()` sería el directorio del
    # proceso, que en un test o en un subshell no es donde está el usuario.
    cwd_raw = payload.get("cwd")
    cwd = Path(cwd_raw) if cwd_raw else Path.cwd()
    repo = _repo_de(cwd)
    if repo is None:
        return 0  # no estamos en el repo de APEX: nada que hacer

    evento = payload.get("hook_event_name", "")
    # En Stop solo merece la pena si se tocó código; en cambio de fase, siempre.
    if evento == "Stop" and not _toco_codigo(repo):
        return 0

    python = repo / ".venv/bin/python"
    if not python.is_file():
        python = Path(sys.executable)

    # SIN --run-tests: ejecutar la suite aquí haría que cada Stop y cada cambio
    # de fase costaran lo que tarde pytest. El recuento estático de funciones
    # `def test_` basta para detectar deriva; quien quiera el número
    # autoritativo corre `scripts/refresh_state.py --run-tests` a mano.
    try:
        proc = subprocess.run(
            [str(python), "scripts/refresh_state.py"],
            cwd=repo, capture_output=True, text=True, timeout=TIMEOUT_SEGUNDOS,
        )
    except subprocess.TimeoutExpired:
        print(
            "[refresh-state] la regeneración excedió "
            f"{TIMEOUT_SEGUNDOS}s; CLAUDE.md puede estar desfasado",
            file=sys.stderr,
        )
        return 0
    except OSError as exc:
        print(f"[refresh-state] no se pudo ejecutar: {exc}", file=sys.stderr)
        return 0

    salida = (proc.stdout or "").strip()
    if proc.returncode != 0:
        print(
            f"[refresh-state] falló: {(proc.stderr or '').strip()[:200]}",
            file=sys.stderr,
        )
    elif "actualizado" in salida:
        print(f"[refresh-state] {salida}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
