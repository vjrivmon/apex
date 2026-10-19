"""APEX Sprint 15 S15.7 — skill /prototype scaffold.

Genera un prototipo ejecutable de máquina de estados para validar lógica
de negocio compleja (>5 reglas, transiciones no triviales) antes de
escribir código real. Ver `.apex/sprints/sprint-15-advisor-blueprint.md`
sección 4.

S15 entrega scaffold + INSERT en `state_machines`. La interactividad TUI
completa (atajos a estados profundos, replay, fuzzing) queda para S16.

API pública: `apex_prototype_init`.
"""
from __future__ import annotations

import json
import re
import sqlite3
from collections import deque
from pathlib import Path
from typing import Any

# ── Validación ───────────────────────────────────────────────────────────

_FEATURE_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,49}$")

# Un guard es el NOMBRE de una condición (`has_required_fields`,
# `payment_authorized`), no una expresión. La skill /prototype lo dice
# explícitamente: "Si una transición depende de una condición, nómbrala en el
# campo guard". Por eso se valida como identificador: el TUI generado tiene
# que poder invocar el guard por nombre.
_GUARD_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,49}$")


def _validate_inputs(
    feature_name: str,
    states: list[str],
    transitions: list[dict],
    initial_state: str,
) -> None:
    if not isinstance(feature_name, str) or not _FEATURE_NAME_RE.match(
            feature_name):
        raise ValueError(
            f"feature_name inválido: {feature_name!r} (usa snake-case "
            f"a-z0-9_- entre 1 y 50 chars, debe empezar con letra)")
    if not isinstance(states, list) or len(states) < 2:
        raise ValueError("Se requieren al menos 2 estados")
    if len(set(states)) != len(states):
        raise ValueError("estados duplicados en la lista")
    if not isinstance(transitions, list) or len(transitions) < 1:
        raise ValueError("Se requiere al menos 1 transición")
    if initial_state not in states:
        raise ValueError(
            f"initial_state {initial_state!r} no está en states")
    states_set = set(states)
    for i, tr in enumerate(transitions):
        if not isinstance(tr, dict):
            raise ValueError(f"transición #{i} no es dict")
        for key in ("from", "event", "to"):
            if key not in tr or not isinstance(tr[key], str) or not tr[key]:
                raise ValueError(
                    f"transición #{i}: campo {key!r} ausente o vacío")
        if tr["from"] not in states_set:
            raise ValueError(
                f"transición #{i}: estado de origen "
                f"{tr['from']!r} desconocido")
        if tr["to"] not in states_set:
            raise ValueError(
                f"transición #{i}: estado destino "
                f"{tr['to']!r} desconocido")
        guard = tr.get("guard")
        if guard is not None:
            if not isinstance(guard, str) or not _GUARD_NAME_RE.match(guard):
                raise ValueError(
                    f"transición #{i}: guard {guard!r} inválido. Un guard es "
                    f"el NOMBRE de una condición (ej. 'has_required_fields'), "
                    f"no una expresión: minúsculas, dígitos y guiones bajos, "
                    f"empezando por letra")


def _check_reachability(
    states: list[str],
    transitions: list[dict],
    initial_state: str,
) -> None:
    """BFS desde initial_state. Si algún estado no es alcanzable, falla."""
    adj: dict[str, list[str]] = {s: [] for s in states}
    for tr in transitions:
        adj[tr["from"]].append(tr["to"])
    seen = {initial_state}
    q = deque([initial_state])
    while q:
        cur = q.popleft()
        for nxt in adj[cur]:
            if nxt not in seen:
                seen.add(nxt)
                q.append(nxt)
    unreachable = sorted(set(states) - seen)
    if unreachable:
        raise ValueError(
            f"Estados no alcanzables desde {initial_state!r}: "
            f"{', '.join(unreachable)}")


# ── Generación de scaffolds ──────────────────────────────────────────────


