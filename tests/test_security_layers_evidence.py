"""Test de la evidencia de las 8 capas AgentArmor.

Comprueba, sobre los ficheros reales de `.apex/security/`, que:

1. Los 8 ficheros L1..L8 existen y su frontmatter YAML es parseable y
   tiene las claves que `lib/security_gate.py` lee.
2. El `status` de cada capa está en el conjunto de valores que el gate
   acepta.
3. Cada referencia `fichero:línea` de la evidencia apunta a un fichero
   que EXISTE y a una línea que está dentro del rango del fichero.
4. Ninguna capa afirma un número de tools MCP con un valor literal
   desactualizado.

El punto 3 es el que muerde: si alguien mueve una función y deja
colgando una referencia `lib/foo.py:120`, el test falla. Por eso el
regex solo acepta rutas relativas a la raíz del repo, con extensión
conocida y sin comodines.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SECURITY_DIR = REPO_ROOT / ".apex" / "security"

LAYERS = [
    ("L1", "ingestion"),
    ("L2", "storage"),
    ("L3", "context"),
    ("L4", "planning"),
    ("L5", "execution"),
    ("L6", "output"),
    ("L7", "inter-agent"),
    ("L8", "identity"),
]

# Claves que el gate lee del frontmatter (lib/security_gate.py).
REQUIRED_KEYS = ("layer", "title", "status", "asi_coverage", "evidence")

# Valores de status que el gate entiende. La plantilla de la fase 10.5
# documenta `passed|partial|pending|missing` y el docstring del gate
# `passed | pending | failed`. Aceptamos la union: lo que importa es que
# el status sea uno de los vocabularios del gate, no un string libre.
DOCUMENTED_STATUSES = {"passed", "partial", "pending", "failed", "missing"}

# Referencias `ruta.ext:linea` o `ruta.ext:linea-linea`.
# - No se admiten comodines (`*`): no son verificables.
# - No se admiten rutas absolutas ni `~`: son fuera del repo.
# - Extension cerrada: evita falsos positivos con ratios o versiones.
REF_RE = re.compile(
    r"(?<![\w./~-])"
    r"((?:[\w.-]+/)*[\w.-]+\.(?:py|md|json|jsonl|ya?ml|sh|txt|toml))"
    r":(\d+)(?:-(\d+))?"
)

# Como se declara el numero de tools MCP en las capas.
TOOL_COUNT_RE = re.compile(r"(\d+)\s+tools?\s+MCP", re.IGNORECASE)


def _parse_frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---"), f"{path.name}: sin frontmatter"
    end = text.index("---", 3)
    data = yaml.safe_load(text[3:end]) or {}
    assert isinstance(data, dict), f"{path.name}: frontmatter no es un mapping"
    return data


def _accepted_statuses() -> set[str]:
    """Statuses que acepta el gate.

    Si `lib/security_gate.py` expone el conjunto, se usa el suyo (es la
    fuente de verdad). Si no, se usa el vocabulario documentado.
    """
    lib_path = REPO_ROOT / "lib"
    if str(lib_path) not in sys.path:
        sys.path.insert(0, str(lib_path))
    try:
        import security_gate  # noqa: PLC0415
    except Exception:  # pragma: no cover - el gate no es importable
        return set(DOCUMENTED_STATUSES)
    for attr in ("VALID_STATUSES", "ACCEPTED_STATUSES", "STATUS_VALUES",
                 "ALLOWED_STATUSES"):
        value = getattr(security_gate, attr, None)
        if isinstance(value, (set, frozenset, list, tuple)) and value:
            return {str(v).lower() for v in value}
    return set(DOCUMENTED_STATUSES)


def _count_mcp_tools() -> int:
    """Numero de tools que declara `list_tools()` en el servidor MCP.

    Se cuenta de forma estatica (y no importando el servidor, que tiene
    efectos secundarios) sobre las declaraciones `Tool(` del propio
    fichero. Es el mismo criterio que el grep documentado en las capas.
    """
    src = (REPO_ROOT / "mcp" / "apex_server.py").read_text(encoding="utf-8")
    return len(re.findall(r"^ {8}Tool\($", src, re.MULTILINE))


def _layer_files() -> list[Path]:
    return [SECURITY_DIR / f"{lid}-{name}.md" for lid, name in LAYERS]


def test_security_dir_exists():
    assert SECURITY_DIR.is_dir(), f"falta el directorio {SECURITY_DIR}"


@pytest.mark.parametrize("layer_id,name", LAYERS)
def test_layer_file_exists(layer_id, name):
    path = SECURITY_DIR / f"{layer_id}-{name}.md"
    assert path.is_file(), f"falta la capa {layer_id} en {path}"


@pytest.mark.parametrize("layer_id,name", LAYERS)
def test_frontmatter_has_required_keys(layer_id, name):
    path = SECURITY_DIR / f"{layer_id}-{name}.md"
    data = _parse_frontmatter(path)
    for key in REQUIRED_KEYS:
        assert key in data, f"{path.name}: falta la clave '{key}' en el frontmatter"
    assert data["layer"] == layer_id, f"{path.name}: layer != {layer_id}"
    assert isinstance(data["evidence"], list) and data["evidence"], (
        f"{path.name}: la evidencia tiene que ser una lista no vacia")
    assert isinstance(data["asi_coverage"], list) and data["asi_coverage"], (
        f"{path.name}: asi_coverage tiene que ser una lista no vacia")


@pytest.mark.parametrize("layer_id,name", LAYERS)
def test_status_is_accepted_by_the_gate(layer_id, name):
    path = SECURITY_DIR / f"{layer_id}-{name}.md"
    data = _parse_frontmatter(path)
    status = str(data["status"]).lower()
    accepted = _accepted_statuses()
    assert status in accepted, (
        f"{path.name}: status '{status}' no es un valor que acepte el gate "
        f"({sorted(accepted)})")


@pytest.mark.parametrize("layer_id,name", LAYERS)
def test_evidence_references_point_to_real_files_and_lines(layer_id, name):
    """Cada `fichero:linea` de la evidencia tiene que existir de verdad."""
    path = SECURITY_DIR / f"{layer_id}-{name}.md"
    data = _parse_frontmatter(path)
    checked = 0
    for item in data["evidence"]:
        for match in REF_RE.finditer(str(item)):
            ref, start, end = match.group(1), int(match.group(2)), match.group(3)
            if "*" in ref:
                continue
            target = REPO_ROOT / ref
            assert target.is_file(), (
                f"{path.name}: la evidencia cita '{ref}:{start}' pero ese "
                f"fichero no existe")
            n_lines = len(target.read_text(encoding="utf-8").splitlines())
            assert start >= 1, f"{path.name}: '{ref}:{start}' linea invalida"
            assert start <= n_lines, (
                f"{path.name}: la evidencia cita '{ref}:{start}' pero el "
                f"fichero tiene {n_lines} lineas")
            if end:
                end = int(end)
                assert end >= start, (
                    f"{path.name}: rango invertido en '{ref}:{start}-{end}'")
                assert end <= n_lines, (
                    f"{path.name}: la evidencia cita '{ref}:{start}-{end}' pero "
                    f"el fichero tiene {n_lines} lineas")
            checked += 1
    assert checked > 0, (
        f"{path.name}: la evidencia no cita ninguna referencia fichero:linea "
        f"verificable")


def test_no_layer_states_a_stale_mcp_tool_count():
    """El numero de tools MCP es un hecho DERIVADO: no puede ageing."""
    current = _count_mcp_tools()
    assert current > 0, "no se pudo contar el numero de tools MCP"
    for path in _layer_files():
        text = path.read_text(encoding="utf-8")
        for literal in TOOL_COUNT_RE.findall(text):
            assert int(literal) == current, (
                f"{path.name}: afirma '{literal} tools MCP' pero el servidor "
                f"expone {current}. Recalcular con "
                f"`grep -c '^        Tool($' mcp/apex_server.py`")


def test_at_least_one_layer_documents_the_tool_count_as_derived():
    """El conteo de tools tiene que aparecer como hecho derivado."""
    current = _count_mcp_tools()
    found = False
    for path in _layer_files():
        text = path.read_text(encoding="utf-8")
        if "list_tools()" in text:
            found = True
            assert str(current) in text, (
                f"{path.name}: documenta list_tools() pero no el valor actual "
                f"({current})")
    assert found, "ninguna capa documenta como se deriva el numero de tools MCP"
