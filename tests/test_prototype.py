"""Sprint 15 S15.7 — tests para lib/prototype.py.

Cubre:
- Happy path: scaffold + INSERT + paths devueltos.
- Validación: initial_state en states, transiciones referencian estados
  conocidos, estados/transiciones mínimos.
- Reachability: detecta estados inalcanzables desde initial.
- Idempotencia: feature_name UNIQUE bloquea re-init sin force.
- Generación: TUI Python parseable, wiki con Mermaid stateDiagram.
- Wiring MCP: list_tools incluye `apex_prototype_init` y dispatcher
  responde sin reventar.
"""
from __future__ import annotations

import ast
import asyncio
import importlib.util
import json
import os
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from context_db import ApexContextDB  # noqa: E402
import prototype as proto  # noqa: E402


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.fixture
def project(tmp_path: Path):
    """Crea un proyecto APEX falso: <root>/.apex/context.db inicializado."""
    apex_dir = tmp_path / ".apex"
    apex_dir.mkdir()
    db_path = apex_dir / "context.db"
    db = ApexContextDB(str(db_path))
    run(db.initialize())
    return tmp_path


def _states_basic() -> list[str]:
    return ["draft", "review", "published"]


def _transitions_basic() -> list[dict]:
    return [
        {"from": "draft", "event": "submit", "to": "review",
         "guard": "has_required_fields"},
        {"from": "review", "event": "approve", "to": "published"},
        {"from": "review", "event": "reject", "to": "draft"},
    ]


class TestHappyPath:
    def test_returns_paths_and_id(self, project: Path):
        out = proto.apex_prototype_init(
            project_root=project,
            feature_name="article_lifecycle",
            states=_states_basic(),
            transitions=_transitions_basic(),
            initial_state="draft",
        )
        assert isinstance(out, dict)
        assert "tui_path" in out and "wiki_path" in out
        assert isinstance(out["machine_id"], int) and out["machine_id"] > 0

        tui = Path(out["tui_path"])
        wiki = Path(out["wiki_path"])
        assert tui.exists() and tui.suffix == ".py"
        assert wiki.exists() and wiki.suffix == ".md"
        assert tui.is_relative_to(project / ".apex" / "prototypes")
        assert wiki.is_relative_to(project / "wiki" / "concepts")

    def test_inserts_state_machine_row(self, project: Path):
        out = proto.apex_prototype_init(
            project_root=project,
            feature_name="article_lifecycle",
            states=_states_basic(),
            transitions=_transitions_basic(),
            initial_state="draft",
        )
        with sqlite3.connect(str(project / ".apex" / "context.db")) as c:
            c.row_factory = sqlite3.Row
            row = c.execute(
                "SELECT * FROM state_machines WHERE id=?",
                (out["machine_id"],),
            ).fetchone()
        assert row is not None
        assert row["feature_name"] == "article_lifecycle"
        assert row["initial_state"] == "draft"
        assert json.loads(row["states"]) == _states_basic()
        assert len(json.loads(row["transitions"])) == 3

    def test_generated_tui_is_valid_python(self, project: Path):
        out = proto.apex_prototype_init(
            project_root=project,
            feature_name="article_lifecycle",
            states=_states_basic(),
            transitions=_transitions_basic(),
            initial_state="draft",
        )
        src = Path(out["tui_path"]).read_text(encoding="utf-8")
        ast.parse(src)  # no SyntaxError
        # Cada estado aparece como literal en el scaffold
        for s in _states_basic():
            assert s in src
        # Cada evento aparece en bindings (para "atajar" a estado profundo)
        for tr in _transitions_basic():
            assert tr["event"] in src

    def test_wiki_has_mermaid_state_diagram(self, project: Path):
        out = proto.apex_prototype_init(
            project_root=project,
            feature_name="article_lifecycle",
            states=_states_basic(),
            transitions=_transitions_basic(),
            initial_state="draft",
        )
        wiki = Path(out["wiki_path"]).read_text(encoding="utf-8")
        assert "```mermaid" in wiki
        assert "stateDiagram" in wiki
        # Initial marker estilo Mermaid
        assert "[*] --> draft" in wiki
        # Cada transición renderizada
        assert "draft --> review" in wiki
        assert "review --> published" in wiki