def _render_tui(
    feature_name: str,
    states: list[str],
    transitions: list[dict],
    initial_state: str,
) -> str:
    """Textual TUI base con bindings por evento (atajos a transiciones)."""
    # Asignación de tecla por evento: primera letra única (fallback: índice)
    used: set[str] = set()
    bindings: list[tuple[str, str, str]] = []
    for i, tr in enumerate(transitions):
        ev = tr["event"]
        # Candidatos: primera letra, segunda, ..., luego dígitos.
        key = ""
        for ch in ev.lower():
            if ch.isalnum() and ch not in used:
                key = ch
                break
        if not key:
            key = str(i + 1)
        used.add(key)
        bindings.append((key, ev, f"{tr['from']} → {tr['to']}"))
    transitions_json = json.dumps(transitions, ensure_ascii=False, indent=4)
    bindings_lines = ",\n        ".join(
        f'("{k}", "fire_{ev}", "{label}")'
        for k, ev, label in bindings
    )
    actions_block = "\n".join(
        f"    def action_fire_{tr['event']}(self) -> None:\n"
        f"        self._fire(event={tr['event']!r})"
        for tr in transitions
    )
    # Un método por guard distinto. El cuerpo lo rellena quien edita el
    # fichero: el scaffold sale con `return True` (guard abierto) para que el
    # TUI arranque, pero la transición queda CONTRACTUAL: si el guard pasa a
    # False, la transición se bloquea y el TUI lo dice.
    guard_names = sorted({
        tr["guard"] for tr in transitions if tr.get("guard")
    })
    guards_block = "\n".join(
        f"    def guard_{name}(self) -> bool:\n"
        f"        # IMPLEMENTA la condición real de {name!r}.\n"
        f"        # Devuelve False para bloquear la transición que lo nombra.\n"
        f"        return True"
        for name in guard_names
    )
    if guards_block:
        guards_block = (
            "\n    # ── Guards contractuales ─────────────────────────────────\n"
            "    # Cada guard nombra una condición. Si devuelve False, la\n"
            "    # transición queda bloqueada y el TUI lo dice en pantalla.\n"
            + guards_block
        )
    return f'''"""Prototipo APEX (skill /prototype) — {feature_name}.

Generado por `apex_prototype_init`. Edita aquí la lógica de guards y
side-effects; sincroniza el diagrama en
`wiki/concepts/{feature_name}-state-machine.md` cuando cambies estados.

Requiere `textual>=0.50` para correr la TUI:

    pip install textual
    python {feature_name}.py
"""
from __future__ import annotations

try:
    from textual.app import App, ComposeResult
    from textual.binding import Binding  # noqa: F401
    from textual.widgets import Footer, Header, Static
except ImportError:  # pragma: no cover - depende del entorno
    raise SystemExit(
        "Falta textual. Instala con: pip install textual"
    )


FEATURE_NAME = {feature_name!r}
STATES = {states!r}
INITIAL_STATE = {initial_state!r}
TRANSITIONS = {transitions_json}


class PrototypeApp(App):
    """Máquina de estados ejecutable. Cada binding salta una transición."""

    CSS = """
    Screen {{ align: center middle; }}
    #current {{ content-align: center middle; height: 5; }}
    """

    BINDINGS = [
        {bindings_lines},
        ("q", "quit", "Salir"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.state = INITIAL_STATE
        self.history: list[str] = [INITIAL_STATE]
        self.blocked: str = ""

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(self._render(), id="current")
        yield Footer()

    def _render(self) -> str:
        path = " → ".join(self.history[-6:])
        head = f"feature: {{FEATURE_NAME}}\\nestado: {{self.state}}\\npath: {{path}}"
        if self.blocked:
            head += f"\\nbloqueado: {{self.blocked}}"
        return head

    def _fire(self, event: str) -> None:
        for tr in TRANSITIONS:
            if tr["from"] == self.state and tr["event"] == event:
                guard = tr.get("guard")
                if guard and not getattr(self, f"guard_{{guard}}")():
                    # El guard manda: la transición NO ocurre y se explica por
                    # qué. Antes esto se ignoraba con un TODO.
                    self.blocked = (
                        f"guard '{{guard}}' bloquea "
                        f"{{tr['from']}} → {{tr['to']}}"
                    )
                    self.query_one("#current", Static).update(self._render())
                    return
                self.blocked = ""
                self.state = tr["to"]
                self.history.append(self.state)
                self.query_one("#current", Static).update(self._render())
                return
        # Evento no aplica desde el estado actual; refrescar igual.
        self.query_one("#current", Static).update(self._render())

{guards_block}
{actions_block}


if __name__ == "__main__":
    PrototypeApp().run()
'''


