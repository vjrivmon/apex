"""Sprint 17 S17.6 — renderizadores SQL→markdown, caché e invalidación.

Cubre:
- `errors_to_md`, `skills_history_to_md` y `lessons_to_md` renderizan los
  datos reales de las BDs de origen.
- El renderizado es idempotente: mismos datos → mismo markdown.
- El caché (`vfs_render_cache`) hace round-trip y se invalida cuando los
  datos fuente cambian.
- `vfs_query_log` registra las consultas.
- Las BDs de origen (context.db de otros proyectos y hub.db) se abren en
  solo-lectura: el render nunca las modifica.
"""
import asyncio
import hashlib
import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from context_db import ApexContextDB  # noqa: E402
from vfs_sql_render import (  # noqa: E402
    QueryLog,
    RenderCache,
    cache_key_for,
    errors_to_md,
    lessons_to_md,
    skills_history_to_md,
    split_sections,
)


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.fixture
def project_root(tmp_path):
    """Proyecto con `context.db` sembrado: errores, roles y verdicts."""
    root = tmp_path / "RoadToDevOps"
    apex = root / "apex"
    (apex / ".apex").mkdir(parents=True)
    db_path = apex / ".apex" / "context.db"
    db = ApexContextDB(str(db_path))
    run(db.initialize())
    run(db.add_error(
        source="claude", phase=3,
        description="El hook de cierre no disparaba",
        cause="El trigger semántico no estaba cableado",
        fix="Cablear `apex_doctor` en el cierre",
        lesson="Un hook sin test es un hook que no existe",
        severity="critical",
    ))
    run(db.add_error(
        source="user", phase=5,
        description="Falta el README del scaffold",
        lesson="Todo scaffold necesita README",
        severity="medium",
    ))
    run(db.add_verdict(
        phase=5, quality=3,
        reasoning="el scaffold está pero sin README",
        issues=["missing_readme"], should_block=False,
    ))
    return root


@pytest.fixture
def project_db(project_root):
    return project_root / "apex" / ".apex" / "context.db"


@pytest.fixture
def cache_db(tmp_path):
    """`context.db` del proyecto actual: ahí vive el caché y la telemetría."""
    path = tmp_path / "cache" / "context.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    db = ApexContextDB(str(path))
    run(db.initialize())
    return path


@pytest.fixture
def hub_db(tmp_path):
    """Hub con la tabla `errors` (lecciones cross-project)."""
    path = tmp_path / "hub.db"
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE errors (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "project_id TEXT, description TEXT, lesson TEXT, severity TEXT, "
        "recurrence_count INTEGER DEFAULT 1, created_at TEXT)"
    )
    conn.executemany(
        "INSERT INTO errors (project_id, description, lesson, severity, "
        "recurrence_count, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        [
            ("apex", "error de apex", "leccion de apex", "critical", 2, "2026-05-01"),
            ("otro", "error de otro", "leccion de otro", "high", 1, "2026-05-02"),
            ("apex", "otro error de apex", "otra leccion", "medium", 1, "2026-05-03"),
        ],
    )
    conn.commit()
    conn.close()
    return path


# ── errors_to_md ────────────────────────────────────────────────────────


class TestErrorsToMd:
    def test_renderiza_los_errores(self, project_db):
        md = errors_to_md("apex", project_db)
        assert "# Errores de apex" in md
        assert "- **Total:** 2" in md
        assert "El hook de cierre no disparaba" in md
        assert "Un hook sin test es un hook que no existe" in md

    def test_es_idempotente(self, project_db):
        """Mismos datos → mismo markdown, byte a byte."""
        primero = errors_to_md("apex", project_db)
        segundo = errors_to_md("apex", project_db)
        assert primero == segundo

    def test_cambia_cuando_cambian_los_datos(self, project_db):
        antes = errors_to_md("apex", project_db)
        db = ApexContextDB(str(project_db))
        run(db.add_error(source="user", description="error nuevo", lesson="l",
                         severity="low"))
        despues = errors_to_md("apex", project_db)
        assert despues != antes
        assert "- **Total:** 3" in despues

    def test_proyecto_sin_bd_devuelve_vacio(self, tmp_path):
        md = errors_to_md("nada", tmp_path / "no-existe.db")
        assert "- **Total:** 0" in md
        assert "Sin errores" in md

    def test_las_secciones_son_por_error(self, project_db):
        secciones = split_sections(errors_to_md("apex", project_db))
        ids = [nombre for nombre, _ in secciones]
        assert ids == ["error-1", "error-2"]