class TestValidation:
    def test_rejects_initial_state_not_in_states(self, project: Path):
        with pytest.raises(ValueError, match="initial_state"):
            proto.apex_prototype_init(
                project_root=project,
                feature_name="x",
                states=["a", "b"],
                transitions=[{"from": "a", "event": "go", "to": "b"}],
                initial_state="z",
            )

    def test_rejects_transition_with_unknown_state(self, project: Path):
        with pytest.raises(ValueError, match="estado"):
            proto.apex_prototype_init(
                project_root=project,
                feature_name="x",
                states=["a", "b"],
                transitions=[{"from": "a", "event": "go", "to": "MISSING"}],
                initial_state="a",
            )

    def test_rejects_too_few_states(self, project: Path):
        with pytest.raises(ValueError, match="estados"):
            proto.apex_prototype_init(
                project_root=project,
                feature_name="x",
                states=["only_one"],
                transitions=[],
                initial_state="only_one",
            )

    def test_rejects_no_transitions(self, project: Path):
        with pytest.raises(ValueError, match="transici"):
            proto.apex_prototype_init(
                project_root=project,
                feature_name="x",
                states=["a", "b"],
                transitions=[],
                initial_state="a",
            )

    def test_rejects_bad_feature_name(self, project: Path):
        with pytest.raises(ValueError, match="feature_name"):
            proto.apex_prototype_init(
                project_root=project,
                feature_name="bad name with spaces",
                states=["a", "b"],
                transitions=[{"from": "a", "event": "go", "to": "b"}],
                initial_state="a",
            )


class TestReachability:
    def test_detects_unreachable_state(self, project: Path):
        # 'orphan' no es alcanzable desde 'a'
        with pytest.raises(ValueError, match="alcanzab"):
            proto.apex_prototype_init(
                project_root=project,
                feature_name="x",
                states=["a", "b", "orphan"],
                transitions=[{"from": "a", "event": "go", "to": "b"}],
                initial_state="a",
            )


class TestIdempotency:
    def test_duplicate_feature_name_raises_without_force(self, project: Path):
        proto.apex_prototype_init(
            project_root=project,
            feature_name="dup",
            states=_states_basic(),
            transitions=_transitions_basic(),
            initial_state="draft",
        )
        with pytest.raises(ValueError, match="ya existe"):
            proto.apex_prototype_init(
                project_root=project,
                feature_name="dup",
                states=_states_basic(),
                transitions=_transitions_basic(),
                initial_state="draft",
            )

    def test_force_overwrites_existing(self, project: Path):
        out1 = proto.apex_prototype_init(
            project_root=project,
            feature_name="dup",
            states=_states_basic(),
            transitions=_transitions_basic(),
            initial_state="draft",
        )
        out2 = proto.apex_prototype_init(
            project_root=project,
            feature_name="dup",
            states=_states_basic(),
            transitions=_transitions_basic(),
            initial_state="draft",
            force=True,
        )
        assert out2["machine_id"] == out1["machine_id"]
        assert Path(out2["tui_path"]).exists()


# ── Wiring MCP ───────────────────────────────────────────────────────────


_APEX_SERVER_PATH = (
    Path(__file__).resolve().parent.parent / "mcp" / "apex_server.py"
)


