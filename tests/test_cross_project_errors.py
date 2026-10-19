"""Errores cross-project: la recurrencia se calcula al leer, no se copia.

Contexto: `hub.db.errors.recurrence_count` es la recurrencia LOCAL (sube sólo
si el mismo error se repite en la misma `context.db`). El escáner de apex-hub
la copia tal cual, así que en la práctica TODAS las filas vale 1. Ordenar por
esa columna no ordena nada y el `LIMIT 5` del hook devolvía siempre los
mismos errores.

Estos tests fijan el comportamiento correcto: la recurrencia que ordena es el
número de PROYECTOS DISTINTOS con la misma firma de error.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from lib.cross_project_errors import (  # noqa: E402
    cluster_errors,
    load_errors,
    max_errors,
    normalize_signature,
    rank_errors,
    top_errors,
)


def _crear_hub(tmp_path: Path, filas: list[tuple]) -> Path:
    """Crea un hub.db mínimo con la tabla `errors` del esquema real."""
    hub = tmp_path / "hub.db"
    conn = sqlite3.connect(hub)
    conn.execute(
        "CREATE TABLE errors (id INTEGER PRIMARY KEY, project_id TEXT, "
        "original_id INTEGER, source TEXT, description TEXT, lesson TEXT, "
        "severity TEXT, phase INTEGER, recurrence_count INTEGER DEFAULT 1, "
        "created_at TEXT)"
    )
    conn.executemany(
        "INSERT INTO errors (project_id, source, description, lesson, severity, "
        "phase, recurrence_count, created_at) VALUES (?,?,?,?,?,?,?,?)",
        filas,
    )
    conn.commit()
    conn.close()
    return hub


class TestNormalizeSignature:
    def test_ignora_mayusculas_y_puntuacion(self):
        assert normalize_signature("No Apliqué el parche.") == normalize_signature(
            "no apliqué el parche"
        )

    def test_colapsa_espacios(self):
        assert normalize_signature("a   b\tc") == "a b c"

    def test_vacio_es_vacio(self):
        assert normalize_signature("") == ""
        assert normalize_signature(None) == ""

    def test_trunca(self):
        largo = "palabra " * 60
        assert len(normalize_signature(largo)) <= 120

    def test_descripciones_equivalentes_misma_firma(self):
        a = "Dejé el frontend con datos mock hardcodeados (MOCK_STEP)"
        b = "dejé el frontend con datos mock hardcodeados mock_step"
        assert normalize_signature(a) == normalize_signature(b)


class TestClusterErrors:
    def test_agrupa_por_firma_y_cuenta_proyectos_distintos(self):
        rows = [
            {"project_id": "p1", "description": "Error X", "severity": "high",
             "lesson": "L1", "recurrence_count": 1, "created_at": "2026-01-01"},
            {"project_id": "p2", "description": "Error X!", "severity": "critical",
             "lesson": "L2", "recurrence_count": 1, "created_at": "2026-01-02"},
            {"project_id": "p2", "description": "Error X", "severity": "high",
             "lesson": "L3", "recurrence_count": 3, "created_at": "2026-01-03"},
        ]
        clusters = cluster_errors(rows)
        assert len(clusters) == 1
        c = clusters[0]
        assert c["project_count"] == 2          # p1 y p2, no 3 filas
        assert sorted(c["projects"]) == ["p1", "p2"]
        assert c["recurrence_count"] == 3        # la local máxima
        assert c["severity"] == "critical"       # la más alta del cluster

    def test_errores_distintos_no_se_agrupan(self):
        rows = [
            {"project_id": "p1", "description": "Error A", "severity": "low"},
            {"project_id": "p2", "description": "Error B", "severity": "low"},
        ]
        assert len(cluster_errors(rows)) == 2

    def test_ignora_filas_sin_descripcion(self):
        rows = [{"project_id": "p1", "description": "", "severity": "low"}]
        assert cluster_errors(rows) == []


class TestRankErrors:
    def test_orden_por_proyectos_distintos_primero(self):
        clusters = [
            {"signature": "a", "project_count": 1, "severity": "critical",
             "last_seen": "2026-05-01", "description": "", "projects": []},
            {"signature": "b", "project_count": 3, "severity": "low",
             "last_seen": "2026-01-01", "description": "", "projects": []},
        ]
        ranked = rank_errors(clusters)
        assert ranked[0]["signature"] == "b"

    def test_a_igual_proyectos_manda_severidad(self):
        clusters = [
            {"signature": "a", "project_count": 2, "severity": "low",
             "last_seen": "2026-05-01", "description": "", "projects": []},
            {"signature": "b", "project_count": 2, "severity": "critical",
             "last_seen": "2026-01-01", "description": "", "projects": []},
        ]
        assert rank_errors(clusters)[0]["signature"] == "b"

    def test_a_igual_proyectos_y_severidad_manda_mas_reciente(self):
        clusters = [
            {"signature": "a", "project_count": 2, "severity": "high",
             "last_seen": "2026-01-01", "description": "", "projects": []},
            {"signature": "b", "project_count": 2, "severity": "high",
             "last_seen": "2026-06-01", "description": "", "projects": []},
        ]
        assert rank_errors(clusters)[0]["signature"] == "b"


class TestTopErrors:
    def test_excluye_el_proyecto_actual(self, tmp_path):
        hub = _crear_hub(tmp_path, [
            ("apex", "claude", "Error del proyecto actual", "L", "critical", None, 1, "2026-01-01"),
            ("otro", "claude", "Error de otro proyecto", "L", "high", None, 1, "2026-01-01"),
        ])
        top = top_errors(hub, exclude_project="apex")
        assert len(top) == 1
        assert top[0]["projects"] == ["otro"]

    def test_el_tope_lo_manda_la_recurrencia_real(self, tmp_path):
        # El error "recurrente" sólo aparece en 1 proyecto pero es critical.
        # El otro aparece en 3 proyectos con severidad media. Gana el de 3.
        filas = [
            ("p1", "claude", "Unico y critico", "L", "critical", None, 1, "2026-01-01"),
            ("p1", "claude", "Repetido", "L", "medium", None, 1, "2026-01-01"),
            ("p2", "claude", "Repetido", "L", "medium", None, 1, "2026-01-02"),
            ("p3", "claude", "Repetido", "L", "medium", None, 1, "2026-01-03"),
        ]
        hub = _crear_hub(tmp_path, filas)
        top = top_errors(hub, limit=1)
        assert top[0]["project_count"] == 3
        assert "Repetido" in top[0]["description"]

    def test_hub_inexistente_devuelve_vacio(self, tmp_path):
        assert top_errors(tmp_path / "no-existe.db") == []

    def test_tope_por_parametro(self, tmp_path):
        filas = [
            (f"p{i}", "claude", f"Error {i}", "L", "medium", None, 1, "2026-01-01")
            for i in range(10)
        ]
        hub = _crear_hub(tmp_path, filas)
        assert len(top_errors(hub, limit=3)) == 3
        assert len(top_errors(hub, limit=10)) == 10

    def test_carga_directa(self, tmp_path):
        hub = _crear_hub(tmp_path, [
            ("p1", "claude", "Error X", "L", "high", None, 1, "2026-01-01"),
        ])
        assert len(load_errors(hub)) == 1


class TestMaxErrors:
    def test_por_defecto(self, monkeypatch):
        monkeypatch.delenv("APEX_CROSS_PROJECT_ERRORS", raising=False)
        assert max_errors() == 5

    def test_configurable_por_env(self, monkeypatch):
        monkeypatch.setenv("APEX_CROSS_PROJECT_ERRORS", "9")
        assert max_errors() == 9

    def test_valor_invalido_usa_el_defecto(self, monkeypatch):
        monkeypatch.setenv("APEX_CROSS_PROJECT_ERRORS", "basura")
        assert max_errors() == 5
        monkeypatch.setenv("APEX_CROSS_PROJECT_ERRORS", "0")
        assert max_errors() == 5
        monkeypatch.setenv("APEX_CROSS_PROJECT_ERRORS", "-3")
        assert max_errors() == 5


class TestHookSessionStart:
    """El hook debe usar la recurrencia real, no `recurrence_count`."""

    @staticmethod
    def _cargar_hook(ruta: str):
        import importlib.util

        path = _REPO / ruta / "session-start.py"
        spec = importlib.util.spec_from_file_location(f"hook_{ruta.replace('/', '_')}", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    @pytest.mark.parametrize("ruta", [".claude/hooks", ".codex/hooks"])
    def test_el_hook_ordena_por_recurrencia_real(self, ruta, tmp_path, monkeypatch):
        """Con dos errores, gana el que aparece en más proyectos.

        El error "crítico y único" sólo está en un proyecto; el repetido está
        en tres. Con el orden viejo (recurrence_count, siempre 1) el resultado
        dependía del orden de inserción. Con el orden nuevo depende de la
        recurrencia cross-project, que es lo que el hook anuncia.
        """
        hub = _crear_hub(tmp_path, [
            ("p1", "claude", "Unico y critico", "L", "critical", None, 1, "2026-01-01"),
            ("p1", "claude", "Repetido", "L", "medium", None, 1, "2026-01-01"),
            ("p2", "claude", "Repetido", "L", "medium", None, 1, "2026-01-02"),
            ("p3", "claude", "Repetido", "L", "medium", None, 1, "2026-01-03"),
        ])
        hook = self._cargar_hook(ruta)
        monkeypatch.setattr(hook, "HUB_DB", hub)
        monkeypatch.setattr(hook, "_current_project_id", lambda: "otro-proyecto")

        top = hook._read_top_errors()
        assert top, "el hook debe devolver errores"
        assert top[0]["project_count"] == 3
        assert "Repetido" in top[0]["description"]

    @pytest.mark.parametrize("ruta", [".claude/hooks", ".codex/hooks"])
    def test_el_hook_no_deja_mensajes_si_el_hub_no_existe(self, ruta, tmp_path, monkeypatch):
        hook = self._cargar_hook(ruta)
        monkeypatch.setattr(hook, "HUB_DB", tmp_path / "no-existe.db")
        assert hook._read_top_errors() == []
        assert hook._format_context([]) == ""

    @pytest.mark.parametrize("ruta", [".claude/hooks", ".codex/hooks"])
    def test_los_dos_hooks_son_identicos(self, ruta):
        """Los dos juegos de hooks no deben divergir sin motivo."""
        claude = (_REPO / ".claude" / "hooks" / "session-start.py").read_text(
            encoding="utf-8"
        )
        codex = (_REPO / ruta / "session-start.py").read_text(encoding="utf-8")
        assert claude == codex
