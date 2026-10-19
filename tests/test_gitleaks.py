"""Tests de lib/gitleaks.py — ejecución del binario gitleaks (Sprint 19, Gap F).

Nada de red: el binario de gitleaks es un script falso en un tmp_path que se
 mete en el PATH con monkeypatch.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import gitleaks as gl  # noqa: E402


# --- helpers ---------------------------------------------------------------

def _fake_bin(tmp_path: Path, body: str, name: str = "gitleaks") -> Path:
    """Crea un binario falso ejecutable y devuelve su directorio."""
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    exe = bin_dir / name
    exe.write_text(body, encoding="utf-8")
    exe.chmod(0o755)
    return bin_dir


def _only_path(monkeypatch: pytest.MonkeyPatch, bin_dir: Path) -> None:
    """Deja el PATH con un único directorio (el del binario falso)."""
    monkeypatch.setenv("PATH", str(bin_dir))


# --- detección del binario -------------------------------------------------

def test_binario_ausente_no_disponible(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _only_path(monkeypatch, tmp_path / "vacio")
    assert gl.gitleaks_binary() is None
    assert gl.is_available() is False


def test_binario_presente_detectado(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    bin_dir = _fake_bin(tmp_path, "#!/bin/sh\nexit 0\n")
    _only_path(monkeypatch, bin_dir)
    assert gl.is_available() is True
    assert gl.gitleaks_binary() == str(bin_dir / "gitleaks")


def test_ejecucion_sin_binario_no_pasa(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Sin gitleaks no se puede afirmar que no hay secretos: ok=False."""
    _only_path(monkeypatch, tmp_path / "vacio")
    result = gl.run_gitleaks(tmp_path)
    assert result.available is False
    assert result.ok is False
    assert result.error is not None
    assert "gitleaks" in result.error


# --- ejecución -------------------------------------------------------------

