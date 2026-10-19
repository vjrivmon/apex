"""Tests de lib/init_claude_md.py — CLAUDE.md APEX-aware (Sprint 19, Gap D).

Todo en tmp_path: ni una escritura fuera del directorio de test.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

from context_db import ApexContextDB  # noqa: E402
from init_claude_md import (  # noqa: E402
    BLOCK_END,
    BLOCK_START,
    ensure_claude_md,
    merge_block,
    read_project_state,
)


# --- helpers ---------------------------------------------------------------

def _crear_db(tmp_path: Path, phase: int | None = None,
              decisions: list[tuple[str, str, str]] | None = None) -> None:
    """Crea un context.db con fase en curso y decisiones vigentes."""
    db = ApexContextDB(tmp_path / ".apex" / "context.db")

    async def _init() -> None:
        await db.initialize()
        if phase is not None:
            await db.set_phase(phase, "in_progress")
        for category, decision, reasoning in decisions or []:
            await db.add_decision(category, decision, reasoning)

    asyncio.run(_init())


# --- creación --------------------------------------------------------------

def test_crea_claude_md_cuando_no_existe(tmp_path: Path):
    path = ensure_claude_md(tmp_path)
    assert path == tmp_path / "CLAUDE.md"
    text = path.read_text(encoding="utf-8")
    assert BLOCK_START in text
    assert BLOCK_END in text
    # Las 4 secciones del blueprint
    assert "Antes de empezar" in text
    assert "Fase actual" in text
    assert "Decisiones vigentes" in text
    assert "Skills APEX recomendadas" in text


def test_sin_context_db_avisa_de_que_no_hay_datos(tmp_path: Path):
    path = ensure_claude_md(tmp_path)
    text = path.read_text(encoding="utf-8")
    assert "Sin datos" in text
    assert "apex_init_project" in text


# --- actualización del bloque ---------------------------------------------

def test_actualiza_bloque_en_claude_md_existente(tmp_path: Path):
    _crear_db(tmp_path, phase=7, decisions=[
        ("arquitectura", "usar SQLite", "no hay servidor gestionado"),
    ])
    path = tmp_path / "CLAUDE.md"
    path.write_text(
        "# CLAUDE.md\n\n"
        "Regla propia del proyecto: nunca tocar el legacy.\n\n"
        f"{BLOCK_START}\ncontenido viejo\n{BLOCK_END}\n",
        encoding="utf-8",
    )

    ensure_claude_md(tmp_path)
    text = path.read_text(encoding="utf-8")

    # Contenido propio intacto
    assert "nunca tocar el legacy" in text
    # Bloque viejo sustituido por el nuevo
    assert "contenido viejo" not in text
    assert "usar SQLite" in text


def test_no_pisa_contenido_previo_sin_bloque(tmp_path: Path):
    path = tmp_path / "CLAUDE.md"
    original = "# CLAUDE.md\n\nContenido manual que no se toca.\n"
    path.write_text(original, encoding="utf-8")

    ensure_claude_md(tmp_path)
    text = path.read_text(encoding="utf-8")

    assert "Contenido manual que no se toca." in text
    # Y el bloque se añade al final
    assert text.index("Contenido manual") < text.index(BLOCK_START)
    assert BLOCK_END in text


def test_es_idempotente(tmp_path: Path):
    path = ensure_claude_md(tmp_path)
    first = path.read_bytes()
    ensure_claude_md(tmp_path)
    second = path.read_bytes()
    assert first == second


def test_bloque_marcable_en_un_solo_sitio(tmp_path: Path):
    path = tmp_path / "CLAUDE.md"
    path.write_text(
        f"{BLOCK_START}\nviejo\n{BLOCK_END}\n",
        encoding="utf-8",
    )
    ensure_claude_md(tmp_path)
    text = path.read_text(encoding="utf-8")
    assert text.count(BLOCK_START) == 1
    assert text.count(BLOCK_END) == 1


def test_marcador_suelto_se_limpia(tmp_path: Path):
    """Un START sin END no deja el fichero con dos marcadores Start."""
    path = tmp_path / "CLAUDE.md"
    path.write_text(
        "# CLAUDE.md\n\ntexto\n\n" + BLOCK_START + "\nbasura\n",
        encoding="utf-8",
    )
    ensure_claude_md(tmp_path)
    text = path.read_text(encoding="utf-8")
    assert text.count(BLOCK_START) == 1
    assert text.count(BLOCK_END) == 1
    # El contenido que quedó tras el marcador suelto no se borra: APEX no
    # destruye texto del usuario, solo gestiona su propio bloque.
    assert "basura" in text


def test_merge_block_no_toca_el_resto():
    texto = "intro\n\ncola\n"
    bloque = f"{BLOCK_START}\nnuevo\n{BLOCK_END}"
    salida = merge_block(texto, bloque)
    assert salida.startswith("intro")
    assert "cola" in salida
    # El bloque se anade al final, sin reescribir lo anterior
    assert salida.index("cola") < salida.index(BLOCK_START)
    assert "nuevo" in salida


# --- lectura del estado ----------------------------------------------------

def test_lee_fase_y_decisiones_del_context_db(tmp_path: Path):
    _crear_db(tmp_path, phase=9, decisions=[
        ("arquitectura", "usar SQLite", "no hay servidor gestionado"),
        ("seguridad", "gitleaks en pre-commit", "gap F del sprint 19"),
    ])
    state = read_project_state(tmp_path)
    assert state.db_exists is True
    assert state.phase_number == 9
    assert state.phase_status == "in_progress"
    assert len(state.decisions) == 2
    # Las más recientes primero
    assert state.decisions[0]["decision"] == "gitleaks en pre-commit"


def test_fase_inexistente_no_rompe(tmp_path: Path):
    _crear_db(tmp_path)
    state = read_project_state(tmp_path)
    assert state.phase_number is None
    assert state.decisions == []


def test_claude_md_refleja_el_estado_de_la_db(tmp_path: Path):
    _crear_db(tmp_path, phase=3, decisions=[
        ("spec", "una decisión", "su razonamiento"),
    ])
    path = ensure_claude_md(tmp_path)
    text = path.read_text(encoding="utf-8")
    assert "Fase 3" in text
    assert "una decisión" in text


def test_db_corrupta_no_revienta(tmp_path: Path):
    apex = tmp_path / ".apex"
    apex.mkdir(parents=True)
    (apex / "context.db").write_text("esto no es una base de datos", encoding="utf-8")
    state = read_project_state(tmp_path)
    assert state.db_error is not None
    # Y el CLAUDE.md se genera igualmente
    path = ensure_claude_md(tmp_path)
    assert path.exists()
