"""Sprint 15 S15.3 — tests para lib/reasoning_traces.py."""
from __future__ import annotations

import asyncio
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from context_db import ApexContextDB  # noqa: E402
import reasoning_traces as rt  # noqa: E402


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


_VALID_DELIB = (
    "Después de revisar el spec, decido aplicar el patrón advisor en lugar de "
    "una API directa porque MAX cubre subagent budget y evita gestionar API keys. "
    "Esto reduce la superficie de fallo y mantiene el flujo dentro de la sesión "
    "activa. La alternativa que descarté fue llamar a Anthropic SDK desde el hook, "
    "pero la falta de cuotas predecibles en MAX-vs-API la hizo arriesgada para "
    "el roadmap del usuario."
)


class TestLogTrace:
    def test_log_trace_ok_returns_id(self, db_path):
        tid = rt.log_trace(
            db_path,
            session_id="s1",
            phase=2,
            category="multi_agent_coordination",
            gate_kind="phase_close",
            deliberation=_VALID_DELIB,
            calibration_confidence=0.8,
            calibration_text="80% por evidencia X",
            alternatives_considered=[
                {"option": "API directa", "rejected_because": "MAX no cubre"},
            ],
        )
        assert isinstance(tid, int) and tid > 0

    def test_invalid_category_raises(self, db_path):
        with pytest.raises(ValueError):
            rt.log_trace(
                db_path, "s1", 2, "bogus_category", "phase_close",
                _VALID_DELIB, 0.8, "txt", [],
            )

    def test_invalid_gate_kind_raises(self, db_path):
        with pytest.raises(ValueError):
            rt.log_trace(
                db_path, "s1", 2, "multi_agent_coordination", "bogus_gate",
                _VALID_DELIB, 0.8, "txt", [],
            )

    def test_short_deliberation_raises(self, db_path):
        with pytest.raises(ValueError):
            rt.log_trace(
                db_path, "s1", 2, "multi_agent_coordination", "phase_close",
                "muy corto", 0.8, "txt", [],
            )

    def test_long_deliberation_raises(self, db_path):
        with pytest.raises(ValueError):
            rt.log_trace(
                db_path, "s1", 2, "multi_agent_coordination", "phase_close",
                "x" * 2500, 0.8, "txt", [],
            )

    def test_invalid_confidence_raises(self, db_path):
        with pytest.raises(ValueError):
            rt.log_trace(
                db_path, "s1", 2, "multi_agent_coordination", "phase_close",
                _VALID_DELIB, 1.5, "txt", [],
            )
        with pytest.raises(ValueError):
            rt.log_trace(
                db_path, "s1", 2, "multi_agent_coordination", "phase_close",
                _VALID_DELIB, -0.1, "txt", [],
            )

    def test_alternatives_serialized_as_json(self, db_path):
        alts = [
            {"option": "A", "rejected_because": "coste alto"},
            {"option": "B", "rejected_because": "no cubre dependencia"},
        ]
        tid = rt.log_trace(
            db_path, "s_alt", 3, "long_horizon_consequences", "override",
            _VALID_DELIB, 0.6, "ok", alts,
        )
        traces = rt.get_recent(db_path, "s_alt", limit=1)
        assert len(traces) == 1
        # alternatives_considered viene como string JSON desde la BD
        decoded = json.loads(traces[0]["alternatives_considered"])
        assert decoded == alts


class TestGetRecent:
    def test_descending_order(self, db_path):
        for i in range(3):
            rt.log_trace(
                db_path, "s_ord", 2, "multi_agent_coordination", "phase_close",
                _VALID_DELIB + f" iter {i}", 0.5, "", [],
            )
        traces = rt.get_recent(db_path, "s_ord", limit=10)
        assert len(traces) == 3
        ids = [t["id"] for t in traces]
        assert ids == sorted(ids, reverse=True)

    def test_respects_limit(self, db_path):
        for _ in range(5):
            rt.log_trace(
                db_path, "s_lim", 2, "multi_agent_coordination", "phase_close",
                _VALID_DELIB, 0.5, "", [],
            )
        assert len(rt.get_recent(db_path, "s_lim", limit=2)) == 2

    def test_filters_by_session(self, db_path):
        rt.log_trace(
            db_path, "s_a", 2, "multi_agent_coordination", "phase_close",
            _VALID_DELIB, 0.5, "", [],
        )
        rt.log_trace(
            db_path, "s_b", 2, "multi_agent_coordination", "phase_close",
            _VALID_DELIB, 0.5, "", [],
        )
        a = rt.get_recent(db_path, "s_a")
        b = rt.get_recent(db_path, "s_b")
        assert len(a) == 1 and len(b) == 1
        assert a[0]["session_id"] == "s_a"


class TestPrompts:
    def test_prompt_for_trace_contains_category_and_gate(self):
        s = rt.prompt_for_trace("cascading_failure_recovery", "grader_blocking")
        assert "cascading_failure_recovery" in s
        assert "grader_blocking" in s
        assert "apex_log_trace" in s


class TestExport:
    def test_export_sharegpt_writes_jsonl(self, db_path, tmp_path):
        rt.log_trace(
            db_path, "s_x", 2, "multi_agent_coordination", "phase_close",
            _VALID_DELIB, 0.7, "70% confianza", [{"option": "Y", "rejected_because": "Z"}],
        )
        out = tmp_path / "traces.jsonl"
        n = rt.export_sharegpt(db_path, "/tmp/proj", str(out))
        assert n == 1
        content = out.read_text(encoding="utf-8").strip().splitlines()
        assert len(content) == 1
        record = json.loads(content[0])
        assert "conversations" in record
        assert record["conversations"][0]["from"] == "human"
        assert record["conversations"][1]["from"] == "gpt"
