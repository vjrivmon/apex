"""Contención de rutas del wiki y de la ingesta (capa L1: F1-03 y F1-04).

Dos fallos reales del gate AgentArmor, ambos de path traversal:

- **F1-03**: `apex_wiki_add` concatenaba el slug del caller tal cual
  (`.apex/wiki/<slug>.md`), así que un slug con `..` escribía FUERA del
  proyecto.
- **F1-04**: `apex_ingest_source` aceptaba cualquier ruta absoluta del
  filesystem, así que la ingesta leía (y podía reescribir) lo que hubiera
  fuera del proyecto.

Aquí se comprueba que:
- un slug con `..`, con `/` no permitido, con `..` en medio o con caracteres
  de control se RECHAZA, y no queda ningún fichero fuera del proyecto;
- un slug legítimo se acepta y se normaliza;
- la ingesta acepta rutas dentro del proyecto y rechaza las de fuera,
  incluidos los symlinks que apuntan fuera.
"""
from __future__ import annotations

import asyncio
import importlib.util
import shutil
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO / "lib") not in sys.path:
    sys.path.insert(0, str(_REPO / "lib"))
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from wiki_scaffold import (  # noqa: E402
    WikiPathError,
    append_log,
    create_wiki,
    sanitize_slug,
    update_index,
    wiki_page_path,
)


# --- Infraestructura de los tests -------------------------------------------

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
    anterior = sys.modules.get("apex_handlers")
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
        # El submódulo puede venir cacheado de otro fichero de tests (el
        # paquete no siempre queda registrado como atributo), así que se
        # importa explícitamente.
        mod.wiki = importlib.import_module("apex_handlers.wiki")
    finally:
        sys.path[:] = original
    yield mod
    if anterior is None:
        sys.modules.pop("apex_handlers", None)
    else:
        sys.modules["apex_handlers"] = anterior


class DbFalsa:
    """Sustituto de ApexContextDB: solo registra lo que se le pide guardar."""

    def __init__(self) -> None:
        self.paginas: list[tuple] = []

    async def add_wiki_page(self, slug, title, content, page_type="entity",
                            tags=None, wikilinks=None) -> None:
        self.paginas.append((slug, title, content, page_type, tags))


@pytest.fixture
def proyecto(tmp_path):
    """Proyecto APEX sintético con el wiki ya creado."""
    root = tmp_path / "proyecto"
    create_wiki(root, "proyecto")
    return root


@pytest.fixture
def wiki(proyecto):
    return proyecto / ".apex" / "wiki"


@pytest.fixture
def wiki_add(handlers, proyecto, monkeypatch):
    """`apex_wiki_add` apuntando a un proyecto temporal."""
    monkeypatch.setattr(handlers.wiki, "_find_project_root", lambda: proyecto)
    db = DbFalsa()

    def _add(slug, **kwargs):
        argumentos = {"slug": slug, "title": "T", "content": "C"}
        argumentos.update(kwargs)
        return run(handlers.wiki.handle_apex_wiki_add(db, argumentos)), db

    return _add


@pytest.fixture
def ingest(handlers, proyecto, monkeypatch):
    """`apex_ingest_source` apuntando a un proyecto temporal."""
    monkeypatch.setattr(handlers.wiki, "_find_project_root", lambda: proyecto)

    def _ingest(path, **kwargs):
        argumentos = {"path": str(path)}
        argumentos.update(kwargs)
        return run(handlers.wiki.handle_apex_ingest_source(DbFalsa(), argumentos))

    return _ingest


def ficheros_fuera_de(root: Path) -> list[Path]:
    """Ficheros que han aparecido por encima de `root` (fuera del proyecto)."""
    return [p for p in root.parent.rglob("*") if p.is_file() and root not in p.parents]


# --- F1-03: el slug no sale del proyecto -------------------------------------

def test_slug_con_traversal_se_rechaza(wiki_add, proyecto):
    """`../../etc/pwned` no se acepta y no escribe nada fuera del proyecto."""
    resultado, db = wiki_add("../../etc/pwned")
    texto = resultado[0].text

    assert "ERROR" in texto, texto
    assert db.paginas == [], "un slug inválido no debe llegar a la BD"
    assert not (proyecto / "etc" / "pwned.md").exists()
    assert not (proyecto.parent / "etc" / "pwned.md").exists()
    assert not (proyecto.parent / "pwned.md").exists()


