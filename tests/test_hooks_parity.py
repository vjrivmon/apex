"""Paridad: una sola implementación y dos familias de hooks idénticas.

Hasta el 2026-10-19 había 13 copias de "buscar la raíz del proyecto" y dos
juegos de hooks (Claude y Codex) que se habían ido separando. Seis de las
copias de Codex ni siquiera cortaban al llegar al home: desde el home
resolvían `~/.apex/context.db` —la memoria global de errores graves— como
si fuera el contexto de un proyecto.

Estos tests son el whistle de la regla: si alguien vuelve a copiar la
lógica, el suite lo dice.

La comprobación es con AST, no con grep: una función que DELEGA en
`lib.project_root` es correcta; una que vuelve a recorrer los padres, no.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

_CARPETAS = [".claude/hooks", ".codex/hooks"]
_NOMBRES_SOSPECHOSOS = {
    "find_project_root", "_find_project_root",
    "_find_context_db", "project_db_path", "_project_db_path",
}


def _hooks(carpeta: str) -> list[Path]:
    raiz = _REPO / carpeta
    assert raiz.is_dir(), f"{carpeta} no existe"
    return sorted(raiz.glob("*.py"))


def _reimplementa(nodo: ast.FunctionDef) -> bool:
    """¿La función vuelve a recorrer los PADRES en vez de delegar?

    Se miran los bucles cuyo iterable se construye con `*x.parents`: eso
    es exactamente el recorrido que hace `lib/project_root.py`. Un bucle
    sobre otra cosa (las raíces permitidas del VFS, por ejemplo) no es una
    copia de nada.
    """
    for hijo in ast.walk(nodo):
        if not isinstance(hijo, ast.For):
            continue
        for sub in ast.walk(hijo.iter):
            if isinstance(sub, ast.Attribute) and sub.attr == "parents":
                return True
            if isinstance(sub, ast.Starred):
                return True
    return False


class TestUnaSolaImplementacion:
    @pytest.mark.parametrize("carpeta", _CARPETAS)
    def test_ningun_hook_reimplementa_la_resolucion(self, carpeta):
        for hook in _hooks(carpeta):
            arbol = ast.parse(hook.read_text(encoding="utf-8"))
            for nodo in ast.walk(arbol):
                if (isinstance(nodo, ast.FunctionDef)
                        and nodo.name in _NOMBRES_SOSPECHOSOS
                        and _reimplementa(nodo)):
                    raise AssertionError(
                        f"{hook.name}:{nodo.lineno} reimplementa la resolución "
                        f"de la raíz del proyecto en {nodo.name}(): usa "
                        f"lib.project_root (una sola implementación)"
                    )

    @pytest.mark.parametrize("carpeta", _CARPETAS)
    def test_los_hooks_que_resuelven_importan_el_modulo_compartido(self, carpeta):
        for hook in _hooks(carpeta):
            texto = hook.read_text(encoding="utf-8")
            if not any(n in texto for n in _NOMBRES_SOSPECHOSOS):
                continue
            assert "from lib.project_root import" in texto, (
                f"{hook.name} resuelve la raíz del proyecto pero no importa "
                f"lib.project_root"
            )

    def test_no_queda_ninguna_copia_en_el_repo(self):
        """Fuera de lib/project_root.py, nadie reimplementa el recorrido."""
        sospechosos = []
        for ruta in _REPO.rglob("*.py"):
            if "__pycache__" in str(ruta) or ".venv" in str(ruta):
                continue
            if ruta.name == "project_root.py":
                continue
            try:
                arbol = ast.parse(ruta.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue
            for nodo in ast.walk(arbol):
                if (isinstance(nodo, ast.FunctionDef)
                        and nodo.name in _NOMBRES_SOSPECHOSOS
                        and _reimplementa(nodo)):
                    sospechosos.append(f"{ruta.relative_to(_REPO)}:{nodo.lineno}")
        assert not sospechosos, (
            "copias de la resolución de la raíz del proyecto:\n"
            + "\n".join(sospechosos)
        )


class TestLasDosFamiliasCoinciden:
    """El juego de Codex no puede ir por delante del de Claude (ni al revés)."""

    def test_los_mismos_hooks_en_ambos_juegos(self):
        claude = {h.name for h in _hooks(".claude/hooks")}
        codex = {h.name for h in _hooks(".codex/hooks")}
        assert claude == codex, (
            f"solo en Claude: {sorted(claude - codex)}; "
            f"solo en Codex: {sorted(codex - claude)}"
        )

    @pytest.mark.parametrize("nombre", sorted(
        {h.name for h in _hooks(".claude/hooks")} &
        {h.name for h in _hooks(".codex/hooks")}
    ))
    def test_el_contenido_es_identico(self, nombre):
        claude = (_REPO / ".claude" / "hooks" / nombre).read_text(
            encoding="utf-8"
        )
        codex = (_REPO / ".codex" / "hooks" / nombre).read_text(encoding="utf-8")
        assert claude == codex, (
            f"{nombre} difiere entre el juego de Claude y el de Codex: "
            f"antes de que se separaran, eran copias"
        )