def test_protect_staged_ok(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    bin_dir = _fake_bin(
        tmp_path, "#!/bin/sh\necho 'escaneado ok'\nexit 0\n")
    _only_path(monkeypatch, bin_dir)
    result = gl.protect_staged(tmp_path)
    assert result.available is True
    assert result.ok is True
    assert result.returncode == 0
    assert "escaneado ok" in result.stdout
    assert result.command[1:] == ["protect", "--staged", "--redact"]


def test_protect_staged_detecta_secreto(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    bin_dir = _fake_bin(
        tmp_path, "#!/bin/sh\necho 'secret found' >&2\nexit 1\n")
    _only_path(monkeypatch, bin_dir)
    result = gl.protect_staged(tmp_path)
    assert result.ok is False
    assert result.returncode == 1
    assert "secret found" in result.stderr
    assert "fallos" in result.summary


def test_timeout_corta_la_ejecucion(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # /bin/sleep con ruta absoluta: el PATH del test solo tiene el binario falso.
    bin_dir = _fake_bin(tmp_path, "#!/bin/sh\n/bin/sleep 5\n")
    _only_path(monkeypatch, bin_dir)
    result = gl.protect_staged(tmp_path, timeout=0.5)
    assert result.timed_out is True
    assert result.ok is False
    assert result.error is not None


def test_no_usa_shell_true(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """La invocación es una lista de args, sin intérprete de shell."""
    captured: dict = {}
    real_run = subprocess.run

    def _fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured.update(kwargs)
        return real_run(["true"], capture_output=True, text=True, timeout=5)

    monkeypatch.setattr(gl.subprocess, "run", _fake_run)
    gl.run_gitleaks(tmp_path, args=["protect"], binary="/bin/true")

    assert captured["shell"] is False
    assert isinstance(captured["cmd"], list)
    assert captured["cmd"] == ["/bin/true", "protect"]


def test_ejecuta_en_el_cwd_indicado(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    captured: dict = {}
    real_run = subprocess.run

    def _fake_run(cmd, **kwargs):
        captured.update(kwargs)
        return real_run(["true"], capture_output=True, text=True, timeout=5)

    monkeypatch.setattr(gl.subprocess, "run", _fake_run)
    workdir = tmp_path / "sub" / "proyecto"
    workdir.mkdir(parents=True)
    gl.run_gitleaks(workdir, binary="/bin/true")
    assert captured["cwd"] == str(workdir)


# --- configuración ---------------------------------------------------------

def test_is_configured_con_hook(tmp_path: Path):
    hook = tmp_path / ".husky" / "pre-commit"
    hook.parent.mkdir(parents=True)
    hook.write_text("#!/bin/sh\n", encoding="utf-8")
    assert gl.is_configured(tmp_path) is True


def test_is_configured_sin_nada(tmp_path: Path):
    assert gl.is_configured(tmp_path) is False


def test_is_configured_con_gitleaks_toml(tmp_path: Path):
    (tmp_path / ".gitleaks.toml").write_text("[extend]\n", encoding="utf-8")
    assert gl.is_configured(tmp_path) is True


# --- plantilla del hook ----------------------------------------------------

def test_plantilla_hook_contiene_gitleaks():
    template = Path(__file__).resolve().parent.parent / "templates" / "devops" / ".husky" / "pre-commit"
    text = template.read_text(encoding="utf-8")
    assert text.startswith("#!")
    assert "gitleaks protect --staged --redact" in text


# --- instalación por apex_scaffold_devops ----------------------------------

def _opts(target: Path, **kwargs):
    from scaffold_devops import ScaffoldOptions
    return ScaffoldOptions(target=target, project_name="demo", **kwargs)


def test_scaffold_instala_el_hook_con_permiso_de_ejecucion(tmp_path: Path):
    from scaffold_devops import scaffold
    report = scaffold(_opts(tmp_path))
    hook = tmp_path / ".husky" / "pre-commit"
    assert hook.exists()
    assert hook.stat().st_mode & 0o111
    assert "gitleaks protect --staged --redact" in hook.read_text(encoding="utf-8")
    assert hook in report.copied


def test_scaffold_no_pisa_un_hook_existente(tmp_path: Path):
    from scaffold_devops import scaffold
    hook = tmp_path / ".husky" / "pre-commit"
    hook.parent.mkdir(parents=True)
    hook.write_text("#!/bin/sh\n# hook del proyecto\n", encoding="utf-8")

    report = scaffold(_opts(tmp_path))
    assert hook.read_text(encoding="utf-8") == "#!/bin/sh\n# hook del proyecto\n"
    assert hook in report.skipped


def test_scaffold_overwrite_sustituye_el_hook(tmp_path: Path):
    from scaffold_devops import scaffold
    hook = tmp_path / ".husky" / "pre-commit"
    hook.parent.mkdir(parents=True)
    hook.write_text("#!/bin/sh\n# hook del proyecto\n", encoding="utf-8")

    scaffold(_opts(tmp_path, overwrite=True))
    assert "gitleaks protect --staged --redact" in hook.read_text(encoding="utf-8")


def test_scaffold_es_idempotente(tmp_path: Path):
    from scaffold_devops import scaffold
    scaffold(_opts(tmp_path))
    first = (tmp_path / ".husky" / "pre-commit").read_bytes()
    report = scaffold(_opts(tmp_path))
    assert (tmp_path / ".husky" / "pre-commit").read_bytes() == first
    assert (tmp_path / ".husky" / "pre-commit") in report.skipped


def test_scaffold_instala_los_slash_commands(tmp_path: Path):
    from scaffold_devops import scaffold
    scaffold(_opts(tmp_path, with_commands=True))
    for name in ("apex-decision", "apex-error", "apex-component", "apex-search"):
        assert (tmp_path / ".claude" / "commands" / f"{name}.md").exists()


def test_scaffold_no_instala_comandos_sin_pedirlos(tmp_path: Path):
    from scaffold_devops import scaffold
    scaffold(_opts(tmp_path))
    assert not (tmp_path / ".claude" / "commands").exists()