@pytest.mark.parametrize("slug", [
    "foo/bar",            # sección que no existe
    "a/b/c",              # demasiados separadores
    "/absoluto",          # ruta absoluta
    "seccion/",           # segmento vacío al final
    "/seccion/x",         # segmento vacío al principio
    "concepts//x",        # segmento vacío en medio
])
def test_slug_con_separador_no_permitido_se_rechaza(wiki_add, slug, proyecto):
    resultado, db = wiki_add(slug)
    texto = resultado[0].text

    assert "ERROR" in texto, texto
    assert db.paginas == []
    assert ficheros_fuera_de(proyecto) == []


@pytest.mark.parametrize("slug", [
    "arqui..tectura",     # '..' en medio
    "concepts/..",        # '..' como último segmento
    "..",                 # solo '..'
    "..hidden",
])
def test_slug_con_doble_punto_en_medio_se_rechaza(wiki_add, slug, proyecto):
    resultado, db = wiki_add(slug)
    texto = resultado[0].text

    assert "ERROR" in texto, texto
    assert db.paginas == []
    assert ficheros_fuera_de(proyecto) == []


@pytest.mark.parametrize("slug", [
    "concepto\x00x",      # NUL
    "concepto\nx",        # salto de línea
    "concepto\x1bx",      # escape
    "concepto\tx",
])
def test_slug_con_caracteres_de_control_se_rechaza(wiki_add, slug, proyecto):
    resultado, db = wiki_add(slug)
    texto = resultado[0].text

    assert "ERROR" in texto, texto
    assert db.paginas == []
    assert ficheros_fuera_de(proyecto) == []


def test_slug_legitimo_se_acepta_y_se_normaliza(wiki_add, wiki):
    """Los slugs de verdad del repo siguen funcionando; los espacios se normalizan."""
    resultado, db = wiki_add("arquitectura del sistema")
    assert "ERROR" not in resultado[0].text, resultado[0].text
    assert (wiki / "arquitectura-del-sistema.md").exists()
    assert db.paginas[0][0] == "arquitectura-del-sistema"

    # Un slug de una sola palabra conserva mayúsculas (SCHEMA.md existe).
    resultado, _ = wiki_add("SCHEMA")
    assert "ERROR" not in resultado[0].text
    assert (wiki / "SCHEMA.md").exists()

    # El formato con sección es el que documenta el schema de la tool.
    resultado, _ = wiki_add("concepts/design-system")
    assert "ERROR" not in resultado[0].text
    assert (wiki / "concepts" / "design-system.md").exists()


def test_el_error_dice_que_se_esperaba(wiki_add):
    """El mensaje de error explica el formato esperado, no sólo 'error'."""
    resultado, _ = wiki_add("../../etc/pwned")
    texto = resultado[0].text

    assert "ERROR" in texto
    assert ".." in texto, texto
    assert "identificador" in texto, texto


def test_sanitize_slug_devuelve_el_slug_normalizado():
    assert sanitize_slug("arquitectura del sistema") == "arquitectura-del-sistema"
    assert sanitize_slug("SCHEMA") == "SCHEMA"
    assert sanitize_slug("concepts/design-system") == "concepts/design-system"
    assert sanitize_slug("  con espacios  ") == "con-espacios"


@pytest.mark.parametrize("slug", [
    "../../etc/pwned", "foo/bar", "a/b/c", "/absoluto", "arqui..tectura",
    "concepto\x00x", "con\\cepto", "",
])
def test_sanitize_slug_rechaza_lo_invalido(slug):
    with pytest.raises(WikiPathError):
        sanitize_slug(slug)


def test_wiki_page_path_no_sale_del_wiki(wiki):
    """La ruta resuelta de la página se queda dentro de `.apex/wiki/`."""
    ruta = wiki_page_path(wiki, "concepts/design-system")
    assert ruta.resolve().is_relative_to(wiki.resolve())

    with pytest.raises(WikiPathError):
        wiki_page_path(wiki, "../../../etc/pwned")


