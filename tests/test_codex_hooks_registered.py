"""Registro de hooks de Codex: `.codex/hooks.json` frente a `.codex/hooks/`.

Auditoría del 2026-10-19: el registro de Codex estaba incompleto (4 hooks
críticos sin registrar, incluido `phase-gate.py`, que es el write-gate de
`apex_set_phase`) y usaba `$CLAUDE_PROJECT_DIR`, una variable de Claude Code
que Codex no garantiza expandir.

Estos tests leen los ficheros reales del repo: no dependen de la máquina.
"""
from __future__ import annotations

import json
import os
import shlex
import sqlite3
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HOOKS_DIR = REPO / ".codex" / "hooks"
REGISTRY = REPO / ".codex" / "hooks.json"

# Hooks sin los que el flujo de Codex pierde una garantía. Si alguno desaparece
# del registro, el test falla.
CRITICOS = {
    "phase-gate.py",       # write-gate: bloquea apex_set_phase con exit 2
    "advice-injector.py",
    "context-watch.py",
    "session-start.py",
    "pending-notes.py",
}


def _entradas() -> list[dict]:
    """Aplana el registro a una lista de entradas con sus campos."""
    datos = json.loads(REGISTRY.read_text(encoding="utf-8"))
    salida = []
    for evento, grupos in datos.get("hooks", {}).items():
        for grupo in grupos:
            matcher = grupo.get("matcher", "")
            for hook in grupo.get("hooks", []):
                comando = hook.get("command", "")
                tokens = shlex.split(comando)
                interprete = tokens[0] if tokens else ""
                script = tokens[1] if len(tokens) > 1 else ""
                salida.append({
                    "evento": evento,
                    "matcher": matcher,
                    "interprete": interprete,
                    "script": script,
                    "comando": comando,
                })
    return salida


def _nombre_script(script: str) -> str:
    """Nombre del hook a partir de la ruta del script."""
    return Path(script).name if script else ""


def _ruta_relativa_al_repo(ruta: str) -> Path | None:
    """Convierte una ruta absoluta en una relativa al repo.

    Devuelve None si la ruta no apunta al repo, para que el test pueda
    distinguir "ruta inválida" de "fichero que no existe".
    """
    partes = Path(ruta).parts
    for ancla in (".codex", ".claude", "scripts", "lib"):
        if ancla in partes:
            i = partes.index(ancla)
            return Path(*partes[i:])
    return None


def test_registro_es_json_valido():
    datos = json.loads(REGISTRY.read_text(encoding="utf-8"))
    assert "hooks" in datos, "el registro debe tener la clave 'hooks'"
    assert datos["hooks"], "el registro no puede estar vacio"


def test_ningun_hook_esta_huerfano():
    """Todo .py de `.codex/hooks/` debe estar registrado."""
    registrados = {_nombre_script(e["script"]) for e in _entradas()}
    en_disco = {p.name for p in HOOKS_DIR.glob("*.py")}
    huerfanos = en_disco - registrados
    assert not huerfanos, f"hooks sin registrar en .codex/hooks.json: {sorted(huerfanos)}"


def test_ningun_registro_esta_roto():
    """Todo hook registrado debe existir en `.codex/hooks/`."""
    for entrada in _entradas():
        nombre = _nombre_script(entrada["script"])
        assert nombre, f"entrada sin script: {entrada}"
        assert (HOOKS_DIR / nombre).is_file(), (
            f"el registro apunta a un hook inexistente: {entrada['script']}"
        )


def test_phase_gate_registrado_con_su_matcher():
    """El write-gate debe seguir en PreToolUse con su matcher exacto.

    Si alguien lo quita o cambia el matcher, `apex_set_phase` deja de
    bloquearse en Codex: es el fallo que da nombre a este test.
    """
    entradas = [e for e in _entradas() if _nombre_script(e["script"]) == "phase-gate.py"]
    assert entradas, "phase-gate.py no está registrado en .codex/hooks.json"
    assert any(
        e["evento"] == "PreToolUse" and e["matcher"] == "mcp__apex__apex_set_phase"
        for e in entradas
    ), (
        "phase-gate.py debe registrarse en PreToolUse con el matcher "
        "'mcp__apex__apex_set_phase'"
    )


