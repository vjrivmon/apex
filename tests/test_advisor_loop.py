"""Sprint 15/16 — ciclo COMPLETO del advisor: review → advice → outcome.

La auditoría del 2026-10-19 encontró el bucle del advisor INERTE: 7269
reviews en 'pending', `advisor_advice` vacía, `advice_outcomes` vacía y
`advisor_health()` estructuralmente vacío. La causa raíz era que
`update_review_status()` no tenía ni un call site: nadie cerraba un
review, así que el circuit breaker (`register_review_outcome`) nunca
disparaba y `tool_count` no se reseteaba nunca (de ahí el flood de
reviews: uno por cada tool call).

Estos tests ejercitan el ciclo entero contra una BD temporal:
  review → advice → rating manual → tuning → health
y comprueban que la reparación de reviews huérfanos es idempotente.
"""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from context_db import ApexContextDB  # noqa: E402
import advisor  # noqa: E402
import advisor_health  # noqa: E402
import advisor_tuning  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK_TRIGGER = REPO_ROOT / ".claude" / "hooks" / "advisor-trigger.py"


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.fixture
def db_path(tmp_path):
    p = tmp_path / "ctx.db"
    db = ApexContextDB(str(p))
    run(db.initialize())
    return str(p)


def _row(db_path: str, sql: str, params=()) -> tuple:
    with sqlite3.connect(db_path) as c:
        return c.execute(sql, params).fetchone()


def _count(db_path: str, sql: str, params=()) -> int:
    row = _row(db_path, sql, params)
    return int(row[0]) if row else 0


def _meta_int(db_path: str, key: str) -> int:
    with sqlite3.connect(db_path) as c:
        return advisor._get_meta_int(c, key)


# ── 1. Cierre del review: estado terminal, conteo y duración ───────

class TestReviewClosing:
    def test_review_se_cierra_con_conteo_y_duracion(self, db_path):
        rid = advisor.record_review(db_path, "s1", "manual")
        for i in range(3):
            advisor.record_advice(
                db_path, rid, "phase_drift", "warn", f"card-{i}", "cuerpo",
            )
        cerrados = advisor.close_ready_reviews(db_path, "s1", settle_sec=0)
        assert len(cerrados) == 1
        row = _row(
            db_path,
            "SELECT status, advice_count, duration_ms FROM advisor_reviews "
            "WHERE id=?",
            (rid,),
        )
        assert row[0] == "completed"
        assert row[1] == 3
        assert row[2] >= 0

    def test_cada_card_refresca_el_conteo_del_review(self, db_path):
        rid = advisor.record_review(db_path, "s1", "manual")
        for expected in (1, 2, 3):
            advisor.record_advice(
                db_path, rid, "grader_overdue", "info", f"c-{expected}", "b",
            )
            row = _row(
                db_path,
                "SELECT advice_count FROM advisor_reviews WHERE id=?",
                (rid,),
            )
            assert row[0] == expected

    def test_no_se_cierra_en_caliente_ventana_settle(self, db_path):
        """Con cards recientes el review sigue abierto: el subagente
        puede seguir emitiendo."""
        rid = advisor.record_review(db_path, "s1", "manual")
        advisor.record_advice(db_path, rid, "phase_drift", "warn", "T", "B")
        assert advisor.close_ready_reviews(db_path, "s1") == []
        row = _row(db_path, "SELECT status FROM advisor_reviews WHERE id=?", (rid,))
        assert row[0] == "pending"

    def test_review_sin_cards_se_cierra_como_skipped(self, db_path):
        rid = advisor.record_review(db_path, "s1", "manual")
        assert advisor.close_ready_reviews(db_path, "s1") == []
        cerrados = advisor.close_ready_reviews(db_path, "s1", grace_sec=0)
        assert len(cerrados) == 1
        row = _row(
            db_path,
            "SELECT status, advice_count FROM advisor_reviews WHERE id=?",
            (rid,),
        )
        assert row[0] == "skipped"
        assert row[1] == 0

    def test_close_review_es_idempotente(self, db_path):
        rid = advisor.record_review(db_path, "s1", "manual")
        advisor.record_advice(db_path, rid, "phase_drift", "warn", "T", "B")
        primero = advisor.close_review(db_path, rid)
        segundo = advisor.close_review(db_path, rid)
        assert primero is not None
        assert segundo is None
        # el circuit breaker no se dispara dos veces
        assert _meta_int(db_path, advisor.META_EMPTY_STREAK) == 0

    def test_update_review_status_tiene_call_site_real(self, db_path):
        """`update_review_status` no puede volver a ser decorativo."""
        rid = advisor.record_review(db_path, "s1", "manual")
        advisor.record_advice(db_path, rid, "phase_drift", "warn", "T", "B")
        advisor.close_review(db_path, rid)
        row = _row(
            db_path,
            "SELECT status, advice_count FROM advisor_reviews WHERE id=?",
            (rid,),
        )
        assert row == ("completed", 1)


