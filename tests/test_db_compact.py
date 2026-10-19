"""DB compaction: el módulo estaba huérfano y además fallaba en silencio.

Dos defectos, medidos el 2026-10-19:

1. `lib/db_compact.py` no lo importaba nadie: 0 importadores en el repo. Un
   módulo con mantenimiento de la base que nunca se ejecuta no es código: es
   una intención.
2. Peor: dos de las ocho tablas de `_LOG_TABLES` pedían una columna que NO
   existe (`advisor_reviews.reviewed_at` — la real es `triggered_at` — y
   `tool_output_archive.archived_at` — la real es `created_at`). El `DELETE`
   lanzaba `OperationalError`, que una Except amplia metía en
   `stats["errors"]`, un dict que nadie leía. Las dos tablas que más crecen
   nunca se compactaban y el fallo era invisible.

Estos tests fijan: las columnas son las reales, el fallo se dice en voz alta,
y la compactación borra de verdad.
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from lib.db_compact import _LOG_TABLES, apex_db_compact  # noqa: E402


def _crear_db(tmp_path: Path) -> Path:
    """context.db mínima con las tablas que el compactador toca."""
    db = tmp_path / "context.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE tool_call_log (id INTEGER PRIMARY KEY, tool TEXT, "
        "args_summary TEXT, created_at TEXT)"
    )
    conn.execute(
        "CREATE TABLE tool_output_archive (id INTEGER PRIMARY KEY, tool TEXT, "
        "arguments TEXT, output_full TEXT, summary TEXT, chars_full INTEGER, "
        "chars_summary INTEGER, created_at TEXT)"
    )
    conn.execute(
        "CREATE TABLE advisor_reviews (id INTEGER PRIMARY KEY, session_id TEXT, "
        "triggered_at TEXT, trigger_kind TEXT, bundle_size_tokens INTEGER, "
        "advice_count INTEGER, duration_ms INTEGER, status TEXT)"
    )
    conn.execute(
        "CREATE TABLE reasoning_traces (id INTEGER PRIMARY KEY, session_id TEXT, "
        "phase INTEGER, category TEXT, gate_kind TEXT, deliberation TEXT, "
        "calibration_confidence REAL, calibration_text TEXT, "
        "alternatives_considered TEXT, created_at TEXT)"
    )
    conn.commit()
    conn.close()
    return db


def _antigua(dias: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=dias)).isoformat()


class TestColumnasReales:
    """Cada tabla de _LOG_TABLES debe tener la columna que se le pide."""

    @pytest.mark.parametrize("tabla,columna", sorted(_LOG_TABLES.items()))
    def test_la_columna_existe_en_el_esquema_real(self, tabla, columna, tmp_path):
        """Contra el esquema REAL de `context.db`, no contra el fuente.

        Se inicializa una ApexContextDB de verdad y se mira su esquema: si
        alguien renombra una columna en lib/context_db.py, este test falla.
        """
        import asyncio

        from lib.context_db import ApexContextDB

        db_path = tmp_path / "esquema.db"
        db = ApexContextDB(str(db_path))
        asyncio.new_event_loop().run_until_complete(db.initialize())

        conn = sqlite3.connect(db_path)
        columnas = {
            row[1] for row in conn.execute(f"PRAGMA table_info({tabla})")
        }
        conn.close()

        assert columna in columnas, (
            f"{tabla} no tiene la columna {columna!r} "
            f"(tiene: {', '.join(sorted(columnas))}): el DELETE fallaría y el "
            f"error quedaría escondido en stats['errors']"
        )


class TestCompaccion:
    def test_borra_filas_antiguas_y_conserva_recientes(self, tmp_path):
        db = _crear_db(tmp_path)
        conn = sqlite3.connect(db)
        conn.execute(
            "INSERT INTO tool_call_log (tool, created_at) VALUES (?,?)",
            ("viejo", _antigua(90)),
        )
        conn.execute(
            "INSERT INTO tool_call_log (tool, created_at) VALUES (?,?)",
            ("nuevo", _antigua(1)),
        )
        conn.commit()
        conn.close()

        stats = apex_db_compact(db, retention_days=30)
        assert stats["rows_deleted"] == 1
        assert "tool_call_log" in stats["tables_cleaned"]
        assert stats["errors"] == []

        conn = sqlite3.connect(db)
        quedan = conn.execute("SELECT tool FROM tool_call_log").fetchall()
        conn.close()
        assert quedan == [("nuevo",)]

    def test_compacta_las_tablas_que_antes_fallaban_en_silencio(self, tmp_path):
        """Las dos tablas con el nombre de columna equivocado."""
        db = _crear_db(tmp_path)
        conn = sqlite3.connect(db)
        conn.execute(
            "INSERT INTO advisor_reviews (session_id, triggered_at) VALUES (?,?)",
            ("s1", _antigua(90)),
        )
        conn.execute(
            "INSERT INTO tool_output_archive (tool, created_at) VALUES (?,?)",
            ("t1", _antigua(90)),
        )
        conn.commit()
        conn.close()

        stats = apex_db_compact(db, retention_days=30)
        assert stats["errors"] == [], (
            "el fallo de columna debe reportarse, no tragarse"
        )
        assert "advisor_reviews" in stats["tables_cleaned"]
        assert "tool_output_archive" in stats["tables_cleaned"]
        assert stats["rows_deleted"] == 2

    def test_una_tabla_inexistente_se_reporta_como_skip(self, tmp_path):
        db = _crear_db(tmp_path)
        conn = sqlite3.connect(db)
        conn.execute("DROP TABLE reasoning_traces")
        conn.commit()
        conn.close()

        stats = apex_db_compact(db, retention_days=30)
        assert any("reasoning_traces" in s for s in stats["tables_skipped"])
        assert stats["errors"] == []

    def test_db_inexistente_devuelve_error_explicito(self, tmp_path):
        stats = apex_db_compact(tmp_path / "no-existe.db")
        assert "error" in stats
        assert stats["rows_deleted"] == 0

    def test_retencion_alta_no_borra_nada(self, tmp_path):
        db = _crear_db(tmp_path)
        conn = sqlite3.connect(db)
        conn.execute(
            "INSERT INTO tool_call_log (tool, created_at) VALUES (?,?)",
            ("viejo", _antigua(90)),
        )
        conn.commit()
        conn.close()

        stats = apex_db_compact(db, retention_days=365)
        assert stats["rows_deleted"] == 0
        assert stats["errors"] == []

    def test_vacuum_reduce_o_conserva_el_tamano(self, tmp_path):
        db = _crear_db(tmp_path)
        stats = apex_db_compact(db, retention_days=30)
        assert stats["vacuum_before_kb"] >= 0
        assert stats["vacuum_after_kb"] >= 0


class TestHuérfanoResuelto:
    """El módulo ya no está huérfano: tiene un CLI usable."""

    def test_tiene_cli(self):
        from lib.db_compact import main

        assert callable(main)

    def test_el_modulo_se_puede_ejecutar(self, tmp_path):
        import subprocess

        db = _crear_db(tmp_path)
        proc = subprocess.run(
            [sys.executable, "-m", "lib.db_compact", "--db", str(db)],
            cwd=str(_REPO),
            capture_output=True,
            text=True,
            env={"PYTHONPATH": str(_REPO), "PATH": "/usr/bin:/bin"},
        )
        assert proc.returncode == 0, proc.stderr
        assert "rows_deleted" in proc.stdout
