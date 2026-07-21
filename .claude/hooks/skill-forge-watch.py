#!/usr/bin/env python3
"""PostToolUse hook: alimenta el log de tool calls (D2) y dispara scans
periódicos del Skill Forge (Sprint 11.2).

NO bloquea. Sólo emite stderr cuando hay propuesta nueva, formato:

    [skill-forge] propuesta(s) nueva(s): slug1, slug2

Diseño:

- **Logging**: cada PostToolUse inserta una fila en `tool_call_log`. Operación
  barata (single INSERT, no más de 1ms).
- **Scan condicional**: sólo se ejecuta cuando el tool actual es un trigger
  (apex_set_phase, apex_grader_evaluate, apex_add_decision) o cuando han
  pasado >=APEX_FORGE_SCAN_EVERY_N_CALLS (default 25) calls desde el último
  scan. El último scan se persiste en `project_meta` (key=`forge_last_scan_id`).
- **Timeout**: el scan se rodea de un wall-clock check; si tarda >2s aborta
  silenciosamente.

Convención hooks Claude Code (PostToolUse):
- stdin: JSON con tool_name + tool_input + tool_response + cwd (a veces).
- stderr → mensaje al usuario; exit 0.
- Bajo NINGÚN concepto se debe imprimir a stdout o devolver exit != 0:
  eso bloquearía el ciclo del agente.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from pathlib import Path

# La raíz del repo debe estar en sys.path ANTES de `from lib.…`:
# el hook puede ejecutarse desde cualquier cwd.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from lib.hook_metrics import start_hook, end_hook

# Permite importar `lib/skill_forge.py` cuando el hook corre desde cualquier cwd
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "lib"))

try:
    import skill_forge as _forge
except Exception:
    _forge = None  # type: ignore


SCAN_TRIGGERS = {
    "mcp__apex__apex_set_phase",
    "mcp__apex__apex_grader_evaluate",
    "mcp__apex__apex_add_decision",
    "mcp__apex__apex_complete_step",
}

SCAN_EVERY_N = int(os.environ.get("APEX_FORGE_SCAN_EVERY_N_CALLS", "25"))
SCAN_TIMEOUT_S = float(os.environ.get("APEX_FORGE_SCAN_TIMEOUT_S", "2.0"))

# Tools cuya invocación NO se loguea: el propio forge, los archives, y los
# tools internos del propio hook system. Evita bucles y ruido.
SKIP_LOG = {
    "mcp__apex__apex_archive_output",
    "mcp__apex__apex_get_archived",
    "mcp__apex__apex_skill_forge_scan",
    "mcp__apex__apex_skill_forge_approve",
    "mcp__apex__apex_skill_forge_reject",
}


def _find_project_root(cwd: Path) -> Path | None:
    for parent in [cwd, *cwd.parents]:
        if (parent / ".apex" / "context.db").exists():
            return parent
    return None


def _short_args(tool_input: dict | str) -> str:
    if isinstance(tool_input, str):
        return tool_input[:200]
    if not isinstance(tool_input, dict):
        return str(tool_input)[:200]
    # Toma 2-3 keys más representativas
    snippet_parts: list[str] = []
    for k, v in list(tool_input.items())[:3]:
        s = str(v).replace("\n", " ")[:60]
        snippet_parts.append(f"{k}={s}")
    return " | ".join(snippet_parts)[:200]


def _last_scan_id(db_path: Path) -> int:
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.OperationalError:
        end_hook("skill-forge-watch", _hook_start, exit_code=0)
        return 0
    try:
        row = conn.execute(
            "SELECT value FROM project_meta WHERE key=?",
            ("forge_last_scan_id",),
        ).fetchone()
        return int(row[0]) if row and row[0] else 0
    except (sqlite3.OperationalError, ValueError):
        end_hook("skill-forge-watch", _hook_start, exit_code=0)
        return 0
    finally:
        conn.close()


def _set_last_scan_id(db_path: Path, value: int) -> None:
    try:
        conn = sqlite3.connect(str(db_path))
    except sqlite3.OperationalError:
        return
    try:
        conn.execute(
            "INSERT OR REPLACE INTO project_meta (key, value, updated_at) "
            "VALUES (?, ?, datetime('now'))",
            ("forge_last_scan_id", str(value)),
        )
        conn.commit()
    finally:
        conn.close()


def _current_max_log_id(db_path: Path) -> int:
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.OperationalError:
        end_hook("skill-forge-watch", _hook_start, exit_code=0)
        return 0
    try:
        row = conn.execute("SELECT MAX(id) FROM tool_call_log").fetchone()
        return int(row[0]) if row and row[0] else 0
    except sqlite3.OperationalError:
        end_hook("skill-forge-watch", _hook_start, exit_code=0)
        return 0
    finally:
        conn.close()


def main() -> int:
    _hook_start = start_hook("skill-forge-watch")
    if _forge is None:
        end_hook("skill-forge-watch", _hook_start, exit_code=0)
        return 0
    try:
        payload = json.load(sys.stdin)
    except Exception:
        end_hook("skill-forge-watch", _hook_start, exit_code=0)
        return 0

    tool = payload.get("tool_name", "") or ""
    cwd_raw = payload.get("cwd") or os.getcwd()
    project_root = _find_project_root(Path(cwd_raw))
    if project_root is None:
        end_hook("skill-forge-watch", _hook_start, exit_code=0)
        return 0

    db_path = _forge.context_db_path(project_root)

    # 1) Log de la tool call (alimenta D2)
    if tool and tool not in SKIP_LOG:
        try:
            _forge.log_tool_call(project_root, tool,
                                  _short_args(payload.get("tool_input") or {}))
        except Exception:
            pass

    # 2) Decidir si toca scan
    cur_id = _current_max_log_id(db_path)
    last_id = _last_scan_id(db_path)
    delta = cur_id - last_id

    is_trigger = tool in SCAN_TRIGGERS
    if not is_trigger and delta < SCAN_EVERY_N:
        end_hook("skill-forge-watch", _hook_start, exit_code=0)
        return 0

    # 3) Scan con timeout wall-clock
    t0 = time.monotonic()
    try:
        # Intentamos cargar la ruta de hub.db desde apex_server (lazy import)
        hub_db = _REPO_ROOT.parent / "apex-hub" / "data" / "hub.db"
        hub_path = hub_db if hub_db.exists() else None
        project_id = project_root.name
        written = _forge.scan_and_write(
            project_root,
            hub_db_path=hub_path,
            project_id=project_id,
        )
    except Exception:
        end_hook("skill-forge-watch", _hook_start, exit_code=0)
        return 0

    elapsed = time.monotonic() - t0
    if elapsed > SCAN_TIMEOUT_S:
        # Aún así guardamos el high-water mark — no queremos rebrotar al
        # siguiente call si el scan tardó mucho por carga puntual
        _set_last_scan_id(db_path, cur_id)
        sys.stderr.write(
            f"[skill-forge] scan tardó {elapsed:.1f}s (>={SCAN_TIMEOUT_S}s); "
            "abortado parcialmente\n"
        )
        end_hook("skill-forge-watch", _hook_start, exit_code=0)
        return 0

    _set_last_scan_id(db_path, cur_id)

    if not written:
        end_hook("skill-forge-watch", _hook_start, exit_code=0)
        return 0

    slugs = ", ".join(p.stem for p in written)
    sys.stderr.write(
        f"[skill-forge] {len(written)} propuesta(s) nueva(s): {slugs}\n"
        f"  revisa con: ls .apex/skill-proposals/\n"
    )
    end_hook("skill-forge-watch", _hook_start, exit_code=0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
