"""Sprint 16.5 — migración de constantes del Advisor a project_meta.

Las constantes hardcoded en `lib/advisor.py` (default_interval,
backoff_interval, empty_streak_threshold, bundle_max_tokens,
min_calls_before_first, active_advice_window_sec) se persisten en
`project_meta.advisor_constants` (JSON). Si la fila no existe o está
corrupta, fallback a defaults. No se rompe BD existente.

Tests previstos (blueprint S16 §11): default fallback, lectura override,
escritura idempotente, partial override, key desconocida, JSON corrupto.
"""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from context_db import ApexContextDB  # noqa: E402
import advisor  # noqa: E402


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.fixture
def db_path(tmp_path):
    p = tmp_path / "ctx.db"
    db = ApexContextDB(str(p))
    _run(db.initialize())
    return str(p)


# ── 1. Default fallback ──────────────────────────────────────────────

class TestDefaultFallback:
    def test_returns_defaults_when_no_row(self, db_path):
        constants = advisor.get_advisor_constants(db_path)
        assert constants == advisor.ADVISOR_CONSTANT_DEFAULTS

    def test_defaults_match_module_constants(self, db_path):
        constants = advisor.get_advisor_constants(db_path)
        assert constants["default_interval"] == advisor.ADVISOR_DEFAULT_INTERVAL
        assert constants["backoff_interval"] == advisor.ADVISOR_BACKOFF_INTERVAL
        assert (
            constants["empty_streak_threshold"]
            == advisor.ADVISOR_EMPTY_STREAK_THRESHOLD
        )
        assert constants["bundle_max_tokens"] == advisor.ADVISOR_BUNDLE_MAX_TOKENS
        assert (
            constants["min_calls_before_first"]
            == advisor.ADVISOR_MIN_CALLS_BEFORE_FIRST
        )
        assert (
            constants["active_advice_window_sec"]
            == advisor.ACTIVE_ADVICE_WINDOW_SEC
        )


# ── 2. Lectura desde override persistido ─────────────────────────────

class TestPersistedOverride:
    def test_read_after_set_returns_override_value(self, db_path):
        advisor.set_advisor_constants(db_path, {"default_interval": 12})
        constants = advisor.get_advisor_constants(db_path)
        assert constants["default_interval"] == 12

    def test_set_writes_to_project_meta_advisor_constants(self, db_path):
        advisor.set_advisor_constants(db_path, {"bundle_max_tokens": 1800})
        with sqlite3.connect(db_path) as c:
            row = c.execute(
                "SELECT value FROM project_meta WHERE key='advisor_constants'"
            ).fetchone()
        assert row is not None
        stored = json.loads(row[0])
        assert stored["bundle_max_tokens"] == 1800


# ── 3. Idempotencia ──────────────────────────────────────────────────

class TestIdempotent:
    def test_set_twice_same_dict_round_trip_unchanged(self, db_path):
        payload = {"default_interval": 10, "backoff_interval": 20}
        advisor.set_advisor_constants(db_path, payload)
        first = advisor.get_advisor_constants(db_path)
        advisor.set_advisor_constants(db_path, payload)
        second = advisor.get_advisor_constants(db_path)
        assert first == second


# ── 4. Override parcial: keys ausentes caen a defaults ───────────────

class TestPartialOverride:
    def test_missing_keys_fall_back_to_defaults(self, db_path):
        advisor.set_advisor_constants(db_path, {"default_interval": 99})
        constants = advisor.get_advisor_constants(db_path)
        assert constants["default_interval"] == 99
        # Las demás siguen en defaults
        assert (
            constants["backoff_interval"]
            == advisor.ADVISOR_CONSTANT_DEFAULTS["backoff_interval"]
        )
        assert (
            constants["bundle_max_tokens"]
            == advisor.ADVISOR_CONSTANT_DEFAULTS["bundle_max_tokens"]
        )


# ── 5. Keys desconocidas se filtran al persistir ─────────────────────

class TestUnknownKeyFiltered:
    def test_unknown_key_not_persisted_or_returned(self, db_path):
        advisor.set_advisor_constants(
            db_path,
            {"default_interval": 7, "garbage_key": 42},
        )
        constants = advisor.get_advisor_constants(db_path)
        assert "garbage_key" not in constants
        assert constants["default_interval"] == 7
        # Verificación de que tampoco se escribió a la BD
        with sqlite3.connect(db_path) as c:
            row = c.execute(
                "SELECT value FROM project_meta WHERE key='advisor_constants'"
            ).fetchone()
        stored = json.loads(row[0])
        assert "garbage_key" not in stored


# ── 6. JSON corrupto en la BD → fallback a defaults ──────────────────

class TestCorruptJsonFallback:
    def test_corrupt_value_returns_defaults(self, db_path):
        # Inyectamos un valor no-JSON directamente vía sqlite
        with sqlite3.connect(db_path) as c:
            advisor._set_meta(c, "advisor_constants", "{not valid json")
            c.commit()
        constants = advisor.get_advisor_constants(db_path)
        assert constants == advisor.ADVISOR_CONSTANT_DEFAULTS

    def test_non_dict_json_returns_defaults(self, db_path):
        with sqlite3.connect(db_path) as c:
            advisor._set_meta(c, "advisor_constants", json.dumps([1, 2, 3]))
            c.commit()
        constants = advisor.get_advisor_constants(db_path)
        assert constants == advisor.ADVISOR_CONSTANT_DEFAULTS