# ── 2. Circuit breaker conectado al cierre ────────────────────────

class TestCircuitBreaker:
    def test_cierre_con_advice_resetea_el_contador(self, db_path):
        rid = advisor.record_review(db_path, "s1", "manual")
        advisor.record_advice(db_path, rid, "phase_drift", "warn", "T", "B")
        advisor.increment_tool_count(db_path)
        advisor.increment_tool_count(db_path)
        advisor.close_review(db_path, rid)
        assert _meta_int(db_path, advisor.META_TOOL_COUNT) == 0
        assert _meta_int(db_path, advisor.META_EMPTY_STREAK) == 0

    def test_tres_reviews_vacios_disparan_el_backoff(self, db_path):
        for _ in range(advisor.ADVISOR_EMPTY_STREAK_THRESHOLD):
            rid = advisor.record_review(db_path, "s1", "manual")
            advisor.close_review(db_path, rid)
        assert _meta_int(db_path, advisor.META_EMPTY_STREAK) == 3
        assert (
            _meta_int(db_path, advisor.META_CURRENT_INTERVAL)
            == advisor.ADVISOR_BACKOFF_INTERVAL
        )

    def test_review_con_advice_devuelve_el_intervalo_al_default(self, db_path):
        for _ in range(advisor.ADVISOR_EMPTY_STREAK_THRESHOLD):
            rid = advisor.record_review(db_path, "s1", "manual")
            advisor.close_review(db_path, rid)
        rid = advisor.record_review(db_path, "s1", "manual")
        advisor.record_advice(db_path, rid, "phase_drift", "warn", "T", "B")
        advisor.close_review(db_path, rid)
        assert (
            _meta_int(db_path, advisor.META_CURRENT_INTERVAL)
            == advisor.ADVISOR_DEFAULT_INTERVAL
        )
        assert _meta_int(db_path, advisor.META_EMPTY_STREAK) == 0


# ── 3. Reparación idempotente de reviews 'pending' ────────────────

class TestStaleReviewRepair:
    def _seed_stale(self, db_path: str, n: int = 3) -> None:
        with sqlite3.connect(db_path) as c:
            for i in range(n):
                c.execute(
                    "INSERT INTO advisor_reviews "
                    "(session_id, triggered_at, trigger_kind, status) "
                    "VALUES (?, datetime('now', '-2 hours'), 'tool_count', 'pending')",
                    (f"s_old_{i}",),
                )
            c.commit()

    def test_poda_los_pending_antiguos(self, db_path):
        self._seed_stale(db_path, 3)
        assert advisor.reap_stale_reviews(db_path) == 3
        row = _row(
            db_path,
            "SELECT COUNT(*) FROM advisor_reviews WHERE status='pending'",
        )
        assert row[0] == 0
        row = _row(
            db_path,
            "SELECT COUNT(*) FROM advisor_reviews WHERE status='abandoned'",
        )
        assert row[0] == 3

    def test_la_reparacion_es_idempotente(self, db_path):
        self._seed_stale(db_path, 3)
        assert advisor.reap_stale_reviews(db_path) == 3
        # segunda pasada: nada que podar
        assert advisor.reap_stale_reviews(db_path) == 0
        assert advisor.reap_stale_reviews(db_path) == 0
        row = _row(
            db_path,
            "SELECT COUNT(*) FROM advisor_reviews WHERE status='abandoned'",
        )
        assert row[0] == 3

    def test_no_toca_reviews_recientes(self, db_path):
        rid = advisor.record_review(db_path, "s1", "manual")
        assert advisor.reap_stale_reviews(db_path) == 0
        row = _row(db_path, "SELECT status FROM advisor_reviews WHERE id=?", (rid,))
        assert row[0] == "pending"

    def test_no_descuadra_el_circuit_breaker(self, db_path):
        """Miles de reviews de basura no pueden dejar el advisor en
        backoff perpetuo: la poda no alimenta `empty_streak`."""
        self._seed_stale(db_path, 20)
        assert advisor.reap_stale_reviews(db_path) == 20
        assert _meta_int(db_path, advisor.META_EMPTY_STREAK) == 0
        assert (
            advisor.get_current_interval(db_path)
            == advisor.ADVISOR_DEFAULT_INTERVAL
        )

    def test_un_review_con_cards_podado_queda_completed(self, db_path):
        rid = advisor.record_review(db_path, "s1", "manual")
        advisor.record_advice(db_path, rid, "phase_drift", "warn", "T", "B")
        with sqlite3.connect(db_path) as c:
            c.execute(
                "UPDATE advisor_reviews SET triggered_at=datetime('now','-2 hours') "
                "WHERE id=?",
                (rid,),
            )
            c.commit()
        assert advisor.reap_stale_reviews(db_path) == 1
        row = _row(
            db_path,
            "SELECT status, advice_count FROM advisor_reviews WHERE id=?",
            (rid,),
        )
        assert row == ("completed", 1)