# ── skills_history_to_md ────────────────────────────────────────────────


class TestSkillsHistoryToMd:
    def test_incluye_verdicts_del_grader(self, project_db):
        md = skills_history_to_md("apex", project_db)
        assert "# Historial de skills de apex" in md
        assert "## verdict-1" in md
        assert "el scaffold está pero sin README" in md

    def test_es_idempotente(self, project_db):
        assert skills_history_to_md("apex", project_db) == skills_history_to_md(
            "apex", project_db
        )

    def test_proyecto_sin_bd_devuelve_vacio(self, tmp_path):
        md = skills_history_to_md("nada", tmp_path / "no-existe.db")
        assert "Sin historial registrado" in md


# ── lessons_to_md ──────────────────────────────────────────────────────


class TestLessonsToMd:
    def test_filtra_por_severidad(self, hub_db):
        md = lessons_to_md("critical", hub_db)
        assert "error de apex" in md
        assert "error de otro" not in md
        assert "severidad: critical" in md

    def test_filtra_por_proyecto(self, hub_db):
        md = lessons_to_md(None, hub_db, project="apex")
        assert "error de apex" in md
        assert "error de otro" not in md

    def test_es_idempotente(self, hub_db):
        assert lessons_to_md(None, hub_db) == lessons_to_md(None, hub_db)

    def test_hub_solo_lectura(self, hub_db):
        """El render no modifica el hub: se abre en modo ro."""
        antes = hashlib.sha256(hub_db.read_bytes()).hexdigest()
        lessons_to_md(None, hub_db)
        despues = hashlib.sha256(hub_db.read_bytes()).hexdigest()
        assert antes == despues


# ── Caché (vfs_render_cache) ───────────────────────────────────────────


class TestRenderCache:
    def test_round_trip(self, cache_db):
        cache = RenderCache(cache_db)
        assert cache.count() == 0
        assert cache.put("k1", "contenido", "h1") is True
        hit = cache.get("k1")
        assert hit is not None
        assert hit[0] == "contenido"
        assert hit[1] == "h1"
        assert cache.count() == 1

    def test_put_reemplaza(self, cache_db):
        cache = RenderCache(cache_db)
        cache.put("k1", "v1", "h1")
        cache.put("k1", "v2", "h2")
        assert cache.count() == 1
        assert cache.get("k1")[0] == "v2"

    def test_get_de_clave_inexistente(self, cache_db):
        assert RenderCache(cache_db).get("no-existe") is None

    def test_cache_sin_db_es_noop(self, tmp_path):
        """Sin BD de proyecto el caché no rompe nada: no inventa ficheros."""
        cache = RenderCache(tmp_path / "no-existe.db")
        assert cache.put("k", "v", "h") is False
        assert cache.get("k") is None
        assert cache.count() == 0

    def test_invalidate_all(self, cache_db):
        cache = RenderCache(cache_db)
        cache.put("k1", "v1", "h1")
        cache.put("k2", "v2", "h2")
        assert cache.invalidate_all() == 2
        assert cache.count() == 0

    def test_invalidate_by_source_hash(self, cache_db):
        cache = RenderCache(cache_db)
        cache.put("k1", "v1", "h-comun")
        cache.put("k2", "v2", "h-otro")
        assert cache.invalidate_by_source_hash("h-comun") == 1
        assert cache.get("k1") is None
        assert cache.get("k2") is not None

    def test_prune_borra_huerfanos(self, cache_db):
        cache = RenderCache(cache_db)
        cache.put("k1", "v1", "h1")
        cache.put("k2", "v2", "h2")
        assert cache.prune({"k1"}) == 1
        assert cache.get("k1") is not None
        assert cache.get("k2") is None

    def test_prune_stale_detecta_drift(self, cache_db):
        cache = RenderCache(cache_db)
        cache.put("k1", "v1", "h-vivo")
        cache.put("k2", "v2", "h-muerto")
        assert cache.prune_stale({"h-vivo"}) == 1
        assert cache.get("k1") is not None
        assert cache.get("k2") is None