def test_log_e_indice_no_se_escriben_fuera_del_proyecto(tmp_path):
    """`append_log`/`update_index` exigen un wiki de proyecto (`.apex/wiki`)."""
    with pytest.raises(WikiPathError):
        append_log(tmp_path / "cualquier-cosa", "accion")
    with pytest.raises(WikiPathError):
        update_index(tmp_path / "cualquier-cosa")
    assert list(tmp_path.iterdir()) == []


def test_wiki_que_es_un_symlink_fuera_del_proyecto_se_rechaza(wiki_add, proyecto, tmp_path):
    """Si `.apex/wiki` apunta fuera del proyecto, la página se rechaza."""
    fuera = tmp_path / "fuera"
    fuera.mkdir()
    wiki_real = proyecto / ".apex" / "wiki"
    shutil.rmtree(wiki_real)
    wiki_real.symlink_to(fuera)

    resultado, db = wiki_add("arquitectura")
    texto = resultado[0].text

    assert "ERROR" in texto, texto
    assert db.paginas == []
    assert list(fuera.iterdir()) == [], "no debe escribirse nada fuera del proyecto"


def test_tras_un_intento_de_traversal_no_queda_fichero_fuera(wiki_add, proyecto, tmp_path):
    """Tras varios intentos de traversal, el árbol de ficheros está intacto."""
    antes = sorted(p.relative_to(proyecto) for p in proyecto.rglob("*"))

    for slug in ("../../etc/pwned", "..%2F..%2Fetc/pwned", "concepts/../../pwned",
                 "/tmp/pwned", "..\\..\\pwned"):
        wiki_add(slug)

    despues = sorted(p.relative_to(proyecto) for p in proyecto.rglob("*"))
    assert despues == antes, "no debería aparecer ningún fichero nuevo"
    assert ficheros_fuera_de(proyecto) == []


# --- F1-04: la ingesta no lee fuera del proyecto ----------------------------

def test_ingesta_fuera_del_proyecto_se_rechaza(ingest, proyecto):
    """Una ruta absoluta fuera del proyecto no se ingiere."""
    resultado = ingest("/etc/passwd")
    texto = resultado[0].text

    assert "ERROR" in texto, texto
    assert "fuera del proyecto" in texto, texto
    assert str(proyecto) in texto, "el error debe decir qué rutas se permiten"


def test_ingesta_fuera_con_ruta_relativa_se_rechaza(ingest, proyecto):
    """Una ruta relativa con `..` tampoco sale del proyecto."""
    resultado = ingest("../../etc/passwd")
    texto = resultado[0].text

    assert "ERROR" in texto, texto
    assert "fuera del proyecto" in texto, texto


def test_symlink_hacia_fuera_se_rechaza(ingest, proyecto):
    """Un symlink dentro del proyecto que apunta fuera se rechaza."""
    enlace = proyecto / ".apex" / "raw" / "enlace.md"
    enlace.symlink_to("/etc/passwd")

    resultado = ingest(enlace)
    texto = resultado[0].text

    assert "ERROR" in texto, texto
    assert "fuera del proyecto" in texto, texto


def test_ingesta_dentro_del_proyecto_se_acepta(ingest, proyecto, wiki):
    """La ingesta de `.apex/raw/` sigue funcionando."""
    nota = proyecto / ".apex" / "raw" / "research" / "nota.md"
    nota.write_text("# Nota de prueba\n\nContenido con un enlace https://example.com\n",
                    encoding="utf-8")

    resultado = ingest(".apex/raw/research/nota.md")
    texto = resultado[0].text

    assert "ERROR" not in texto, texto
    assert "Ingestado" in texto, texto
    assert list(wiki.glob("entities/*.md")) or list(wiki.glob("concepts/*.md"))


def test_ingesta_de_directorio_ignora_symlinks_fuera(ingest, proyecto, wiki):
    """Al ingerir un directorio, un symlink que apunta fuera no se lee."""
    (proyecto / ".apex" / "raw" / "research" / "nota.md").write_text(
        "# Nota\n\nContenido propio.\n", encoding="utf-8")
    (proyecto / ".apex" / "raw" / "research" / "fuera.md").symlink_to("/etc/passwd")

    resultado = ingest(".apex/raw/research")
    texto = resultado[0].text

    assert "ERROR" not in texto, texto
    assert "fuera.md" not in texto, "el symlink fuera no debe ingerirse"
    assert "nota.md" in texto