# ── 4. El hook no apila reviews (guard anti-flood) ─────────────────

class TestHookNoFlood:
    def _invoke(self, payload: dict, project_root: Path):
        return subprocess.run(
            [sys.executable, str(HOOK_TRIGGER)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            cwd=str(project_root),
            timeout=10,
        )

    @pytest.fixture
    def project_root(self, tmp_path):
        (tmp_path / ".apex").mkdir()
        db = ApexContextDB(str(tmp_path / ".apex" / "context.db"))
        run(db.initialize())
        return tmp_path

    def test_no_crea_un_segundo_review_si_hay_uno_pendiente(
        self, project_root,
    ):
        db_file = str(project_root / ".apex" / "context.db")
        force_payload = {
            "tool_name": "mcp__apex__apex_set_phase",
            "tool_input": {"phase_number": 5, "status": "in_progress"},
            "tool_response": {"content": [{"text": "Fase 5 → in_progress"}]},
            "cwd": str(project_root),
            "session_id": "s_flood",
        }
        cp = self._invoke(force_payload, project_root)
        assert cp.returncode == 0
        assert "advisor_review" in cp.stderr
        # 20 tool calls más: el review sigue abierto, así que no se
        # apila otro (esto era el flood: un review por tool call).
        plain = {
            "tool_name": "Read",
            "tool_input": {"file_path": "x.py"},
            "tool_response": {},
            "cwd": str(project_root),
            "session_id": "s_flood",
        }
        for _ in range(20):
            cp2 = self._invoke(plain, project_root)
            assert cp2.returncode == 0
        assert _count(db_file, "SELECT COUNT(*) FROM advisor_reviews") == 1
        assert _count(
            db_file, "SELECT COUNT(*) FROM advisor_reviews WHERE status='pending'"
        ) == 1

    def test_un_force_trigger_cierra_el_review_anterior(self, project_root):
        """Un force trigger invalida el review en curso: lo cierra y abre
        otro, en vez de dejar reviews huérfanos apilados."""
        db_file = str(project_root / ".apex" / "context.db")
        payload = {
            "tool_name": "mcp__apex__apex_set_phase",
            "tool_input": {"phase_number": 5, "status": "in_progress"},
            "tool_response": {"content": [{"text": "Fase 5 → in_progress"}]},
            "cwd": str(project_root),
            "session_id": "s_force2",
        }
        self._invoke(payload, project_root)
        self._invoke(payload, project_root)
        assert _count(db_file, "SELECT COUNT(*) FROM advisor_reviews") == 2
        assert _count(
            db_file, "SELECT COUNT(*) FROM advisor_reviews WHERE status='pending'"
        ) == 1
        assert _count(
            db_file,
            "SELECT COUNT(*) FROM advisor_reviews WHERE status='skipped'",
        ) == 1

    def test_el_hook_poda_la_basura_historica(self, project_root):
        db_file = str(project_root / ".apex" / "context.db")
        with sqlite3.connect(db_file) as c:
            c.execute(
                "INSERT INTO advisor_reviews "
                "(session_id, triggered_at, trigger_kind, status) "
                "VALUES ('s_old', datetime('now', '-3 hours'), 'tool_count', 'pending')"
            )
            c.commit()
        payload = {
            "tool_name": "Read",
            "tool_input": {"file_path": "x.py"},
            "tool_response": {},
            "cwd": str(project_root),
            "session_id": "s_new",
        }
        cp = self._invoke(payload, project_root)
        assert cp.returncode == 0
        n = _count(db_file, "SELECT COUNT(*) FROM advisor_reviews WHERE status='abandoned'")
        assert n == 1

    def test_el_hook_cierra_el_review_tras_las_cards(self, project_root):
        """Ciclo por hook: review → card → el siguiente tool call
        cierra el review con el conteo real y resetea el tool_count
        (o sea: el circuit breaker queda cableado de verdad)."""
        db_file = str(project_root / ".apex" / "context.db")
        force = {
            "tool_name": "mcp__apex__apex_set_phase",
            "tool_input": {"phase_number": 5, "status": "in_progress"},
            "tool_response": {"content": [{"text": "Fase 5 → in_progress"}]},
            "cwd": str(project_root),
            "session_id": "s_cycle",
        }
        self._invoke(force, project_root)
        # el subagente emite una card
        advisor.record_advice(db_file, 1, "phase_drift", "warn", "T", "B")
        # ...y la card ya está asentada (fuera de la ventana de settle)
        with sqlite3.connect(db_file) as c:
            c.execute(
                "UPDATE advisor_advice SET created_at=datetime('now','-60 seconds') "
                "WHERE review_id=1"
            )
            c.commit()
        plain = {
            "tool_name": "Read",
            "tool_input": {"file_path": "x.py"},
            "tool_response": {},
            "cwd": str(project_root),
            "session_id": "s_cycle",
        }
        cp = self._invoke(plain, project_root)
        assert cp.returncode == 0
        row = _row(
            db_file,
            "SELECT status, advice_count FROM advisor_reviews WHERE id=1",
        )
        assert row == ("completed", 1)
        # el cierre reseteó el tool_count (circuit breaker) y el hook
        # sumó su propio incremento
        with sqlite3.connect(db_file) as c:
            assert advisor._get_meta_int(c, advisor.META_TOOL_COUNT) == 1
            assert advisor._get_meta_int(c, advisor.META_EMPTY_STREAK) == 0

    def test_el_hook_cierra_reviews_de_otra_sesion(self, project_root):
        """Un review de una sesión anterior no puede quedarse abierto
        para siempre: el hook revisa todas las sesiones."""
        db_file = str(project_root / ".apex" / "context.db")
        rid = advisor.record_review(db_file, "s_ayer", "manual")
        advisor.record_advice(db_file, rid, "phase_drift", "warn", "T", "B")
        with sqlite3.connect(db_file) as c:
            c.execute(
                "UPDATE advisor_advice SET created_at=datetime('now','-60 seconds') "
                "WHERE review_id=?",
                (rid,),
            )
            c.commit()
        payload = {
            "tool_name": "Read",
            "tool_input": {"file_path": "x.py"},
            "tool_response": {},
            "cwd": str(project_root),
            "session_id": "s_hoy",
        }
        cp = self._invoke(payload, project_root)
        assert cp.returncode == 0
        row = _row(
            db_file,
            "SELECT status, advice_count FROM advisor_reviews WHERE id=?",
            (rid,),
        )
        assert row == ("completed", 1)


# ── 5. Ciclo completo: review → advice → outcome → tuning → health ─

class TestFullLoop:
    def _emit_and_rate(self, db_path: str, kind: str, n_cards: int) -> list[int]:
        """Emite `n_cards` cards de un kind y las tasa como not_useful."""
        advice_ids: list[int] = []
        for i in range(n_cards):
            rid = advisor.record_review(db_path, "s_loop", "manual")
            aid = advisor.record_advice(
                db_path, rid, kind, "warn", f"{kind}-{i}", "cuerpo",
            )
            advisor.close_ready_reviews(db_path, "s_loop", settle_sec=0)
            advice_ids.append(aid)
            advisor.rate_advice(
                db_path,
                advice_id=aid,
                rating="not_useful",
                reason="la card no aplicaba a esta fase",
            )
        return advice_ids

    def test_ciclo_completo_deja_trazas_en_la_bd(self, db_path):
        # 1. reviews con estado terminal y advice_count > 0
        self._emit_and_rate(db_path, "forgotten_tool", 21)
        row = _row(
            db_path,
            "SELECT COUNT(*) FROM advisor_reviews WHERE status='completed' "
            "AND advice_count > 0",
        )
        assert row[0] == 21
        assert _count(db_path, "SELECT COUNT(*) FROM advisor_reviews "
                              "WHERE status='pending'") == 0

        # 2. advice_outcomes con señal (escape hatch manual)
        assert _count(db_path, "SELECT COUNT(*) FROM advice_outcomes "
                              "WHERE assoc_method='manual'") == 21

        # 3. tuning: 21 not_useful del mismo kind > 40% → propuesta
        propuesta = advisor_tuning.apply_tuning(db_path, dry_run=True)
        assert propuesta["proposals"], "con 21 not_useful debe haber propuesta"
        consts = {p["constant"] for p in propuesta["proposals"]}
        assert "default_interval" in consts

        # 4. aplicar tuning (con cooldown de 7 días)
        aplicado = advisor_tuning.apply_tuning(db_path, dry_run=False)
        assert aplicado["applied"] == 1
        assert _count(db_path, "SELECT COUNT(*) FROM advisor_tuning_history") == 1
        assert (
            advisor.get_advisor_constants(db_path)["default_interval"]
            == advisor_tuning.TUNING_RULES["forgotten_tool"][1]
        )

        # 5. una segunda aplicación no cambia nada (la constante ya está
        #    en el valor propuesto)
        segundo = advisor_tuning.apply_tuning(db_path, dry_run=False)
        assert segundo["applied"] == 0
        assert _count(db_path, "SELECT COUNT(*) FROM advisor_tuning_history") == 1

        # 5b. el cooldown de 7 días bloquea un nuevo tuneo de la misma
        #     constante (si el valor difiere del propuesto)
        advisor.set_advisor_constants(db_path, {"default_interval": 10})
        with sqlite3.connect(db_path) as c:
            c.execute(
                "INSERT INTO advisor_tuning_history "
                "(category, constant_name, old_value, new_value, "
                " trigger_n_outcomes, fp_rate_before, source, reason) "
                "VALUES ('forgotten_tool', 'default_interval', 8, 12, 21, "
                "        1.0, 'auto', 'tuneo previo')"
            )
            c.commit()
        bloqueado = advisor_tuning.apply_tuning(db_path, dry_run=False)
        assert bloqueado["applied"] == 0
        assert "default_interval" in bloqueado["cooldown_blocked"]
        assert _count(db_path, "SELECT COUNT(*) FROM advisor_tuning_history") == 2
        assert (
            advisor.get_advisor_constants(db_path)["default_interval"] == 10
        )

        # 6. health deja de estar estructuralmente vacío
        health = advisor_health.advisor_health(db_path, window_days=30)
        assert health["total_advice_emitted"] == {"forgotten_tool": 21}
        assert health["outcomes_computed"]["forgotten_tool"]["manual"][
            "not_useful"
        ] == 21
        assert health["fp_rate"]["forgotten_tool"] == pytest.approx(1.0)
        assert health["tuning_history"], "el tuning debe verse en health"
        assert health["reviews_pendientes"] == 0
        assert health["reviews_por_estado"]["completed"] == 21
        assert health["advice_sin_outcome"] == 0
        assert (
            health["constants_actuales"]["default_interval"]["source"] == "tuned"
        )

    def test_health_refleja_el_backlog_de_ratings(self, db_path):
        rid = advisor.record_review(db_path, "s1", "manual")
        advisor.record_advice(db_path, rid, "phase_drift", "warn", "T", "B")
        advisor.close_ready_reviews(db_path, "s1", settle_sec=0)
        health = advisor_health.advisor_health(db_path)
        assert health["advice_sin_outcome"] == 1
        assert health["reviews_pendientes"] == 0
        assert health["reviews_por_estado"]["completed"] == 1


# ── 6. El cierre desde el handler MCP ─────────────────────────────

@pytest.fixture(scope="module")
def apex_server_mod():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "apex_server_loop_test",
        str(REPO_ROOT / "mcp" / "apex_server.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestMcpPath:
    def test_record_advice_actualiza_el_conteo_del_review(
        self, apex_server_mod, tmp_path, monkeypatch,
    ):
        (tmp_path / ".apex").mkdir()
        db = ApexContextDB(str(tmp_path / ".apex" / "context.db"))
        run(db.initialize())
        monkeypatch.chdir(tmp_path)
        res = run(apex_server_mod.call_tool(
            "apex_advisor_review",
            {"session_id": "s_mcp", "force": True, "trigger": "manual"},
        ))
        assert "advisor_review" in res[0].text
        res = run(apex_server_mod.call_tool(
            "apex_record_advice",
            {
                "review_id": 1,
                "kind": "phase_drift",
                "severity": "warn",
                "title": "T",
                "body": "B",
                "evidence_refs": ["phase=5"],
            },
        ))
        assert "registrada" in res[0].text
        assert "advice_count=1" in res[0].text
        row = _row(
            str(tmp_path / ".apex" / "context.db"),
            "SELECT advice_count FROM advisor_reviews WHERE id=1",
        )
        assert row[0] == 1
