"""Las tools del VFS, del curador y del compactador están registradas.

Tres trabajos paralelos dejaron código escrito sin registrar: el VirtualFS
(Sprint 17), el curador local (Sprint 18) y el compactador de la base de
contexto (`lib/db_compact.py`). Los handlers existían y funcionaban, pero el
agente no podía invocarlos: no estaban en `list_tools()` ni en el dict
`HANDLERS`. Código escrito que nadie puede llamar es código muerto con
intención, que es peor que código muerto y ya está.

Estos tests fijan tres cosas:

1. Las 7 tools existen con su nombre exacto (el nombre es el contrato: si el
   agente lo invoca por ese nombre, tiene que estar).
2. El número de tools declaradas y el de handlers registrados coinciden. Si
   alguien declara una tool y olvida su handler (o al revés), el test lo
   dice: es el olvido que se cuela en las revisiones.
3. El VirtualFS responde SIN que el cwd sea un proyecto APEX. Es su caso de
   uso: navegar el ecosistema desde cualquier sitio. Si el dispatcher
   exigiera un proyecto, la tool quedaría inalcanzable justo donde sirve.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent

#: Nombre de la tool -> (parámetros que el schema declara como requeridos,
#: parámetros que el schema expone con un default).
#: El requerimiento no es decorativo: es lo que el agente tiene que pasar.
TOOLS_NUEVAS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "apex_vfs_exec": (("command",), ()),
    "apex_vfs_ls": ((), ("path",)),
    "apex_vfs_cat": (("path",), ()),
    "apex_vfs_grep": (("pattern",), ("path", "flags")),
    "apex_curator_status": ((), ()),
    "apex_curator_test": (("text",), ("kind", "docs")),
    "apex_db_compact": ((), ("retention_days",)),
}


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.fixture
def apex_server_mod():
    """Carga mcp/apex_server.py sin que el directorio `mcp/` ensombrezca el SDK."""
    root = _REPO
    for p in ("", ".", str(root)):
        while p in sys.path:
            sys.path.remove(p)
    sys.path.insert(0, str(root / "lib"))
    sys.path.append(str(root))
    spec = importlib.util.spec_from_file_location(
        "apex_server", root / "mcp" / "apex_server.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["apex_server"] = mod
    spec.loader.exec_module(mod)
    return mod


def _declaradas(mod) -> dict:
    return {t.name: t for t in run(mod.list_tools())}


# ── Registro ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("nombre", sorted(TOOLS_NUEVAS))
def test_la_tool_esta_declarada_en_list_tools(apex_server_mod, nombre):
    declaradas = _declaradas(apex_server_mod)
    assert nombre in declaradas, (
        f"{nombre} no aparece en list_tools(): el agente no puede invocarla")


@pytest.mark.parametrize("nombre", sorted(TOOLS_NUEVAS))
def test_la_tool_tiene_handler(apex_server_mod, nombre):
    assert nombre in apex_server_mod.HANDLERS, (
        f"{nombre} está declarada pero no tiene handler en HANDLERS")


@pytest.mark.parametrize("nombre", sorted(TOOLS_NUEVAS))
def test_el_schema_declara_los_parametros(apex_server_mod, nombre):
    """Los parámetros del schema son los que el handler realmente lee."""
    tool = _declaradas(apex_server_mod)[nombre]
    requeridos, opcionales = TOOLS_NUEVAS[nombre]
    propiedades = set(tool.inputSchema.get("properties", {}))
    assert set(requeridos) | set(opcionales) <= propiedades, (
        f"{nombre}: el schema expone {sorted(propiedades)}, "
        f"faltan {sorted(set(requeridos) | set(opcionales) - propiedades)}")
    assert set(tool.inputSchema.get("required", [])) == set(requeridos), (
        f"{nombre}: required={sorted(tool.inputSchema.get('required', []))}, "
        f"esperado={sorted(requeridos)}")


def test_toda_tool_declarada_tiene_handler(apex_server_mod):
    """Ninguna tool puede quedarse sin dispatch: sería un 'Unknown tool'."""
    declaradas = set(_declaradas(apex_server_mod))
    registradas = set(apex_server_mod.HANDLERS)
    huerfanas = declaradas - registradas
    assert not huerfanas, (
        f"tools declaradas sin handler (quedan inalcanzables): {sorted(huerfanas)}")


def test_todo_handler_tiene_tool_declarada(apex_server_mod):
    """Y al revés: un handler que nadie ve es código muerto."""
    declaradas = set(_declaradas(apex_server_mod))
    registradas = set(apex_server_mod.HANDLERS)
    muertos = registradas - declaradas
    assert not muertos, (
        f"handlers sin tool declarada (nadie puede llamarlos): {sorted(muertos)}")


def test_el_numero_de_tools_coincide_con_el_de_handlers(apex_server_mod):
    """El recuento de tools y el de handlers son el MISMO número.

    Es el invariante que detecta el olvido: si declaras 64 tools y registras
    63 handlers, alguien se ha dejado una por el camino.
    """
    declaradas = _declaradas(apex_server_mod)
    assert len(declaradas) == len(set(declaradas)), (
        "hay nombres de tool repetidos en list_tools()")
    assert len(declaradas) == len(apex_server_mod.HANDLERS), (
        f"{len(declaradas)} tools declaradas y "
        f"{len(apex_server_mod.HANDLERS)} handlers registrados")


# ── El VFS es cross-project ───────────────────────────────────────────────

def test_el_vfs_se_despacha_sin_db_de_proyecto(apex_server_mod):
    """Las 4 tools del VFS no pueden pasar por `_get_db()`.

    `_get_db()` lanza `NotAnApexProjectError` si el cwd no es un proyecto
    APEX, y el VFS existe justo para consultarse desde fuera de cualquier
    proyecto.
    """
    sin_db = set(apex_server_mod.NO_PROJECT_DB_TOOLS)
    for nombre in ("apex_vfs_exec", "apex_vfs_ls", "apex_vfs_cat", "apex_vfs_grep"):
        assert nombre in sin_db, (
            f"{nombre} se despacha con db de proyecto: no funcionaría fuera "
            f"de un proyecto APEX")


def test_vfs_ls_responde_sin_proyecto_apex(apex_server_mod, tmp_path, monkeypatch):
    """La prueba de fuego: `apex_vfs_ls` desde un directorio sin `.apex/`."""
    fuera = tmp_path / "no-soy-un-proyecto"
    fuera.mkdir()
    monkeypatch.chdir(fuera)
    assert not (fuera / ".apex").exists()

    res = run(apex_server_mod.call_tool("apex_vfs_ls", {"path": "/"}))
    texto = res[0].text

    assert "no es un proyecto APEX" not in texto, (
        f"el VFS pidió un proyecto APEX: {texto}")
    payload = json.loads(texto)
    assert payload["path"] == "/"
    assert isinstance(payload["entries"], list)


def test_vfs_exec_rechaza_un_comando_fuera_de_la_whitelist(apex_server_mod, tmp_path,
                                                            monkeypatch):
    """El exec es una whitelist, no un shell: `rm -rf` no se ejecuta."""
    fuera = tmp_path / "no-soy-un-proyecto-2"
    fuera.mkdir()
    monkeypatch.chdir(fuera)

    res = run(apex_server_mod.call_tool(
        "apex_vfs_exec", {"command": "rm -rf /"}))
    payload = json.loads(res[0].text)
    assert payload["exit_code"] == 2
    assert payload["stdout"] == ""
