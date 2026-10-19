"""Tests del generador de estado del CLAUDE.md.

Lo que se verifica es que los números salgan del repo real y que el script
respete la narrativa escrita a mano: si sobreescribiera texto fuera de los
marcadores, destruiría lo único del documento que no caduca.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "refresh_state.py"
HOOK = REPO / ".claude" / "hooks" / "refresh-state.py"


def _load():
    spec = importlib.util.spec_from_file_location("refresh_state", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rs = _load()


# ── Conteos ──

def test_cuenta_tools_reales():
    """Debe coincidir con las Tool(name="apex_...") del servidor."""
    esperado = len(set(
        __import__("re").findall(
            r'name="(apex_[a-z_]+)"',
            (REPO / "mcp/apex_server.py").read_text(encoding="utf-8"),
        )
    ))
    assert rs.count_tools() == esperado
    assert rs.count_tools() > 50, "el servidor debería tener decenas de tools"


def test_cuenta_skills_reales():
    assert rs.count_skills() == len(list((REPO / "skills").glob("*/SKILL.md")))


def test_cuenta_tablas_reales():
    assert rs.count_tables() == len(set(
        __import__("re").findall(
            r"CREATE TABLE IF NOT EXISTS (\w+)",
            (REPO / "lib/context_db.py").read_text(encoding="utf-8"),
        )
    ))


def test_cuenta_hooks_en_disco_y_registrados():
    disco, registrados = rs.count_hooks()
    assert disco == len(list((REPO / ".claude/hooks").glob("*.py")))
    assert registrados > 0, "settings.json debería registrar hooks"
    assert registrados <= disco + 5  # los de ~/.claude también cuentan


def test_detecta_biblioteca_como_presente():
    """Los sprints se marcan por presencia de artefactos, no por texto."""
    filas = dict((n, e) for n, e, _ in rs.sprint_rows())
    assert filas["Biblioteca de libros"] == "presente"
    assert filas["S17 VirtualFS"] == "presente"


def test_detecta_sprint_ausente():
    """S18 arrancó el 2026-10-19 (lib/curator.py): ahora el sprint ausente
    es S19 (Advent), que sigue sin artefactos. El test sigue detectando
    un sprint ausente; solo cambia cuál."""
    filas = dict((n, e) for n, e, _ in rs.sprint_rows())
    assert filas["S18 Granite curator"] == "presente"
    assert filas["S19 Advent integration"] == "ausente"


def test_modulos_huerfanos_no_incluye_los_cableados():
    """book_corpus se importa desde el servidor: no puede salir como huérfano."""
    huerfanos = rs.orphan_modules()
    assert "book_corpus" not in huerfanos
    assert "book_chunker" not in huerfanos  # lo importa book_corpus
    assert "embeddings" not in huerfanos    # lo importa book_corpus


def test_vfs_grep_sale_como_huerfano():
    """Deuda real conocida: escrito, con tests, y sin cablear."""
    assert "vfs_grep" in rs.orphan_modules()


# ── Bloque generado ──

def test_bloque_lleva_marcadores_y_datos():
    bloque = rs.build_block()
    assert bloque.startswith(rs.BEGIN)
    assert bloque.rstrip().endswith(rs.END)
    assert "Tools MCP" in bloque and "Tests" in bloque
    assert "NO editar a mano" in bloque


def test_bloque_sin_emojis():
    bloque = rs.build_block()
    assert not any(ord(c) > 0x2500 for c in bloque), "el proyecto prohíbe emojis"


# ── Escritura ──

def test_no_toca_la_narrativa(tmp_path, monkeypatch):
    """El texto fuera de los marcadores debe sobrevivir intacto."""
    fake = tmp_path / "CLAUDE.md"
    fake.write_text(
        "# Encabezado propio\n\nNarrativa que NO debe tocarse.\n\n"
        f"{rs.BEGIN}\nviejo y falso\n{rs.END}\n\n"
        "## Decisiones\n\nMás narrativa al final.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(rs, "REPO", REPO)
    monkeypatch.setattr(rs, "__file__", str(SCRIPT))

    texto = fake.read_text(encoding="utf-8")
    import re
    nuevo = re.sub(
        re.escape(rs.BEGIN) + r".*?" + re.escape(rs.END),
        lambda _: rs.build_block(),
        texto,
        flags=re.DOTALL,
    )
    fake.write_text(nuevo, encoding="utf-8")

    final = fake.read_text(encoding="utf-8")
    assert "# Encabezado propio" in final
    assert "Narrativa que NO debe tocarse." in final
    assert "Más narrativa al final." in final
    assert "viejo y falso" not in final
    assert "Tools MCP" in final


def test_claude_md_refleja_los_conteos_actuales():
    """Si esto falla, el CLAUDE.md se quedó desfasado.

    Compara los números escritos contra los reales SIN invocar `--check`, que
    ejecutaría la suite entera dentro de este test (pytest anidado).
    """
    texto = (REPO / "CLAUDE.md").read_text(encoding="utf-8")
    bloque = texto.split(rs.BEGIN)[1].split(rs.END)[0]

    assert f"| Tools MCP | {rs.count_tools()} |" in bloque, (
        "recuento de tools desfasado; corre scripts/refresh_state.py"
    )
    assert f"| Skills (`skills/`) | {rs.count_skills()} |" in bloque
    assert f"| Tablas en `context.db` | {rs.count_tables()} |" in bloque


def test_count_test_functions_no_ejecuta_pytest():
    """El recuento estático debe ser inmediato: lo usan tests y hooks."""
    import time

    t0 = time.monotonic()
    n = rs.count_test_functions()
    assert time.monotonic() - t0 < 5.0, "no debe ejecutar la suite"
    assert n > 600, f"esperaba cientos de tests, conté {n}"


def test_claude_md_tiene_los_marcadores():
    texto = (REPO / "CLAUDE.md").read_text(encoding="utf-8")
    assert rs.BEGIN in texto and rs.END in texto


# ── Hook ──

@pytest.mark.parametrize("payload", [
    '{"hook_event_name":"Stop","cwd":"/tmp"}',
    '{"hook_event_name":"PostToolUse","cwd":"/tmp"}',
    "esto no es json",
    "",
])
def test_hook_nunca_bloquea(payload):
    """Regenerar documentación no puede tumbar el flujo de trabajo."""
    proc = subprocess.run(
        [sys.executable, str(HOOK)],
        input=payload, capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0


def test_hook_registrado_en_settings():
    settings = json.loads(
        (REPO / ".claude/settings.json").read_text(encoding="utf-8")
    )
    eventos = set()
    for evento, entradas in settings["hooks"].items():
        for entrada in entradas:
            for h in entrada.get("hooks", []):
                if "refresh-state.py" in h.get("command", ""):
                    eventos.add(evento)
    assert eventos == {"PostToolUse", "Stop"}


def test_hook_de_fase_usa_matcher_especifico():
    """No debe correr en CADA tool: solo al cambiar de fase."""
    settings = json.loads(
        (REPO / ".claude/settings.json").read_text(encoding="utf-8")
    )
    for entrada in settings["hooks"]["PostToolUse"]:
        if any("refresh-state.py" in h.get("command", "")
               for h in entrada.get("hooks", [])):
            assert entrada.get("matcher") == "mcp__apex__apex_set_phase"
