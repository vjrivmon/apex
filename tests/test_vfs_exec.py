"""Sprint 17 S17.7 — exec del VirtualFS: whitelist de comandos y EROFS.

Riesgo R3 del blueprint: un parser de comandos mal hecho es un agujero de
inyección. Aquí se comprueba que el parser rechaza TODO lo que no está en
la whitelist (`rm`, `curl`, `python`, `;`, `&&`, backticks, `$(...)`) y que
el VirtualFS es read-only (cualquier escritura devuelve EROFS).
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from vfs import (  # noqa: E402
    EROFS_MESSAGE,
    VFSExecError,
    VFSPathError,
    VFSWriteError,
    VirtualFS,
    parse_exec_command,
    run_exec,
)


@pytest.fixture
def project_root(tmp_path):
    root = tmp_path / "RoadToDevOps"
    wiki = root / "apex" / "wiki"
    wiki.mkdir(parents=True)
    (wiki / "a.md").write_text("hola tdd\nmundo\n")
    (wiki / "b.md").write_text("otra cosa\ntdd otra vez\n")
    (root / "otro" / "wiki").mkdir(parents=True)
    (root / "otro" / "wiki" / "c.md").write_text("contenido de otro\n")
    return root


@pytest.fixture
def vfs(project_root):
    return VirtualFS(allowed_roots=[project_root])


# ── Whitelist de comandos ───────────────────────────────────────────────


class TestCommandWhitelist:
    @pytest.mark.parametrize("comando", [
        "ls /projects/apex/wiki",
        "cat /projects/apex/wiki/a.md",
        "grep tdd /projects/apex/wiki",
        "find /projects/apex/wiki",
    ])
    def test_comandos_permitidos(self, comando):
        plan = parse_exec_command(comando)
        assert plan.name in ("ls", "cat", "grep", "find")

    @pytest.mark.parametrize("comando", [
        "rm -rf /projects",
        "curl http://example.com",
        "python -c 'import os'",
        "wget http://x",
        "bash -c 'ls'",
        "chmod 777 /projects",
    ])
    def test_comandos_no_permitidos(self, comando):
        with pytest.raises(VFSExecError, match="no permitido"):
            parse_exec_command(comando)

    @pytest.mark.parametrize("comando", [
        "cat /projects/apex/wiki/a.md; rm -rf /",
        "ls /projects && cat /etc/passwd",
        "ls /projects || cat /etc/passwd",
        "cat `whoami`",
        "cat $(whoami)",
        "cat /projects > /tmp/salida",
        "cat < /etc/passwd",
        "ls (subshell)",
        "ls {curly}",
    ])
    def test_inyeccion_rechazada(self, comando):
        """Nada de `;`, `&&`, backticks, `$(...)` ni redirecciones."""
        with pytest.raises(VFSExecError):
            parse_exec_command(comando)

    def test_comando_vacio(self):
        with pytest.raises(VFSExecError, match="vacío"):
            parse_exec_command("   ")

    def test_comando_de_multilinea(self):
        with pytest.raises(VFSExecError):
            parse_exec_command("ls /projects\nrm -rf /")

    def test_comillas_sin_cerrar(self):
        with pytest.raises(VFSExecError):
            parse_exec_command("grep 'sin cerrar /projects")

    def test_path_relativo_rechazado(self):
        with pytest.raises(VFSExecError, match="absoluto"):
            parse_exec_command("cat projects/apex/wiki/a.md")

    def test_traversal_rechazado(self):
        with pytest.raises(VFSExecError, match="traversal"):
            parse_exec_command("cat /projects/apex/../../etc/passwd")

    def test_flag_no_permitido(self):
        with pytest.raises(VFSExecError, match="flag"):
            parse_exec_command("grep -Z tdd /projects/apex/wiki")

    def test_grep_necesita_patron_y_path(self):
        with pytest.raises(VFSExecError):
            parse_exec_command("grep tdd")

    def test_cat_necesita_path(self):
        with pytest.raises(VFSExecError):
            parse_exec_command("cat")

    def test_find_solo_admite_name(self):
        with pytest.raises(VFSExecError, match="-name"):
            parse_exec_command("find /projects/apex/wiki -iname '*.md'")


class TestPipeWhitelist:
    def test_filtros_permitidos(self):
        plan = parse_exec_command(
            "ls /projects/apex/wiki | grep md | head -n 2 | wc -l"
        )
        assert [f.kind for f in plan.filters] == ["grep", "head", "wc"]

    def test_filtro_no_permitido(self):
        with pytest.raises(VFSExecError, match="filtro no permitido"):
            parse_exec_command("ls /projects | tee /tmp/x")

    def test_pipe_vacio(self):
        with pytest.raises(VFSExecError, match="pipe vacío"):
            parse_exec_command("ls /projects | ")

    def test_head_solo_admite_n(self):
        with pytest.raises(VFSExecError, match="head"):
            parse_exec_command("ls /projects | head -c 10")

    def test_wc_solo_admite_l(self):
        with pytest.raises(VFSExecError, match="wc"):
            parse_exec_command("ls /projects | wc -w")


# ── Ejecución ───────────────────────────────────────────────────────────


class TestExec:
    def test_ls(self, vfs):
        result = run_exec(vfs, "ls /projects/apex/wiki")
        assert result.exit_code == 0
        assert "a.md" in result.stdout
        assert "b.md" in result.stdout
        assert result.stderr == ""

    def test_cat(self, vfs):
        result = run_exec(vfs, "cat /projects/apex/wiki/a.md")
        assert result.exit_code == 0
        assert result.stdout == "hola tdd\nmundo\n"

    def test_grep(self, vfs):
        result = run_exec(vfs, "grep tdd /projects/apex/wiki")
        assert result.exit_code == 0
        assert "/projects/apex/wiki/a.md:hola tdd" in result.stdout

    def test_grep_sin_coincidencias_devuelve_1(self, vfs):
        result = run_exec(vfs, "grep zzzz /projects/apex/wiki")
        assert result.exit_code == 1
        assert result.stdout == ""

    def test_find(self, vfs):
        result = run_exec(vfs, "find /projects/apex/wiki -name '*.md'")
        assert result.exit_code == 0
        assert "/projects/apex/wiki/a.md" in result.stdout

    def test_pipe_grep(self, vfs):
        result = run_exec(vfs, "ls /projects/apex/wiki | grep b.md")
        assert result.exit_code == 0
        assert result.stdout.strip() == "b.md"

    def test_pipe_head(self, vfs):
        result = run_exec(vfs, "ls /projects/apex/wiki | head -n 1")
        assert result.exit_code == 0
        assert len(result.stdout.strip().splitlines()) == 1

    def test_pipe_wc_l(self, vfs):
        result = run_exec(vfs, "ls /projects/apex/wiki | wc -l")
        assert result.exit_code == 0
        assert result.stdout.strip() == "2"

    def test_comando_rechazado_devuelve_2(self, vfs):
        result = run_exec(vfs, "rm -rf /projects")
        assert result.exit_code == 2
        assert result.stdout == ""
        assert "no permitido" in result.stderr

    def test_error_de_filesystem_devuelve_1(self, vfs):
        result = run_exec(vfs, "cat /projects/apex/wiki/no-existe.md")
        assert result.exit_code == 1
        assert "not found" in result.stderr

    def test_path_fuera_de_las_raices(self, vfs):
        """La sandbox del resolver sigue vigente a través del exec."""
        result = run_exec(vfs, "cat /etc/passwd")
        assert result.exit_code == 1
        assert "unknown mount" in result.stderr


# ── Read-only (EROFS) ───────────────────────────────────────────────────


class TestReadOnly:
    def test_write_devuelve_erofs(self, vfs):
        with pytest.raises(VFSWriteError) as exc:
            vfs.write("/projects/apex/wiki/a.md", "contenido")
        assert EROFS_MESSAGE in str(exc.value)

    def test_comandos_de_escritura_dicen_erofs(self, vfs):
        for comando in ("rm x", "mv a b", "touch f", "echo hola > f"):
            result = run_exec(vfs, comando)
            assert result.exit_code == 2
            assert EROFS_MESSAGE in result.stderr, comando

    def test_el_vfs_no_tiene_metodos_de_escritura(self, vfs):
        """Solo `write` existe, y solo para fallar con EROFS."""
        assert not hasattr(vfs, "mkdir")
        assert not hasattr(vfs, "unlink")
        assert not hasattr(vfs, "rm")
        assert not hasattr(vfs, "put")


# ── Sandbox de rutas ────────────────────────────────────────────────────


class TestPathWhitelist:
    def test_proyecto_fuera_de_las_raices(self, vfs):
        with pytest.raises(VFSPathError, match="unknown project"):
            vfs._resolve("/projects/ajeno/wiki/a.md")

    def test_vault_no_configurado(self, project_root):
        vfs = VirtualFS(allowed_roots=[project_root])
        with pytest.raises(VFSPathError, match="vault"):
            vfs._resolve("/vault/index.md")

    def test_la_memoria_global_no_es_un_proyecto(self, tmp_path, monkeypatch):
        """`~/.apex` es memoria global: nunca un proyecto alcanzable."""
        home = tmp_path / "home"
        (home / ".apex").mkdir(parents=True)
        monkeypatch.setenv("HOME", str(home))
        with pytest.raises(VFSPathError, match="memoria global"):
            VirtualFS(allowed_roots=[home / ".apex"])

    def test_la_memoria_global_no_se_resuelve_como_proyecto(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        (home / ".apex" / "wiki").mkdir(parents=True)
        monkeypatch.setenv("HOME", str(home))
        vfs = VirtualFS(allowed_roots=[home])
        with pytest.raises(VFSPathError):
            vfs._resolve("/projects/.apex/wiki/secret.md")
