"""Sprint 17 S17.8 — tools MCP del VirtualFS.

Comprueba que las cuatro tools (`apex_vfs_exec`, `apex_vfs_ls`,
`apex_vfs_cat`, `apex_vfs_grep`) son alcanzables desde el dispatcher MCP
y que:
- respetan la whitelist de raíces (`hub.db.global_meta.vfs_allowed_roots`),
- sirven también las categorías virtuales (errors, skills-history),
- registran cada consulta en `vfs_query_log`,
- no escriben nunca en `hub.db` (solo-lectura),
- rechazan escrituras con EROFS.
"""
import asyncio
import hashlib
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "lib"))
sys.path.insert(0, str(_REPO))

from context_db import ApexContextDB  # noqa: E402


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.fixture(scope="module")
def handlers():
    """Carga el paquete de handlers bajo el alias `apex_handlers`."""
    pkg = _REPO / "mcp" / "handlers"
    spec = importlib.util.spec_from_file_location(
        "apex_handlers", pkg / "__init__.py",
        submodule_search_locations=[str(pkg)],
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["apex_handlers"] = mod
    raiz = str(_REPO)
    original = list(sys.path)
    sys.path[:] = [p for p in sys.path if p != raiz] + [raiz]
    try:
        spec.loader.exec_module(mod)
        # `apex_handlers/__init__.py` aún no registra el módulo del VFS
        # (lo hace otro agente); aquí se importa a mano para poder
        # monkeypatchear sus constantes.
        mod.vfs = importlib.import_module("apex_handlers.vfs")
    finally:
        sys.path[:] = original
    return mod


@pytest.fixture
def entorno(tmp_path, handlers, monkeypatch):
    """Proyecto + hub sintéticos, con la whitelist apuntando al tmp."""
    root = tmp_path / "RoadToDevOps"
    wiki = root / "apex" / "wiki"
    wiki.mkdir(parents=True)
    (wiki / "a.md").write_text("hola tdd\nmundo\n")
    (root / "apex" / ".apex").mkdir(parents=True)
    project_db_path = root / "apex" / ".apex" / "context.db"
    project_db = ApexContextDB(str(project_db_path))
    run(project_db.initialize())
    run(project_db.add_error(
        source="claude", description="error sembrado", lesson="leccion",
        severity="critical",
    ))

    hub_path = tmp_path / "hub.db"
    conn = sqlite3.connect(str(hub_path))
    conn.execute(
        "CREATE TABLE global_meta (key TEXT PRIMARY KEY, value TEXT, "
        "updated_at TEXT DEFAULT (datetime('now')))"
    )
    conn.execute(
        "INSERT INTO global_meta (key, value) VALUES (?, ?)",
        ("vfs_allowed_roots", json.dumps([str(root)])),
    )
    conn.execute(
        "CREATE TABLE errors (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "project_id TEXT, description TEXT, lesson TEXT, severity TEXT, "
        "recurrence_count INTEGER DEFAULT 1, created_at TEXT)"
    )
    conn.execute(
        "INSERT INTO errors (project_id, description, lesson, severity) "
        "VALUES ('apex', 'error del hub', 'leccion del hub', 'critical')"
    )
    conn.commit()
    conn.close()

    # `context.db` del proyecto actual: caché de renders y telemetría.
    current_path = tmp_path / "proyecto" / ".apex" / "context.db"
    current_path.parent.mkdir(parents=True, exist_ok=True)
    current = ApexContextDB(str(current_path))
    run(current.initialize())

    monkeypatch.setattr(
        handlers.vfs, "_HUB_DB", hub_path, raising=True
    )
    return {
        "root": root,
        "hub": hub_path,
        "db": current,
        "current_path": current_path,
    }


def _texto(salida) -> str:
    return salida[0].text


def _json(salida) -> dict:
    return json.loads(_texto(salida))


class TestCargaDelModulo:
    def test_se_importa_como_apex_handlers_vfs(self, handlers):
        """El paquete se llama `apex_handlers`: `mcp.handlers` ensombrece
        el SDK `mcp` y rompe el import de `mcp.types`."""
        import apex_handlers.vfs as modulo

        assert modulo.__name__ == "apex_handlers.vfs"
        assert hasattr(modulo, "handle_apex_vfs_exec")
        assert hasattr(modulo, "handle_apex_vfs_ls")
        assert hasattr(modulo, "handle_apex_vfs_cat")
        assert hasattr(modulo, "handle_apex_vfs_grep")

    def test_declara_las_cuatro_tools(self, handlers):
        import apex_handlers.vfs as modulo

        assert modulo.VFS_TOOLS == frozenset({
            "apex_vfs_exec", "apex_vfs_ls", "apex_vfs_cat", "apex_vfs_grep",
        })


# ── apex_vfs_ls ────────────────────────────────────────────────────────


class TestLs:
    def test_lista_el_contenido(self, handlers, entorno):
        from apex_handlers.vfs import handle_apex_vfs_ls

        payload = _json(run(handle_apex_vfs_ls(entorno["db"], {"path": "/projects/apex/wiki"})))
        nombres = [e["name"] for e in payload["entries"]]
        assert "a.md" in nombres
        assert payload["path"] == "/projects/apex/wiki"

    def test_lista_los_proyectos(self, handlers, entorno):
        from apex_handlers.vfs import handle_apex_vfs_ls

        payload = _json(run(handle_apex_vfs_ls(entorno["db"], {"path": "/projects"})))
        assert "apex" in [e["name"] for e in payload["entries"]]

    def test_proyecto_fuera_de_la_whitelist(self, handlers, entorno):
        from apex_handlers.vfs import handle_apex_vfs_ls

        texto = _texto(run(handle_apex_vfs_ls(entorno["db"], {"path": "/projects/ajeno/wiki"})))
        assert texto.startswith("ERROR")
        assert "unknown project" in texto

    def test_path_no_virtual(self, handlers, entorno):
        from apex_handlers.vfs import handle_apex_vfs_ls

        texto = _texto(run(handle_apex_vfs_ls(entorno["db"], {"path": "/etc/passwd"})))
        assert texto.startswith("ERROR")
        assert "unknown mount" in texto


# ── apex_vfs_cat ───────────────────────────────────────────────────────


class TestCat:
    def test_devuelve_el_contenido(self, handlers, entorno):
        from apex_handlers.vfs import handle_apex_vfs_cat

        texto = _texto(run(handle_apex_vfs_cat(
            entorno["db"], {"path": "/projects/apex/wiki/a.md"})))
        assert texto == "hola tdd\nmundo\n"

    def test_fichero_inexistente(self, handlers, entorno):
        from apex_handlers.vfs import handle_apex_vfs_cat

        texto = _texto(run(handle_apex_vfs_cat(
            entorno["db"], {"path": "/projects/apex/wiki/no-existe.md"})))
        assert texto.startswith("ERROR")
        assert "not found" in texto

    def test_categoria_virtual(self, handlers, entorno):
        """Las categorías SQL→markdown se sirven como ficheros virtuales."""
        from apex_handlers.vfs import handle_apex_vfs_cat

        texto = _texto(run(handle_apex_vfs_cat(
            entorno["db"], {"path": "/projects/apex/errors/error-1.md"})))
        assert "error sembrado" in texto

    def test_ls_de_una_categoria_virtual(self, handlers, entorno):
        from apex_handlers.vfs import handle_apex_vfs_ls

        payload = _json(run(handle_apex_vfs_ls(
            entorno["db"], {"path": "/projects/apex/errors"})))
        assert "error-1.md" in [e["name"] for e in payload["entries"]]

    def test_lecciones_por_proyecto(self, handlers, entorno):
        """`/lessons/by-project/<slug>.md` agrega las lecciones del hub."""
        from apex_handlers.vfs import handle_apex_vfs_cat

        texto = _texto(run(handle_apex_vfs_cat(
            entorno["db"], {"path": "/lessons/by-project/apex.md"})))
        assert "error del hub" in texto

    def test_lecciones_criticas(self, handlers, entorno):
        from apex_handlers.vfs import handle_apex_vfs_ls

        payload = _json(run(handle_apex_vfs_ls(
            entorno["db"], {"path": "/lessons/critical"})))
        assert payload["entries"], "debería listar las lecciones críticas"

    def test_sin_path(self, handlers, entorno):
        from apex_handlers.vfs import handle_apex_vfs_cat

        texto = _texto(run(handle_apex_vfs_cat(entorno["db"], {})))
        assert texto.startswith("ERROR")


# ── apex_vfs_grep ──────────────────────────────────────────────────────


class TestGrep:
    def test_encuentra_coincidencias(self, handlers, entorno):
        from apex_handlers.vfs import handle_apex_vfs_grep

        texto = _texto(run(handle_apex_vfs_grep(entorno["db"], {
            "pattern": "tdd", "path": "/projects/apex/wiki",
        })))
        assert "/projects/apex/wiki/a.md:hola tdd" in texto

    def test_sin_coincidencias_lo_dice(self, handlers, entorno):
        from apex_handlers.vfs import handle_apex_vfs_grep

        texto = _texto(run(handle_apex_vfs_grep(entorno["db"], {
            "pattern": "zzzz", "path": "/projects/apex/wiki",
        })))
        assert "Sin coincidencias" in texto

    def test_patron_no_traducible_avisa(self, handlers, entorno):
        """Riesgo R2: si el patrón no va a FTS5, se avisa del escaneo completo."""
        from apex_handlers.vfs import handle_apex_vfs_grep

        texto = _texto(run(handle_apex_vfs_grep(entorno["db"], {
            "pattern": "(tdd|mundo)", "path": "/projects/apex/wiki", "flags": "-E",
        })))
        assert "AVISO" in texto
        assert "FTS5" in texto

    def test_flag_de_numero_de_linea(self, handlers, entorno):
        from apex_handlers.vfs import handle_apex_vfs_grep

        texto = _texto(run(handle_apex_vfs_grep(entorno["db"], {
            "pattern": "tdd", "path": "/projects/apex/wiki", "flags": "-n",
        })))
        assert "/projects/apex/wiki/a.md:1:hola tdd" in texto

    def test_sin_pattern(self, handlers, entorno):
        from apex_handlers.vfs import handle_apex_vfs_grep

        texto = _texto(run(handle_apex_vfs_grep(entorno["db"], {"path": "/projects"})))
        assert texto.startswith("ERROR")


# ── apex_vfs_exec ──────────────────────────────────────────────────────


class TestExec:
    def test_devuelve_stdout_stderr_y_exit_code(self, handlers, entorno):
        from apex_handlers.vfs import handle_apex_vfs_exec

        payload = _json(run(handle_apex_vfs_exec(entorno["db"], {
            "command": "ls /projects/apex/wiki",
        })))
        assert set(payload) >= {"stdout", "stderr", "exit_code"}
        assert payload["exit_code"] == 0
        assert "a.md" in payload["stdout"]

    def test_comando_prohibido(self, handlers, entorno):
        from apex_handlers.vfs import handle_apex_vfs_exec

        payload = _json(run(handle_apex_vfs_exec(entorno["db"], {
            "command": "rm -rf /projects",
        })))
        assert payload["exit_code"] == 2
        assert "EROFS" in payload["stderr"]

    def test_inyeccion_rechazada(self, handlers, entorno):
        from apex_handlers.vfs import handle_apex_vfs_exec

        payload = _json(run(handle_apex_vfs_exec(entorno["db"], {
            "command": "cat /projects/apex/wiki/a.md; rm -rf /",
        })))
        assert payload["exit_code"] == 2
        assert payload["stdout"] == ""

    def test_sin_command(self, handlers, entorno):
        from apex_handlers.vfs import handle_apex_vfs_exec

        texto = _texto(run(handle_apex_vfs_exec(entorno["db"], {})))
        assert texto.startswith("ERROR")

    def test_sin_db_de_proyecto(self, handlers, entorno, tmp_path, monkeypatch):
        """El VFS es cross-project: funciona también con `db=None`."""
        from apex_handlers.vfs import handle_apex_vfs_exec

        # Sin proyecto APEX alrededor: la telemetría no tiene dónde ir y la
        # lectura sigue funcionando.
        monkeypatch.chdir(tmp_path)
        payload = _json(run(handle_apex_vfs_exec(None, {
            "command": "ls /projects/apex/wiki",
        })))
        assert payload["exit_code"] == 0
        assert "a.md" in payload["stdout"]


# ── Telemetría y solo-lectura del hub ──────────────────────────────────


class TestTelemetryAndReadOnly:
    def test_registra_las_consultas(self, handlers, entorno):
        from apex_handlers.vfs import handle_apex_vfs_ls

        run(handle_apex_vfs_ls(entorno["db"], {"path": "/projects/apex/wiki"}))
        conn = sqlite3.connect(str(entorno["current_path"]))
        filas = conn.execute(
            "SELECT command, project_slug, hits FROM vfs_query_log"
        ).fetchall()
        conn.close()
        assert filas, "la consulta no se registró en vfs_query_log"
        assert filas[0][0] == "ls /projects/apex/wiki"
        assert filas[0][1] == "apex"
        assert filas[0][2] >= 1

    def test_el_hub_no_se_modifica(self, handlers, entorno):
        """El hub se abre en solo-lectura: ni una byte cambia."""
        from apex_handlers.vfs import handle_apex_vfs_cat, handle_apex_vfs_ls

        antes = hashlib.sha256(entorno["hub"].read_bytes()).hexdigest()
        run(handle_apex_vfs_ls(entorno["db"], {"path": "/projects"}))
        run(handle_apex_vfs_cat(entorno["db"], {"path": "/projects/apex/wiki/a.md"}))
        run(handle_apex_vfs_cat(entorno["db"], {"path": "/lessons/critical"}))
        despues = hashlib.sha256(entorno["hub"].read_bytes()).hexdigest()
        assert antes == despues

    def test_el_cache_de_renders_va_al_proyecto_actual(self, handlers, entorno):
        """El caché se escribe en la context.db del proyecto, no en el hub."""
        from apex_handlers.vfs import handle_apex_vfs_cat

        run(handle_apex_vfs_cat(
            entorno["db"], {"path": "/projects/apex/errors/error-1.md"}))
        conn = sqlite3.connect(str(entorno["current_path"]))
        n = conn.execute("SELECT COUNT(*) FROM vfs_render_cache").fetchone()[0]
        conn.close()
        assert n >= 1