@pytest.fixture(scope="module")
def apex_server_mod():
    spec = importlib.util.spec_from_file_location(
        "apex_server_under_test_proto", str(_APEX_SERVER_PATH)
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestMCPWiring:
    def test_list_tools_includes_prototype_init(self, apex_server_mod):
        tools = run(apex_server_mod.list_tools())
        names = {t.name for t in tools}
        assert "apex_prototype_init" in names

    def test_dispatcher_creates_machine(
        self, apex_server_mod, tmp_path, monkeypatch,
    ):
        (tmp_path / ".apex").mkdir()
        db = ApexContextDB(str(tmp_path / ".apex" / "context.db"))
        run(db.initialize())
        monkeypatch.chdir(tmp_path)
        res = run(apex_server_mod.call_tool(
            "apex_prototype_init",
            {
                "feature_name": "checkout_flow",
                "states": ["cart", "shipping", "paid"],
                "transitions": [
                    {"from": "cart", "event": "next", "to": "shipping"},
                    {"from": "shipping", "event": "pay", "to": "paid"},
                ],
                "initial_state": "cart",
            },
        ))
        text = res[0].text
        assert "prototype" in text and "TUI" in text
        assert (tmp_path / ".apex" / "prototypes" / "checkout_flow.py")\
            .exists()
        assert (tmp_path / "wiki" / "concepts"
                / "checkout_flow-state-machine.md").exists()

    def test_dispatcher_reports_validation_error(
        self, apex_server_mod, tmp_path, monkeypatch,
    ):
        (tmp_path / ".apex").mkdir()
        db = ApexContextDB(str(tmp_path / ".apex" / "context.db"))
        run(db.initialize())
        monkeypatch.chdir(tmp_path)
        res = run(apex_server_mod.call_tool(
            "apex_prototype_init",
            {
                "feature_name": "bad",
                "states": ["a", "b"],
                "transitions": [
                    {"from": "a", "event": "go", "to": "b"},
                ],
                "initial_state": "z",  # no está en states
            },
        ))
        text = res[0].text
        assert "Validación falló" in text or "initial_state" in text


# ── Guards contractuales ─────────────────────────────────────────────────
#
# La skill /prototype dice: "Si una transición depende de una condición
# (`has_required_fields`, `payment_authorized`), nómbrala en el campo `guard`.
# Los guards son contractuales." Hasta ahora el TUI generado lo ignoraba con
# un TODO y la transición ocurría igual. Estos tests fijan que el guard se
# EVALÚA y que bloquea la transición cuando devuelve False.


@pytest.fixture
def textual_falso(monkeypatch):
    """Módulo textual mínimo para poder importar el TUI generado.

    `textual` no es dependencia de APEX: el scaffold dice "pip install
    textual" y el TUI es opcional. Para poder ejercitar la lógica del guard
    sin la TUI real, se inyecta un doble mínimo.
    """
    import types

    class _Static:
        def __init__(self, *args, **kwargs):
            self.rendered = ""

        def update(self, text):
            self.rendered = text

    class _App:
        def __init__(self, *args, **kwargs):
            self._widgets = {"#current": _Static()}

        def query_one(self, selector, widget_type=None):
            return self._widgets[selector]

        def run(self):
            return None

    app_mod = types.ModuleType("textual.app")
    app_mod.App = _App
    app_mod.ComposeResult = list

    binding_mod = types.ModuleType("textual.binding")
    binding_mod.Binding = tuple

    widgets_mod = types.ModuleType("textual.widgets")
    widgets_mod.Footer = _Static
    widgets_mod.Header = _Static
    widgets_mod.Static = _Static

    textual_mod = types.ModuleType("textual")
    textual_mod.app = app_mod
    textual_mod.binding = binding_mod
    textual_mod.widgets = widgets_mod

    monkeypatch.setitem(sys.modules, "textual", textual_mod)
    monkeypatch.setitem(sys.modules, "textual.app", app_mod)
    monkeypatch.setitem(sys.modules, "textual.binding", binding_mod)
    monkeypatch.setitem(sys.modules, "textual.widgets", widgets_mod)
    return textual_mod


def _cargar_tui(ruta: Path, nombre: str):
    spec = importlib.util.spec_from_file_location(nombre, ruta)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestGuards:
    def test_genera_un_metodo_por_guard(self, project: Path):
        out = proto.apex_prototype_init(
            project_root=project,
            feature_name="checkout_flow",
            states=["cart", "shipping", "paid"],
            transitions=[
                {"from": "cart", "event": "next", "to": "shipping",
                 "guard": "has_required_fields"},
                {"from": "shipping", "event": "pay", "to": "paid",
                 "guard": "payment_authorized"},
                {"from": "shipping", "event": "cancel", "to": "cart"},
            ],
            initial_state="cart",
        )
        src = Path(out["tui_path"]).read_text(encoding="utf-8")
        assert "def guard_has_required_fields(self) -> bool:" in src
        assert "def guard_payment_authorized(self) -> bool:" in src
        # Un guard por transición con nombre, no por transición.
        assert src.count("def guard_") == 2
        ast.parse(src)  # sigue siendo Python válido

    def test_no_hay_metodos_de_guard_si_no_hay_guards(self, project: Path):
        out = proto.apex_prototype_init(
            project_root=project,
            feature_name="sin_guards",
            states=["a", "b"],
            transitions=[{"from": "a", "event": "go", "to": "b"}],
            initial_state="a",
        )
        src = Path(out["tui_path"]).read_text(encoding="utf-8")
        assert "def guard_" not in src

    def test_guard_abierto_permite_la_transicion(
        self, project: Path, textual_falso,
    ):
        out = proto.apex_prototype_init(
            project_root=project,
            feature_name="checkout_flow",
            states=["cart", "shipping", "paid"],
            transitions=[
                {"from": "cart", "event": "next", "to": "shipping",
                 "guard": "has_required_fields"},
                {"from": "shipping", "event": "pay", "to": "paid"},
            ],
            initial_state="cart",
        )
        mod = _cargar_tui(Path(out["tui_path"]), "tui_guards_abiertos")
        app = mod.PrototypeApp()
        app._fire("next")
        assert app.state == "shipping"
        assert app.blocked == ""

    def test_guard_cerrado_bloquea_la_transicion(
        self, project: Path, textual_falso,
    ):
        out = proto.apex_prototype_init(
            project_root=project,
            feature_name="checkout_flow",
            states=["cart", "shipping", "paid"],
            transitions=[
                {"from": "cart", "event": "next", "to": "shipping",
                 "guard": "has_required_fields"},
                {"from": "shipping", "event": "pay", "to": "paid"},
            ],
            initial_state="cart",
        )
        mod = _cargar_tui(Path(out["tui_path"]), "tui_guard_cerrado")
        app = mod.PrototypeApp()
        # El guard se implementa en el fichero generado: aquí se fuerza a
        # False para comprobar que la transición NO ocurre.
        app.guard_has_required_fields = lambda: False
        app._fire("next")
        assert app.state == "cart", "el guard cerrado debe impedir la transición"
        assert "has_required_fields" in app.blocked
        assert "cart" in app.blocked and "shipping" in app.blocked

    def test_transicion_sin_guard_sigue_pasando(
        self, project: Path, textual_falso,
    ):
        out = proto.apex_prototype_init(
            project_root=project,
            feature_name="checkout_flow",
            states=["cart", "shipping", "paid"],
            transitions=[
                {"from": "cart", "event": "next", "to": "shipping",
                 "guard": "has_required_fields"},
                {"from": "cart", "event": "cancel", "to": "paid"},
            ],
            initial_state="cart",
        )
        mod = _cargar_tui(Path(out["tui_path"]), "tui_sin_guard")
        app = mod.PrototypeApp()
        app.guard_has_required_fields = lambda: False
        app._fire("cancel")
        assert app.state == "paid"
        assert app.blocked == ""

    def test_guard_invalido_se_rechaza_en_validacion(self, project: Path):
        with pytest.raises(ValueError, match="guard"):
            proto.apex_prototype_init(
                project_root=project,
                feature_name="bad_guard",
                states=["a", "b"],
                transitions=[
                    {"from": "a", "event": "go", "to": "b",
                     "guard": "no es un identificador"},
                ],
                initial_state="a",
            )

    def test_guard_no_string_vacia_se_rechaza(self, project: Path):
        with pytest.raises(ValueError, match="guard"):
            proto.apex_prototype_init(
                project_root=project,
                feature_name="empty_guard",
                states=["a", "b"],
                transitions=[
                    {"from": "a", "event": "go", "to": "b", "guard": ""},
                ],
                initial_state="a",
            )
