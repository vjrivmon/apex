"""agent_knowledge: nota de lo que saben los agentes y aviso de secciones caducadas."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "agent_knowledge.py"

PROFILE = """# PROFILE.md

## Quién es

_Revisado: 2026-07-01_

Estudiante.

## Proyectos activos

_Revisado: 2026-08-01_

- TFG (prioridad alta)

## Stack

Python.
"""


@pytest.fixture
def entorno(tmp_path):
    prof = tmp_path / "PROFILE.md"
    prof.write_text(PROFILE, encoding="utf-8")
    vault = tmp_path / "Visi-Personal"
    (vault / "perfil").mkdir(parents=True)
    mem = tmp_path / "projects"
    for proyecto, nombre, tipo in (("-home-vicente-RoadToDevOps-apex", "Perfil de Vicente", "user"),
                                   ("-home-vicente-RoadToDevOps-otro", "Perfil de Vicente", "user"),
                                   ("-home-vicente-RoadToDevOps-apex", "Sin emojis", "feedback"),
                                   ("-home-vicente-RoadToDevOps-apex", "Rutas", "reference")):
        d = mem / proyecto / "memory"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{nombre.replace(' ', '_')}.md").write_text(
            f"---\nname: {nombre}\ndescription: desc de {nombre}\nmetadata:\n  type: {tipo}\n---\n\ncuerpo\n",
            encoding="utf-8")
    (mem / "-home-vicente-RoadToDevOps-apex" / "memory" / "MEMORY.md").write_text("- índice\n")
    env = {**os.environ, "APEX_PROFILE_PATH": str(prof), "APEX_MEMORY_ROOT": str(mem),
           "APEX_PERSONAL_VAULT": str(vault), "APEX_TODAY": "2026-09-23"}
    return env, vault / "perfil" / "Lo que saben los agentes.md"


def run(env, *args):
    out = subprocess.run([sys.executable, str(SCRIPT), *args], input="{}", capture_output=True,
                         text=True, env=env, timeout=20)
    assert out.returncode == 0, out.stderr
    return out.stdout


def test_nota_con_caducidad_por_seccion(entorno):
    env, nota = entorno
    run(env)
    texto = nota.read_text()
    assert "| Quién es | 2026-07-01 | vigente (hace 84 días) |" in texto  # 90 días: aún vale
    assert "| Proyectos activos | 2026-08-01 | **POR REVISAR** (hace 53 días, caduca a los 30) |" in texto
    assert "| Stack | — | **POR REVISAR** (sin fecha) |" in texto


def test_memorias_user_feedback_y_duplicadas(entorno):
    env, nota = entorno
    run(env)
    texto = nota.read_text()
    assert "Memorias sueltas (3)" in texto  # la de tipo reference y MEMORY.md no cuentan
    assert "- **Perfil de Vicente** · en 2: RoadToDevOps/apex" in texto
    assert "### Cómo trabajar contigo (1)" in texto and "Sin emojis" in texto
    assert "Rutas" not in texto


def test_hook_avisa_solo_de_lo_caducado(entorno):
    env, _ = entorno
    ctx = json.loads(run(env, "--hook"))["hookSpecificOutput"]["additionalContext"]
    assert "Proyectos activos (revisada 2026-08-01)" in ctx and "Stack (revisada nunca)" in ctx
    assert "Quién es" not in ctx and "pregunta a Vicente" in ctx

    env = {**env, "APEX_TODAY": "2026-08-10"}  # todo vigente salvo Stack sin fecha
    Path(env["APEX_PROFILE_PATH"]).write_text(PROFILE.replace("## Stack\n", "## Stack\n\n_Revisado: 2026-08-01_\n"))
    assert run(env, "--hook") == ""


def test_no_pisa_una_nota_escrita_a_mano(entorno):
    env, nota = entorno
    nota.write_text("Mis apuntes\n", encoding="utf-8")
    run(env)
    assert nota.read_text() == "Mis apuntes\n"
