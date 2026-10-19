"""Una sola resolución de la raíz del proyecto, con el home excluido.

Hasta el 2026-10-19 había 13 copias de esta lógica (6 en `.claude/hooks/`,
6 en `.codex/hooks/`, una en `mcp/apex_server.py`, otra en
`mcp/handlers/_common.py`) y no todas coincidían. La divergenciacales:
una ejecución desde el home resolvía `~/.apex/context.db` —la memoria global
de errores graves— como si fuera el contexto de un proyecto. De ahí que
" Motor Fisico 2D Propio" acabara escrito en la BD global (2026-09-22) y que
la memoria global guardara el estado de `bookmarks-rag` y los logs de sesión
de TFG-SMA-Writer y gti-orienta.

Estos tests fijan la regla: **el home NUNCA es un proyecto**.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from lib.project_root import (  # noqa: E402
    GlobalMemoryError,
    assert_not_global_memory,
    find_project_root,
    is_global_memory,
    project_db_path,
    resolve_project_root,
)


@pytest.fixture
def home(tmp_path, monkeypatch):
    """HOME aislado: un home con un .apex/ de memoria global."""
    h = tmp_path / "home"
    (h / ".apex").mkdir(parents=True)
    (h / ".apex" / "context.db").write_bytes(b"")
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: h))
    return h


@pytest.fixture
def proyecto(tmp_path):
    """Proyecto APEX de verdad: .apex/context.db dentro de un repo."""
    p = tmp_path / "mi-proyecto"
    (p / ".apex").mkdir(parents=True)
    (p / ".apex" / "context.db").write_bytes(b"")
    (p / ".git").mkdir()
    return p


class TestEncuentraElProyecto:
    def test_encuentra_la_raiz_desde_un_subdirectorio(self, proyecto):
        sub = proyecto / "src" / "lib"
        sub.mkdir(parents=True)
        assert find_project_root(sub) == proyecto.resolve()

    def test_encuentra_la_raiz_desde_la_raiz_misma(self, proyecto):
        assert find_project_root(proyecto) == proyecto.resolve()

    def test_usa_el_cwd_por_defecto(self, proyecto, monkeypatch):
        monkeypatch.chdir(proyecto)
        assert find_project_root() == proyecto.resolve()

    def test_un_repo_git_sin_apex_tambien_es_proyecto(self, tmp_path):
        repo = tmp_path / "repo-solo-git"
        (repo / ".git").mkdir(parents=True)
        assert find_project_root(repo) == repo.resolve()

    def test_devuelve_none_sin_proyecto(self, tmp_path):
        huerfano = tmp_path / "huerfano" / "sub"
        huerfano.mkdir(parents=True)
        assert find_project_root(huerfano) is None


class TestElHomeNoEsUnProyecto:
    """La regla que evita escribir en la memoria global."""

    def test_el_home_no_es_proyecto(self, home):
        assert find_project_root(home) is None

    def test_un_subdirectorio_del_home_no_es_proyecto(self, home):
        sub = home / "trabajo" / "cosas"
        sub.mkdir(parents=True)
        assert find_project_root(sub) is None

    def test_el_home_con_apex_no_resuelve_a_la_memoria_global(self, home):
        """El caso que escribió "Motor Fisico 2D Propio" en la BD global."""
        assert find_project_root(home) != home
        assert find_project_root(home / "cualquier" / "cosa") is None

    def test_resolve_project_root_cae_al_cwd_no_al_home(self, home, tmp_path):
        sub = home / "trabajo"
        sub.mkdir()
        resuelto = resolve_project_root(sub)
        assert resuelto != home
        assert resuelto == sub.resolve()

    def test_project_db_path_no_devuelve_la_memoria_global(self, home):
        assert project_db_path(home) is None


class TestMemoriaGlobal:
    def test_reconoce_el_directorio_de_memoria_global(self, home):
        assert is_global_memory(home / ".apex")
        assert is_global_memory(home / ".apex" / "context.db")

    def test_reconoce_un_fichero_dentro(self, home):
        assert is_global_memory(home / ".apex" / "raw" / "nota.md")

    def test_no_confunde_un_proyecto_que_se_llame_apex(self, tmp_path):
        p = tmp_path / "apex"
        (p / ".apex").mkdir(parents=True)
        assert not is_global_memory(p)
        assert not is_global_memory(p / ".apex" / "context.db")

    def test_assert_lanza_en_la_memoria_global(self, home):
        with pytest.raises(GlobalMemoryError):
            assert_not_global_memory(home / ".apex" / "context.db")

    def test_assert_no_lanza_fuera(self, tmp_path):
        assert_not_global_memory(tmp_path / "proyecto" / ".apex" / "context.db")


class TestResolucionPorPath:
    def test_acepta_str(self, proyecto):
        assert find_project_root(str(proyecto)) == proyecto.resolve()

    def test_resuelve_symlinks(self, tmp_path, proyecto):
        link = tmp_path / "enlace"
        link.symlink_to(proyecto)
        assert find_project_root(link) == proyecto.resolve()
