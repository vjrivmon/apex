"""El gate de fase distingue "sin verdict" de "no pude leerlo".

Antes, `_get_latest_verdict` devolvía None ante cualquier error: tabla
ausente, BD bloqueada, fila corrupta. Y `main()` trata None como "adelante".
Resultado: un fallo de lectura dejaba pasar la transición en silencio, justo
en el punto cuyo trabajo es frenarla.

Ahora:
- sin verdict / tabla ausente  → None, deja pasar (correcto: nada que evaluar)
- BD ilegible / fila corrupta  → VerdictIlegible, avisa por stderr y deja
  pasar (bloquear por una BD momentáneamente locked atascaría la sesión sin
  causa real; lo inaceptable era callarlo)
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_HOOK = _REPO / ".claude" / "hooks" / "phase-gate.py"


@pytest.fixture(scope="module")
def gate():
    """El hook no es importable por nombre (guion); se carga por ruta."""
    spec = importlib.util.spec_from_file_location("phase_gate_hook", _HOOK)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["phase_gate_hook"] = mod
    spec.loader.exec_module(mod)
    return mod


def _crear_db(ruta: Path, con_tabla: bool = True) -> Path:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(ruta))
    if con_tabla:
        conn.execute(
            "CREATE TABLE grader_verdicts ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, phase INTEGER NOT NULL, "
            "quality INTEGER NOT NULL, issues TEXT DEFAULT '[]', "
            "should_block INTEGER DEFAULT 0, reasoning TEXT NOT NULL, "
            "created_at TEXT DEFAULT (datetime('now')))")
    conn.commit()
    conn.close()
    return ruta


# ── lo que NO debe considerarse error ────────────────────────────────────

def test_sin_verdict_devuelve_none(gate, tmp_path):
    """Tabla vacía: no hay nada que evaluar, la transición sigue."""
    db = _crear_db(tmp_path / ".apex" / "context.db")
    assert gate._get_latest_verdict(db, 5) is None


def test_tabla_ausente_devuelve_none(gate, tmp_path):
    """Proyecto anterior al Sprint 8: la tabla no existe y es legítimo."""
    db = _crear_db(tmp_path / ".apex" / "context.db", con_tabla=False)
    assert gate._get_latest_verdict(db, 5) is None


# ── lo que SÍ debe gritar ────────────────────────────────────────────────

def test_bd_corrupta_lanza_verdict_ilegible(gate, tmp_path):
    """Un fichero que no es SQLite no puede tratarse como 'sin verdict'."""
    db = tmp_path / ".apex" / "context.db"
    db.parent.mkdir(parents=True)
    db.write_bytes(b"esto no es una base de datos sqlite" * 50)

    with pytest.raises(gate.VerdictIlegible):
        gate._get_latest_verdict(db, 5)


def test_issues_corrupto_lanza_verdict_ilegible(gate, tmp_path):
    """JSON inválido en `issues`: se reporta, no se degrada a None."""
    db = _crear_db(tmp_path / ".apex" / "context.db")
    conn = sqlite3.connect(str(db))
    conn.execute(
        "INSERT INTO grader_verdicts (phase, quality, issues, should_block, "
        "reasoning) VALUES (5, 1, '{no es json', 1, 'roto')")
    conn.commit()
    conn.close()

    with pytest.raises(gate.VerdictIlegible):
        gate._get_latest_verdict(db, 5)


def test_verdict_valido_se_lee_entero(gate, tmp_path):
    """El camino feliz sigue intacto tras separar los errores."""
    db = _crear_db(tmp_path / ".apex" / "context.db")
    conn = sqlite3.connect(str(db))
    conn.execute(
        "INSERT INTO grader_verdicts (phase, quality, issues, should_block, "
        "reasoning) VALUES (5, 1, '[\"no_git_init\"]', 1, 'Sin git')")
    conn.commit()
    conn.close()

    v = gate._get_latest_verdict(db, 5)
    assert v["should_block"] is True
    assert v["issues"] == ["no_git_init"]
    assert v["reasoning"] == "Sin git"


# ── desempate por id (bug del mismo segundo) ─────────────────────────────

def test_desempate_por_id_con_timestamp_identico(gate, tmp_path):
    """created_at tiene precisión de segundo: dos verdicts seguidos empatan.

    Sin `id DESC`, reevaluar tras arreglar el problema devolvía el verdict
    bloqueante anterior y la fase no se desbloqueaba nunca.
    """
    db = _crear_db(tmp_path / ".apex" / "context.db")
    conn = sqlite3.connect(str(db))
    conn.execute(
        "INSERT INTO grader_verdicts (phase, quality, issues, should_block, "
        "reasoning, created_at) "
        "VALUES (5, 1, '[]', 1, 'bloqueante', '2026-09-21 18:00:00')")
    conn.execute(
        "INSERT INTO grader_verdicts (phase, quality, issues, should_block, "
        "reasoning, created_at) "
        "VALUES (5, 3, '[]', 0, 'resuelto', '2026-09-21 18:00:00')")
    conn.commit()
    conn.close()

    v = gate._get_latest_verdict(db, 5)
    assert v["reasoning"] == "resuelto", "devolvió el verdict viejo"
    assert v["should_block"] is False


# ── el hook completo, por subproceso ─────────────────────────────────────

def _ejecutar_hook(payload: dict, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_HOOK)],
        input=json.dumps(payload), text=True, capture_output=True,
        cwd=str(cwd), timeout=30,
        env={"PATH": "/usr/bin:/bin", "CLAUDE_PROJECT_DIR": str(cwd),
             "PYTHONPATH": str(_REPO)},
    )


def test_hook_avisa_por_stderr_si_no_puede_leer(tmp_path):
    """El caso que antes pasaba mudo: aviso visible y exit 0."""
    db = tmp_path / ".apex" / "context.db"
    db.parent.mkdir(parents=True)
    db.write_bytes(b"corrupta" * 100)

    r = _ejecutar_hook(
        {"tool_name": "mcp__apex__apex_set_phase",
         "tool_input": {"phase_number": 5, "status": "completed"}},
        tmp_path)

    assert r.returncode == 0, "un fallo de lectura no debe bloquear"
    assert "no se pudo comprobar el grader" in r.stderr.lower(), (
        f"el hook no avisó. stderr: {r.stderr!r}")


def test_hook_bloquea_con_verdict_bloqueante(tmp_path):
    """El bloqueo real sigue funcionando: exit 2 y motivo en stderr."""
    db = _crear_db(tmp_path / ".apex" / "context.db")
    conn = sqlite3.connect(str(db))
    conn.execute(
        "INSERT INTO grader_verdicts (phase, quality, issues, should_block, "
        "reasoning) VALUES (5, 1, '[\"no_git_init\"]', 1, 'Falta git')")
    conn.commit()
    conn.close()

    r = _ejecutar_hook(
        {"tool_name": "mcp__apex__apex_set_phase",
         "tool_input": {"phase_number": 5, "status": "completed"}},
        tmp_path)

    assert r.returncode == 2, f"debía bloquear. stderr: {r.stderr!r}"
    assert "BLOQUEA" in r.stderr
    assert "no_git_init" in r.stderr


def test_hook_deja_pasar_con_force(tmp_path):
    """force=True sigue siendo la vía de override."""
    db = _crear_db(tmp_path / ".apex" / "context.db")
    conn = sqlite3.connect(str(db))
    conn.execute(
        "INSERT INTO grader_verdicts (phase, quality, issues, should_block, "
        "reasoning) VALUES (5, 1, '[]', 1, 'Falta git')")
    conn.commit()
    conn.close()

    r = _ejecutar_hook(
        {"tool_name": "mcp__apex__apex_set_phase",
         "tool_input": {"phase_number": 5, "status": "completed",
                        "force": True, "force_reason": "deuda aceptada"}},
        tmp_path)

    assert r.returncode == 0