def test_hooks_criticos_registrados():
    registrados = {_nombre_script(e["script"]) for e in _entradas()}
    faltan = CRITICOS - registrados
    assert not faltan, f"hooks críticos sin registrar: {sorted(faltan)}"


def test_ninguna_entrada_usa_claude_project_dir():
    """`$CLAUDE_PROJECT_DIR` es de Claude Code: Codex puede no expandirla."""
    for entrada in _entradas():
        assert "$CLAUDE_PROJECT_DIR" not in entrada["interprete"], (
            f"el interprete usa $CLAUDE_PROJECT_DIR: {entrada['comando']}"
        )


def test_el_registro_no_usa_claude_project_dir():
    """Ninguna referencia a `$CLAUDE_PROJECT_DIR` en todo el fichero."""
    crudo = REGISTRY.read_text(encoding="utf-8")
    assert "$CLAUDE_PROJECT_DIR" not in crudo, (
        "el registro de Codex no debe referenciar $CLAUDE_PROJECT_DIR"
    )


def test_las_rutas_son_absolutas():
    """Interprete y script con ruta absoluta: portables entre shells."""
    for entrada in _entradas():
        assert entrada["interprete"].startswith("/"), (
            f"el interprete no es absoluto: {entrada['interprete']}"
        )
        assert entrada["script"].startswith("/"), (
            f"el script no tiene ruta absoluta: {entrada['script']}"
        )


def test_los_scripts_apuntan_al_repo():
    """Cada script registrado vive en el repo (o en un directorio suyo)."""
    for entrada in _entradas():
        relativa = _ruta_relativa_al_repo(entrada["script"])
        assert relativa is not None, (
            f"el script no cuelga del repo: {entrada['script']}"
        )
        assert (REPO / relativa).is_file(), (
            f"el script no existe en el repo: {entrada['script']}"
        )


# --- Equivalencia de pending-notes entre los dos juegos de hooks ------------


def _preparar_pendientes(base: Path) -> None:
    """Crea un proyecto APEX con una nota de pendientes y su vault."""
    root = base / "Mi Proyecto"
    (root / ".apex").mkdir(parents=True)
    con = sqlite3.connect(root / ".apex" / "context.db")
    con.execute(
        "CREATE TABLE project_meta (key TEXT PRIMARY KEY, value TEXT, "
        "updated_at TEXT DEFAULT (datetime('now')))"
    )
    con.commit()
    con.close()
    vault = base / "vault"
    nota = vault / "projects" / "mi-proyecto" / "pendientes.md"
    nota.parent.mkdir(parents=True)
    nota.write_text(
        "# Pendientes\n\n- [ ] Añadir exportación a CSV\n  - solo la tabla\n",
        encoding="utf-8",
    )


def _correr(hook: Path, base: Path) -> str:
    env = {**os.environ, "HOME": str(base / "home"), "APEX_VAULT_DIR": str(base / "vault")}
    (base / "home").mkdir(exist_ok=True)
    out = subprocess.run(
        [sys.executable, str(hook)],
        input=json.dumps({"cwd": str(base / "Mi Proyecto")}),
        capture_output=True,
        text=True,
        env=env,
        timeout=20,
    )
    assert out.returncode == 0, out.stderr
    return out.stdout


def test_pending_notes_de_codex_es_equivalente_al_de_claude(tmp_path):
    """La copia de Codex debe comportarse igual que la de Claude.

    Si divergen, los pendientes de Obsidian se inyectan distinto según el
    cliente: el mismo hook en dos versiones no es mantenible.
    """
    base_claude = tmp_path / "claude"
    base_codex = tmp_path / "codex"
    for base in (base_claude, base_codex):
        base.mkdir()
        _preparar_pendientes(base)

    salida_claude = _correr(REPO / ".claude" / "hooks" / "pending-notes.py", base_claude)
    salida_codex = _correr(REPO / ".codex" / "hooks" / "pending-notes.py", base_codex)

    assert salida_claude.strip(), "el hook de Claude no inyectó nada"
    # Se normaliza la ruta base: cada copia corre en su propio tmp_path y el
    # vault aparece en el texto inyectado.
    assert salida_codex.replace(str(base_codex), "<BASE>") == \
        salida_claude.replace(str(base_claude), "<BASE>"), \
        "los dos hooks de pending-notes divergen"
    assert "Añadir exportación a CSV" in salida_codex
