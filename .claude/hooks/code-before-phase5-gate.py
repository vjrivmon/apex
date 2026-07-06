#!/usr/bin/env python3
"""PreToolUse hook: bloquea escribir CÓDIGO DE PRODUCCIÓN antes de la fase 5.

Auditoría 2026-07-03 (C13): el enforcement de APEX era opt-in — el gate solo
mordía si el agente elegía llamar apex_set_phase. Un agente que abría un editor
y escribía código a secas nunca se topaba con ninguna guarda. Este hook cierra
ese hueco: hace vinculante la regla absoluta #3 ("NUNCA generar código antes de
fase 5") en el punto de acción (Write/Edit/MultiEdit), no como prosa.

Solo actúa en proyectos APEX (existe .apex/context.db). Bloquea SOLO ficheros
fuente de producción; deja pasar wiki, docs, tests, config y todo lo de .apex/.

Escape: variable de entorno APEX_ALLOW_EARLY_CODE=1 (equivalente al force=True
de los otros gates; deja rastro en el entorno de la sesión).

Convención hooks: stdin JSON con tool_name+tool_input; exit 0 permite, exit 2
bloquea (stderr → usuario).
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

TARGET_TOOLS = {"Write", "Edit", "MultiEdit"}

# Extensiones que consideramos código de producción.
_CODE_EXT = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".go", ".rs",
    ".java", ".kt", ".rb", ".php", ".c", ".cc", ".cpp", ".h", ".hpp",
    ".cs", ".swift", ".scala", ".ex", ".exs", ".vue", ".svelte",
}

# Raíces/segmentos donde escribir NUNCA se bloquea (no es código de producción).
_SAFE_SEGMENTS = {
    ".apex", "wiki", "docs", "doc", "tests", "test", "__tests__", "spec",
    ".claude", ".github", "node_modules", ".venv",
}
# Nombres de fichero que son config/scaffold, no lógica de producción.
_SAFE_NAMES = {
    "pyproject.toml", "package.json", "package-lock.json", "requirements.txt",
    "setup.py", "setup.cfg", "tsconfig.json", "dockerfile", "docker-compose.yml",
    ".gitignore", "readme.md", "conftest.py", "makefile",
}


def _find_context_db(start: Path) -> Path | None:
    for parent in [start, *start.parents]:
        candidate = parent / ".apex" / "context.db"
        if candidate.exists():
            return candidate
    return None


def _current_phase_number(db_path: Path) -> int | None:
    """Fase in_progress más baja. None si no hay ninguna o error."""
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=2)
        cur = conn.execute(
            "SELECT phase_number FROM phases WHERE status='in_progress' "
            "ORDER BY phase_number LIMIT 1")
        row = cur.fetchone()
        conn.close()
        return int(row[0]) if row else None
    except Exception:
        return None


def _extract_paths(tool_input: dict) -> list[str]:
    paths = []
    for key in ("file_path", "path", "notebook_path"):
        v = tool_input.get(key)
        if isinstance(v, str):
            paths.append(v)
    return paths


def _is_production_code(path_str: str, project_root: Path) -> bool:
    p = Path(path_str)
    if p.suffix.lower() not in _CODE_EXT:
        return False
    if p.name.lower() in _SAFE_NAMES:
        return False
    # Segmentos seguros en cualquier parte de la ruta relativa al proyecto.
    try:
        rel = p.resolve().relative_to(project_root.resolve())
        parts = set(rel.parts)
    except Exception:
        parts = set(p.parts)
    if parts & _SAFE_SEGMENTS:
        return False
    # test_*.py / *_test.go etc. son tests, no producción.
    name = p.name.lower()
    if name.startswith("test_") or "_test." in name or name.endswith(".test.ts") \
            or name.endswith(".test.js") or name.endswith(".spec.ts"):
        return False
    return True


def main() -> int:
    if os.environ.get("APEX_ALLOW_EARLY_CODE") == "1":
        return 0
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0

    tool_name = payload.get("tool_name") or payload.get("name") or ""
    if tool_name not in TARGET_TOOLS:
        return 0

    tool_input = payload.get("tool_input") or payload.get("arguments") or {}
    paths = _extract_paths(tool_input)
    if not paths:
        return 0

    cwd = Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    db_path = _find_context_db(cwd)
    if not db_path:
        return 0  # no es proyecto APEX: no aplica
    project_root = db_path.parent.parent

    offending = [p for p in paths if _is_production_code(p, project_root)]
    if not offending:
        return 0

    phase = _current_phase_number(db_path)
    if phase is not None and phase >= 5:
        return 0  # ya en fase de implementación

    where = "sin fase in_progress" if phase is None else f"en fase {phase}"
    print(
        "code-before-phase5-gate.py BLOQUEA (regla absoluta #3):\n"
        f"  Intento de escribir código de producción {where}: {offending[0]}\n"
        "  Las fases 0-4 son análisis y diseño; el código empieza en fase 5.\n"
        "\n"
        "Resolución: cierra las fases de diseño y entra a fase 5 "
        "(apex_set_phase(5, 'in_progress')).\n"
        "Override: exporta APEX_ALLOW_EARLY_CODE=1 en la sesión.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