def _render_wiki(
    feature_name: str,
    states: list[str],
    transitions: list[dict],
    initial_state: str,
) -> str:
    """Markdown con frontmatter + Mermaid stateDiagram + tabla de reglas."""
    lines = [
        "---",
        f"title: {feature_name} — state machine",
        "type: concept",
        "source: apex_prototype_init",
        "---",
        "",
        f"# {feature_name} — máquina de estados",
        "",
        "Generado por la skill `/prototype` (S15). Mantén este archivo "
        "sincronizado con `.apex/prototypes/" + feature_name + ".py` "
        "cuando cambien estados o transiciones.",
        "",
        "## Diagrama",
        "",
        "```mermaid",
        "stateDiagram-v2",
        f"    [*] --> {initial_state}",
    ]
    for tr in transitions:
        guard = tr.get("guard")
        label = tr["event"] + (f" [{guard}]" if guard else "")
        lines.append(f"    {tr['from']} --> {tr['to']}: {label}")
    lines += [
        "```",
        "",
        "## Estados",
        "",
    ]
    for s in states:
        marker = " (initial)" if s == initial_state else ""
        lines.append(f"- `{s}`{marker}")
    lines += [
        "",
        "## Reglas (transiciones)",
        "",
        "| from | event | to | guard |",
        "| ---- | ----- | -- | ----- |",
    ]
    for tr in transitions:
        lines.append(
            f"| `{tr['from']}` | `{tr['event']}` | `{tr['to']}` | "
            f"{tr.get('guard') or '—'} |"
        )
    lines += [
        "",
        "## Verificación post-implementación",
        "",
        "El grader (fase 9) debe comprobar que el código real honra estas "
        "transiciones. Cualquier camino estado→estado no listado aquí es "
        "deuda: o se añade explícitamente o se elimina del código.",
        "",
    ]
    return "\n".join(lines)


# ── DB helpers ───────────────────────────────────────────────────────────


def _conn(db_path: Path | str) -> sqlite3.Connection:
    return sqlite3.connect(str(db_path), timeout=5.0)


def _existing_machine(
    db_path: Path | str, feature_name: str,
) -> sqlite3.Row | None:
    with _conn(db_path) as c:
        c.row_factory = sqlite3.Row
        return c.execute(
            "SELECT * FROM state_machines WHERE feature_name=?",
            (feature_name,),
        ).fetchone()


# ── API pública ──────────────────────────────────────────────────────────


def apex_prototype_init(
    *,
    project_root: Path | str,
    feature_name: str,
    states: list[str],
    transitions: list[dict],
    initial_state: str,
    force: bool = False,
) -> dict[str, Any]:
    """Genera scaffold de máquina de estados ejecutable.

    Args:
        project_root: Raíz del proyecto APEX (contiene `.apex/context.db`).
        feature_name: Slug snake-case (a-z0-9_-).
        states: Lista de estados (>=2, únicos).
        transitions: Lista de dicts con keys `from`, `event`, `to`,
            opcional `guard`.
        initial_state: Estado de arranque, debe estar en `states`.
        force: Si ya existe `feature_name`, sobrescribe en vez de fallar.

    Returns:
        dict con `tui_path`, `wiki_path`, `machine_id`.

    Raises:
        ValueError: Validaciones de inputs, reachability, o duplicado sin
            force.
    """
    _validate_inputs(feature_name, states, transitions, initial_state)
    _check_reachability(states, transitions, initial_state)

    project_root = Path(project_root)
    db_path = project_root / ".apex" / "context.db"
    if not db_path.exists():
        raise ValueError(
            f"No se encontró {db_path}; ejecuta apex_init_project primero")

    existing = _existing_machine(db_path, feature_name)
    if existing is not None and not force:
        raise ValueError(
            f"feature_name {feature_name!r} ya existe (machine_id="
            f"{existing['id']}). Usa force=True para sobrescribir.")

    tui_dir = project_root / ".apex" / "prototypes"
    wiki_dir = project_root / "wiki" / "concepts"
    tui_dir.mkdir(parents=True, exist_ok=True)
    wiki_dir.mkdir(parents=True, exist_ok=True)
    tui_path = tui_dir / f"{feature_name}.py"
    wiki_path = wiki_dir / f"{feature_name}-state-machine.md"

    tui_path.write_text(
        _render_tui(feature_name, states, transitions, initial_state),
        encoding="utf-8",
    )
    wiki_path.write_text(
        _render_wiki(feature_name, states, transitions, initial_state),
        encoding="utf-8",
    )

    states_json = json.dumps(states, ensure_ascii=False)
    trans_json = json.dumps(transitions, ensure_ascii=False)
    tui_rel = str(tui_path.relative_to(project_root))
    wiki_rel = str(wiki_path.relative_to(project_root))

    with _conn(db_path) as c:
        if existing is not None:
            c.execute(
                "UPDATE state_machines SET states=?, transitions=?, "
                "initial_state=?, tui_path=?, wiki_path=?, "
                "created_at=datetime('now') WHERE feature_name=?",
                (states_json, trans_json, initial_state,
                 tui_rel, wiki_rel, feature_name),
            )
            machine_id = int(existing["id"])
        else:
            cur = c.execute(
                "INSERT INTO state_machines "
                "(feature_name, states, transitions, initial_state, "
                " tui_path, wiki_path) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (feature_name, states_json, trans_json, initial_state,
                 tui_rel, wiki_rel),
            )
            machine_id = int(cur.lastrowid)
        c.commit()

    return {
        "tui_path": str(tui_path),
        "wiki_path": str(wiki_path),
        "machine_id": machine_id,
    }
