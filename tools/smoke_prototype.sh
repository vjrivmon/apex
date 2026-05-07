#!/usr/bin/env bash
# Smoke test end-to-end de skills/prototype + lib/prototype.py + state_machines.
#
# Ejercita 4 bloques en orden:
#   1. Happy path: init DB · scaffold TUI/wiki · INSERT state_machines.
#   2. Validación negativa: initial fuera de states, estado huérfano,
#      duplicado sin force, force=True idempotente.
#   3. Simulación pura: carga TRANSITIONS via AST y recorre la máquina
#      sin necesidad de Textual.
#   4. TUI headless: corre el .py generado con Textual Pilot, pulsa
#      bindings reales y verifica transiciones de estado.
#
# Tras un paso cualquiera fallido, sale con exit code != 0.
#
# Uso:
#   bash tools/smoke_prototype.sh           # tmp dir auto, instala textual si falta
#   APEX_SMOKE_DIR=/tmp/foo bash tools/smoke_prototype.sh
#   APEX_SMOKE_KEEP=1 bash tools/smoke_prototype.sh   # no borrar al terminar

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYBIN="${REPO_ROOT}/.venv/bin/python"
SMOKE_DIR="${APEX_SMOKE_DIR:-/tmp/proto-smoke-$$}"
KEEP="${APEX_SMOKE_KEEP:-0}"

if [[ ! -x "$PYBIN" ]]; then
    echo "ERROR: no se encuentra $PYBIN" >&2
    echo "Crea el venv primero: python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt" >&2
    exit 2
fi

cleanup() {
    if [[ "$KEEP" != "1" && -d "$SMOKE_DIR" ]]; then
        rm -rf "$SMOKE_DIR"
    fi
}
trap cleanup EXIT

echo ">>> Smoke proto en $SMOKE_DIR (KEEP=$KEEP)"

# Asegura textual instalado (solo lo necesita el bloque [4]).
if ! "$PYBIN" -c "import textual" >/dev/null 2>&1; then
    echo ">>> textual no instalado · pip install -q textual"
    "${REPO_ROOT}/.venv/bin/pip" install -q textual
fi

rm -rf "$SMOKE_DIR"
mkdir -p "$SMOKE_DIR"
(cd "$SMOKE_DIR" && git init -q)

PYTHONPATH="${REPO_ROOT}/lib" "$PYBIN" - <<PY
import asyncio, ast, json, sqlite3, sys
from pathlib import Path
sys.path.insert(0, "${REPO_ROOT}/lib")
from context_db import ApexContextDB
import prototype as proto

PROJECT = Path("${SMOKE_DIR}")
(PROJECT / ".apex").mkdir(exist_ok=True)
db = ApexContextDB(str(PROJECT / ".apex" / "context.db"))
asyncio.new_event_loop().run_until_complete(db.initialize())
print(f"[1] context.db inicializada en {db.db_path}")

# ── Bloque 1: happy path ────────────────────────────────────────
out = proto.apex_prototype_init(
    project_root=PROJECT,
    feature_name="checkout",
    states=["cart", "shipping", "paid", "refunded"],
    transitions=[
        {"from": "cart", "event": "next", "to": "shipping"},
        {"from": "shipping", "event": "pay", "to": "paid",
         "guard": "payment_authorized"},
        {"from": "paid", "event": "refund", "to": "refunded"},
    ],
    initial_state="cart",
)
print(f"[2] apex_prototype_init OK · machine_id={out['machine_id']}")
tui = Path(out["tui_path"]); wiki = Path(out["wiki_path"])
assert tui.exists() and wiki.exists()
print(f"[3] artefactos: TUI {tui.stat().st_size}B · wiki {wiki.stat().st_size}B")
ast.parse(tui.read_text())
print("[4] TUI parsea como Python válido")
wiki_txt = wiki.read_text()
assert "\`\`\`mermaid" in wiki_txt and "stateDiagram-v2" in wiki_txt
assert "[*] --> cart" in wiki_txt
assert "shipping --> paid: pay [payment_authorized]" in wiki_txt
print("[5] wiki tiene Mermaid stateDiagram-v2 con guard renderizado")
con = sqlite3.connect(str(db.db_path)); con.row_factory = sqlite3.Row
row = con.execute("SELECT * FROM state_machines").fetchone()
assert row["feature_name"] == "checkout" and row["initial_state"] == "cart"
assert len(json.loads(row["transitions"])) == 3
print(f"[6] state_machines fila: id={row['id']} feature={row['feature_name']!r}")

