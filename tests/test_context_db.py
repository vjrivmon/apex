"""Tests para APEX Context DB v2."""
import asyncio
import os
import pytest
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from context_db import ApexContextDB


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.db")


@pytest.fixture
def db(db_path):
    return ApexContextDB(db_path)


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class TestInitialization:
    def test_creates_db_file(self, db, db_path):
        run(db.initialize())
        assert os.path.exists(db_path)

    def test_creates_14_phases(self, db):
        run(db.initialize())
        phases = run(db.get_all_phases())
        assert len(phases) == 15  # 0 a 14

    def test_phases_start_pending(self, db):
        run(db.initialize())
        phases = run(db.get_all_phases())
        assert all(p["status"] == "pending" for p in phases)


class TestMeta:
    def test_set_and_get(self, db):
        run(db.initialize())
        run(db.set_meta("nombre", "Test"))
        assert run(db.get_meta("nombre")) == "Test"

    def test_missing_key_returns_none(self, db):
        run(db.initialize())
        assert run(db.get_meta("inexistente")) is None

    def test_overwrite(self, db):
        run(db.initialize())
        run(db.set_meta("k", "v1"))
        run(db.set_meta("k", "v2"))
        assert run(db.get_meta("k")) == "v2"


class TestPhases:
    def test_set_in_progress(self, db):
        run(db.initialize())
        run(db.set_phase(0, "in_progress", "Empezando"))
        current = run(db.get_current_phase())
        assert current is not None
        assert current["number"] == 0
        assert current["name"] == "socrático"

    def test_set_completed(self, db):
        run(db.initialize())
        run(db.set_phase(0, "completed", "Terminado"))
        current = run(db.get_current_phase())
        assert current is None  # ninguna en progreso


class TestTemporalDecisions:
    def test_add_decision(self, db):
        run(db.initialize())
        did = run(db.add_decision("stack", "Python", "Mejor para ML", phase=2))
        assert did > 0

    def test_active_decisions(self, db):
        run(db.initialize())
        run(db.add_decision("stack", "Python", "ML"))
        active = run(db.get_active_decisions())
        assert len(active) == 1
        assert active[0]["decision"] == "Python"

    def test_invalidate_removes_from_active(self, db):
        run(db.initialize())
        d1 = run(db.add_decision("stack", "Node.js", "Rápido"))
        run(db.add_decision("stack", "Python", "ML"))
        run(db.invalidate_decision(d1, "Cambiamos"))
        active = run(db.get_active_decisions())
        assert len(active) == 1
        assert active[0]["decision"] == "Python"

    def test_filter_by_category(self, db):
        run(db.initialize())
        run(db.add_decision("stack", "Python", "ML"))
        run(db.add_decision("design", "Dark mode", "Preferencia"))
        stack = run(db.get_active_decisions("stack"))
        assert len(stack) == 1


class TestErrorMemory:
    def test_add_error(self, db):
        run(db.initialize())
        eid = run(db.add_error("claude", "Frontend antes de backend", "Backend-first"))
        assert eid > 0

    def test_recurrence_increments(self, db):
        run(db.initialize())
        run(db.add_error("claude", "Mismo error", "Lección"))
        run(db.add_error("claude", "Mismo error", "Lección v2"))
        errors = run(db.get_errors())
        assert len(errors) == 1
        assert errors[0]["recurrence_count"] == 2
        assert errors[0]["lesson"] == "Lección v2"

    def test_filter_by_source(self, db):
        run(db.initialize())
        run(db.add_error("claude", "Error Claude", "L1"))
        run(db.add_error("user", "Error usuario", "L2"))
        claude_errors = run(db.get_errors(source="claude"))
        assert len(claude_errors) == 1
        assert claude_errors[0]["source"] == "claude"

    def test_filter_by_severity(self, db):
        run(db.initialize())
        run(db.add_error("claude", "Leve", "L", severity="low"))
        run(db.add_error("claude", "Grave", "L", severity="high"))
        high = run(db.get_errors(min_severity="high"))
        assert len(high) == 1


class TestComponents:
    def test_add_and_list(self, db):
        run(db.initialize())
        run(db.add_component("scraper-mercadona", "Mercadona", "agent", 7, "API"))
        comps = run(db.get_components())
        assert len(comps) == 1
        assert comps[0]["name"] == "Mercadona"

    def test_update_status(self, db):
        run(db.initialize())
        run(db.add_component("sc", "Test", "agent"))
        run(db.update_component_status("sc", "verified"))
        comps = run(db.get_components(status="verified"))
        assert len(comps) == 1

    def test_filter_by_type(self, db):
        run(db.initialize())
        run(db.add_component("a1", "Agent1", "agent"))
        run(db.add_component("p1", "Port1", "port"))
        agents = run(db.get_components(type="agent"))
        assert len(agents) == 1


class TestNextSteps:
    def test_add_and_list(self, db):
        run(db.initialize())
        run(db.add_next_step("Hacer X", priority=1))
        steps = run(db.get_next_steps())
        assert len(steps) == 1
        assert steps[0]["priority"] == 1

    def test_complete_step(self, db):
        run(db.initialize())
        sid = run(db.add_next_step("Hacer X"))
        run(db.complete_step(sid))
        pending = run(db.get_next_steps("pending"))
        done = run(db.get_next_steps("done"))
        assert len(pending) == 0
        assert len(done) == 1


class TestWikiPages:
    def test_add_and_get(self, db):
        run(db.initialize())
        run(db.add_wiki_page("entities/product", "Producto", "# Producto\nEntidad core"))
        page = run(db.get_wiki_page("entities/product"))
        assert page is not None
        assert page["title"] == "Producto"

    def test_list_by_type(self, db):
        run(db.initialize())
        run(db.add_wiki_page("entities/p1", "P1", "C1", page_type="entity"))
        run(db.add_wiki_page("concepts/c1", "C1", "C2", page_type="concept"))
        entities = run(db.list_wiki_pages("entity"))
        assert len(entities) == 1


class TestProgressiveDisclosure:
    def test_compact_is_short(self, db):
        run(db.initialize())
        run(db.set_meta("nombre", "Test"))
        run(db.set_phase(2, "in_progress"))
        compact = run(db.get_context("compact"))
        assert "Test" in compact
        assert len(compact) < 500

    def test_timeline_has_decisions(self, db):
        run(db.initialize())
        run(db.add_decision("stack", "Python", "ML"))
        timeline = run(db.get_context("timeline"))
        assert "Python" in timeline

    def test_full_has_wiki(self, db):
        run(db.initialize())
        run(db.add_wiki_page("entities/x", "X", "Content"))
        full = run(db.get_context("full"))
        assert "Knowledge Base" in full
        assert "entities/x" in full

    def test_full_shows_invalidated_decisions(self, db):
        run(db.initialize())
        d1 = run(db.add_decision("stack", "Node.js", "Rápido"))
        run(db.invalidate_decision(d1))
        full = run(db.get_context("full"))
        assert "invalidada" in full.lower() or "Node.js" in full


class TestSearch:
    def test_fts_search(self, db):
        run(db.initialize())
        run(db.add_decision("stack", "Python FastAPI", "Backend-first"))
        results = run(db.search("backend"))
        assert len(results) >= 1