class TestCacheInvalidation:
    """El mecanismo de invalidación (riesgo R1 del blueprint)."""

    def test_la_clave_cambia_cuando_cambian_los_datos(self, project_db, cache_db):
        """Clave direccionada por contenido: la invalidación es intrínseca."""
        cache = RenderCache(cache_db)
        antes = errors_to_md("apex", project_db, cache)
        assert cache.count() == 1
        clave_vieja = next(iter(cache.keys()))

        db = ApexContextDB(str(project_db))
        run(db.add_error(source="user", description="otro error", lesson="l",
                         severity="low"))
        despues = errors_to_md("apex", project_db, cache)

        assert despues != antes
        assert cache.count() == 2, "la entrada vieja debe quedar como huérfana"
        assert clave_vieja in cache.keys()
        # El prune es la limpieza de los huérfanos que deja el cambio.
        assert cache.prune(cache.keys() - {clave_vieja}) == 1
        assert cache.count() == 1

    def test_render_servido_desde_cache(self, project_db, cache_db):
        """La segunda lectura sale del caché: mismo markdown, sin rehacerlo."""
        from vfs_sql_render import ERRORS_QUERY, cached_render, _query_rows

        cache = RenderCache(cache_db)
        rows = _query_rows(project_db, ERRORS_QUERY)
        primero = cached_render(ERRORS_QUERY, rows, lambda r: "x", cache)
        segundo = cached_render(ERRORS_QUERY, rows, lambda r: "y", cache)
        assert primero.cached is False
        assert segundo.cached is True
        assert segundo.markdown == "x", "el caché debe devolver el render viejo"

    def test_ttl_expira_la_entrada(self, cache_db):
        from vfs_sql_render import cached_render

        cache = RenderCache(cache_db)
        resultado = cached_render("q", [{"a": 1}], lambda r: "x", cache,
                                        max_age_seconds=-1)
        assert resultado.cached is False, "una entrada caducada no se reutiliza"


# ── Telemetría (vfs_query_log) ──────────────────────────────────────────


class TestQueryLog:
    def test_round_trip(self, cache_db):
        log = QueryLog(cache_db)
        assert log.count() == 0
        assert log.record("ls /projects/apex/wiki", "apex", 3, 12) is True
        assert log.count() == 1
        filas = log.recent()
        assert filas[0]["command"] == "ls /projects/apex/wiki"
        assert filas[0]["project_slug"] == "apex"
        assert filas[0]["hits"] == 3
        assert filas[0]["latency_ms"] == 12

    def test_slug_null_para_queries_cross_project(self, cache_db):
        log = QueryLog(cache_db)
        log.record("grep -r foo /projects/", None, 0, 400)
        assert log.recent()[0]["project_slug"] is None

    def test_sin_db_no_rompe(self, tmp_path):
        log = QueryLog(tmp_path / "no-existe.db")
        assert log.record("ls", None, 0, 0) is False
        assert log.count() == 0
        assert log.recent() == []


def test_cache_key_es_sha256_de_query_mas_rows():
    """La clave es sha256(query + rows), tal y como fija el blueprint."""
    import hashlib

    rows = [{"a": 1}]
    esperado = hashlib.sha256(
        ("q" + "\n" + hashlib.sha256(
            '[{"a": 1}]'.encode("utf-8")
        ).hexdigest()).encode("utf-8")
    ).hexdigest()
    assert cache_key_for("q", rows) == esperado
