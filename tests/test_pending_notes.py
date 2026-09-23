"""Hook pending-notes: los pendientes de Obsidian llegan al contexto al abrir el proyecto."""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parent.parent / ".claude" / "hooks" / "pending-notes.py"


@pytest.fixture
def proyecto(tmp_path):
    root = tmp_path / "RoadToDevOps" / "Mi Proyecto"
    (root / ".apex").mkdir(parents=True)
    con = sqlite3.connect(root / ".apex" / "context.db")
    con.execute("CREATE TABLE project_meta (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT)")
    con.commit(); con.close()
    return root


def run(cwd: Path, home: Path) -> dict | None:
    env = {**os.environ, "HOME": str(home), "APEX_VAULT_DIR": str(home / "vault")}
    (home / "vault").mkdir(exist_ok=True)
    out = subprocess.run([sys.executable, str(HOOK)], input=json.dumps({"cwd": str(cwd)}),
                         capture_output=True, text=True, env=env, timeout=20)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)["hookSpecificOutput"]["additionalContext"] if out.stdout.strip() else None


def nota(home: Path) -> Path:
    return home / "vault" / "projects" / "mi-proyecto" / "pendientes.md"


def test_sin_nota_crea_la_plantilla_y_no_inyecta(proyecto, tmp_path):
    assert run(proyecto, tmp_path) is None
    assert "- [ ] !auto" in nota(tmp_path).read_text()
    assert run(proyecto, tmp_path) is None  # los ejemplos de la plantilla no cuentan


def test_inyecta_abiertas_con_detalle_y_protocolo(proyecto, tmp_path):
    run(proyecto, tmp_path)
    nota(tmp_path).write_text(
        "# Pendientes\n\n- [ ] Añadir exportación a CSV\n  - solo la tabla de errores\n"
        "- [x] Ya hecha\n- [ ] !auto Subir la versión a 1.2\n", encoding="utf-8")

    ctx = run(proyecto, tmp_path)

    assert "1. Añadir exportación a CSV [NUEVA o MODIFICADA" in ctx
    assert "solo la tabla de errores" in ctx
    assert "Subir la versión a 1.2 [!auto · NUEVA" in ctx
    assert "Ya hecha" not in ctx
    assert "Dudas: ninguna" in ctx and "ESPERA su confirmación" in ctx


def test_segunda_sesion_no_es_nueva_y_una_edicion_si(proyecto, tmp_path):
    run(proyecto, tmp_path)
    nota(tmp_path).write_text("- [ ] Tarea A\n- [ ] Tarea B\n", encoding="utf-8")
    run(proyecto, tmp_path)

    ctx = run(proyecto, tmp_path)
    assert "1. Tarea A\n" in ctx + "\n" and "NUEVA" not in ctx  # siguen abiertas, ya vistas

    nota(tmp_path).write_text("- [ ] Tarea A\n- [ ] Tarea B con un cambio\n", encoding="utf-8")
    ctx = run(proyecto, tmp_path)
    assert "Tarea B con un cambio [NUEVA" in ctx
    assert "1. Tarea A\n" in ctx


def test_fuera_de_un_proyecto_apex_no_hace_nada(tmp_path):
    suelta = tmp_path / "RoadToDevOps" / "suelta"
    suelta.mkdir(parents=True)
    (tmp_path / ".apex").mkdir()  # el ~/.apex global no cuenta como proyecto
    (tmp_path / ".apex" / "context.db").touch()
    assert run(suelta, tmp_path) is None
    assert not (tmp_path / "vault" / "projects").exists()