# ── Bloque 2: casos negativos ──────────────────────────────────
def _expect_value_error(label, **kwargs):
    try:
        proto.apex_prototype_init(project_root=PROJECT, **kwargs)
        raise AssertionError(f"[{label}] no levantó ValueError")
    except ValueError as e:
        print(f"[{label}] OK ValueError: {e}")

_expect_value_error(
    "A", feature_name="bad_initial",
    states=["a", "b"],
    transitions=[{"from": "a", "event": "go", "to": "b"}],
    initial_state="z",
)
_expect_value_error(
    "B", feature_name="bad_orphan",
    states=["a", "b", "orphan"],
    transitions=[{"from": "a", "event": "go", "to": "b"}],
    initial_state="a",
)
_expect_value_error(
    "C", feature_name="checkout",  # ya existe
    states=["cart", "shipping", "paid", "refunded"],
    transitions=[
        {"from": "cart", "event": "next", "to": "shipping"},
        {"from": "shipping", "event": "pay", "to": "paid"},
        {"from": "paid", "event": "refund", "to": "refunded"},
    ],
    initial_state="cart",
)

out2 = proto.apex_prototype_init(
    project_root=PROJECT, feature_name="checkout",
    states=["cart", "shipping", "paid", "refunded"],
    transitions=[
        {"from": "cart", "event": "next", "to": "shipping"},
        {"from": "shipping", "event": "pay", "to": "paid"},
        {"from": "paid", "event": "refund", "to": "refunded"},
        {"from": "refunded", "event": "reorder", "to": "cart"},
    ],
    initial_state="cart",
    force=True,
)
assert out2["machine_id"] == out["machine_id"], "force=True debe mantener machine_id"
print(f"[D] OK force=True · machine_id={out2['machine_id']} (mismo)")

# ── Bloque 3: simulación pura ──────────────────────────────────
tree = ast.parse(tui.read_text())
ns = {}
for node in tree.body:
    if isinstance(node, ast.Assign) and len(node.targets) == 1:
        target = node.targets[0]
        if isinstance(target, ast.Name) and target.id in (
                "STATES", "INITIAL_STATE", "TRANSITIONS"):
            ns[target.id] = ast.literal_eval(node.value)
print(f"[E] cargado del .py: {len(ns['TRANSITIONS'])} transiciones")
def fire(state, event, transitions):
    for tr in transitions:
        if tr["from"] == state and tr["event"] == event:
            return tr["to"]
    return state
state = ns["INITIAL_STATE"]; path = [state]
for ev in ["next", "pay", "refund", "reorder", "next"]:
    state = fire(state, ev, ns["TRANSITIONS"])
    path.append(state)
assert path == ["cart", "shipping", "paid", "refunded", "cart", "shipping"], path
print(f"[F] simulación: {' → '.join(path)}")
assert fire("cart", "pay", ns["TRANSITIONS"]) == "cart"
print("[G] evento inaplicable desde 'cart' → no-op")
PY

# ── Bloque 4: TUI headless con Textual Pilot ───────────────────
PYTHONPATH="${SMOKE_DIR}/.apex/prototypes" "$PYBIN" - <<PY
import asyncio, sys
sys.path.insert(0, "${SMOKE_DIR}/.apex/prototypes")
from checkout import PrototypeApp

async def smoke():
    app = PrototypeApp()
    async with app.run_test() as pilot:
        assert app.state == "cart", f"init: {app.state}"
        print(f"[H1] estado inicial: {app.state}")
        await pilot.press("n"); print(f"[H2] tras 'n': {app.state}")
        assert app.state == "shipping"
        await pilot.press("p"); print(f"[H3] tras 'p': {app.state}")
        assert app.state == "paid"
        await pilot.press("r"); print(f"[H4] tras 'r': {app.state}")
        assert app.state == "refunded"
        keys = [b[0] for b in PrototypeApp.BINDINGS if isinstance(b, tuple)]
        print(f"[H5] BINDINGS keys: {keys}")
        assert app.history == ["cart", "shipping", "paid", "refunded"]
        print(f"[H6] history: {app.history}")

asyncio.run(smoke())
print("[OK] TUI corre y reacciona a bindings sin errores")
PY

echo ">>> Smoke proto: TODOS LOS CHEQUEOS VERDE"
