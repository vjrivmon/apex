"""APEX /goal turn-budget loop (Sprint 8.2).

Inspirado en Hermes /goal de Eric Traut/teknium1 (Codex CLI 0.128.0): el modelo
recibe un goal persistente que sobrevive turnos. Tras cada turno, un juez
ligero (Sonnet 4.6) decide done | continue. Si continue, el agente sigue
automáticamente hasta done, budget agotado o pausa manual.

A diferencia de Hermes, el juez aquí también detecta DEGENERACIÓN (loops sin
progreso real) y aborta antes de agotar budget.

Esta librería NO ejecuta turnos — el ejecutor es el agente Claude Code o el
modo Anthropic SDK. La librería gestiona estado en `.apex/goal/{id}.json`,
construye prompts para el juez y parsea decisiones.
"""
from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import handoff as _handoff_lib

DEFAULT_TURN_BUDGET = 20

DECISION_DONE = "done"
DECISION_CONTINUE = "continue"
DECISION_DEGENERATE = "degenerate"

STATUS_ACTIVE = "active"
STATUS_DONE = "done"
STATUS_PAUSED = "paused"
STATUS_BUDGET_EXHAUSTED = "budget_exhausted"
STATUS_DEGENERATE = "degenerate"
STATUS_CONTEXT_THRESHOLD = "context_threshold"

_DEFAULT_THRESHOLD_TOKENS = 200_000


def _resolve_threshold_tokens(override: int | None) -> int:
    if override is not None and override > 0:
        return int(override)
    env_val = os.environ.get("APEX_HANDOFF_THRESHOLD_TOKENS")
    if env_val:
        try:
            n = int(env_val)
            if n > 0:
                return n
        except ValueError:
            pass
    return _DEFAULT_THRESHOLD_TOKENS


@dataclass
class GoalState:
    id: str
    goal: str
    turn_budget: int
    turns_used: int = 0
    status: str = STATUS_ACTIVE
    history: list[dict] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, text: str) -> "GoalState":
        return cls(**json.loads(text))

    def is_terminal(self) -> bool:
        return self.status != STATUS_ACTIVE


def _goals_dir(project_root: Path) -> Path:
    return Path(project_root) / ".apex" / "goal"


def _state_path(project_root: Path, goal_id: str) -> Path:
    return _goals_dir(project_root) / f"{goal_id}.json"


# ── API pública ───────────────────────────────────────────────────────────

def start_goal(project_root: Path | str, goal: str,
               turn_budget: int = DEFAULT_TURN_BUDGET) -> GoalState:
    """Crea un goal nuevo y persiste estado inicial."""
    goal_id = uuid.uuid4().hex[:12]
    now = datetime.now(timezone.utc).isoformat()
    state = GoalState(
        id=goal_id,
        goal=goal,
        turn_budget=turn_budget,
        created_at=now,
        updated_at=now,
    )
    path = _state_path(Path(project_root), goal_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(state.to_json())
    return state


def load_goal(project_root: Path | str, goal_id: str) -> GoalState:
    path = _state_path(Path(project_root), goal_id)
    return GoalState.from_json(path.read_text())


def save_goal(project_root: Path | str, state: GoalState) -> None:
    state.updated_at = datetime.now(timezone.utc).isoformat()
    path = _state_path(Path(project_root), state.id)
    path.write_text(state.to_json())


def record_turn(project_root: Path | str, goal_id: str,
                turn_summary: str,
                tools_used: list[str] | None = None,
                transcript_path: Path | str | None = None,
                threshold_tokens: int | None = None) -> GoalState:
    """Registra un turno completado por el agente.

    Termina el goal con un status terminal en dos condiciones independientes:

    - `STATUS_BUDGET_EXHAUSTED` si `turns_used >= turn_budget`.
    - `STATUS_CONTEXT_THRESHOLD` si `transcript_path` se pasa y los tokens
      estimados del transcript JSONL superan `threshold_tokens` (override) o
      la env `APEX_HANDOFF_THRESHOLD_TOKENS` (default 200_000).

    Si las dos condiciones se cumplen en el mismo turno, prevalece
    `context_threshold` porque requiere acción del usuario (handoff + /clear),
    mientras que budget_exhausted es solo cierre del ciclo.
    """
    state = load_goal(project_root, goal_id)
    if state.is_terminal():
        return state
    state.turns_used += 1
    entry: dict = {
        "turn": state.turns_used,
        "summary": (turn_summary or "")[:1000],
        "tools_used": tools_used or [],
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    state.history.append(entry)

    if state.turns_used >= state.turn_budget:
        state.status = STATUS_BUDGET_EXHAUSTED

    if transcript_path:
        tokens = _handoff_lib.estimate_tokens_in_transcript(transcript_path)
        if tokens > 0:
            limit = _resolve_threshold_tokens(threshold_tokens)
            entry["transcript_tokens"] = tokens
            if tokens >= limit:
                state.status = STATUS_CONTEXT_THRESHOLD
                entry["threshold_tokens"] = limit

    save_goal(project_root, state)
    return state


def build_judge_prompt(state: GoalState) -> str:
    """Prompt para el juez Sonnet 4.6: ¿done | continue | degenerate?"""
    last_turns = state.history[-5:] if state.history else []
    history_block = "\n".join(
        f"- Turno {h.get('turn', '?')}: {h.get('summary', '')[:280]}"
        for h in last_turns if h.get("tools_used") != ["judge"]
    ) or "(sin turnos previos)"

    return f"""Eres juez objetivo de un /goal loop de APEX. Decide si el goal se ha completado,
si hay degeneración (no hay progreso) o si el agente debe continuar.

## Goal
{state.goal}

## Turnos usados: {state.turns_used} / {state.turn_budget}

## Últimos turnos del agente
{history_block}

## Tu tarea
Devuelve SÓLO un JSON con este schema, sin texto adicional:

{{
  "decision": "done|continue|degenerate",
  "reason": "una frase corta explicando la decisión"
}}

Reglas:
- "done" si el goal está cumplido según evidencia en los últimos turnos
- "degenerate" si los últimos 3 turnos repiten acciones sin progreso real
- "continue" en cualquier otro caso (el agente debe seguir trabajando)"""


def parse_judge_decision(text: str) -> dict:
    """Parser tolerante de la decisión del juez."""
    if not text:
        return {"decision": DECISION_CONTINUE,
                "reason": "(juez sin respuesta)"}
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < 0 or end <= start:
        lower = text.lower()
        if "degenerate" in lower:
            return {"decision": DECISION_DEGENERATE,
                    "reason": "(heurística texto: degenerate)"}
        if "done" in lower and "continue" not in lower[:50]:
            return {"decision": DECISION_DONE,
                    "reason": "(heurística texto: done)"}
        return {"decision": DECISION_CONTINUE,
                "reason": "(heurística texto: continue)"}
    try:
        d = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return {"decision": DECISION_CONTINUE,
                "reason": "(json inválido)"}
    if d.get("decision") not in (DECISION_DONE, DECISION_CONTINUE,
                                  DECISION_DEGENERATE):
        d["decision"] = DECISION_CONTINUE
    if "reason" not in d:
        d["reason"] = "(sin razón)"
    return d


def apply_judge_decision(project_root: Path | str, goal_id: str,
                          decision: dict) -> GoalState:
    """Aplica la decisión del juez al estado del goal."""
    state = load_goal(project_root, goal_id)
    if state.is_terminal():
        return state
    d = decision.get("decision", DECISION_CONTINUE)
    if d == DECISION_DONE:
        state.status = STATUS_DONE
    elif d == DECISION_DEGENERATE:
        state.status = STATUS_DEGENERATE
    state.history.append({
        "turn": state.turns_used,
        "summary": f"[judge] {d}: {decision.get('reason', '')[:200]}",
        "tools_used": ["judge"],
        "ts": datetime.now(timezone.utc).isoformat(),
    })
    save_goal(project_root, state)
    return state


def pause_goal(project_root: Path | str, goal_id: str) -> GoalState:
    state = load_goal(project_root, goal_id)
    if state.is_terminal():
        return state
    state.status = STATUS_PAUSED
    save_goal(project_root, state)
    return state


def list_active_goals(project_root: Path | str) -> list[GoalState]:
    out: list[GoalState] = []
    d = _goals_dir(Path(project_root))
    if not d.exists():
        return out
    for f in sorted(d.glob("*.json")):
        try:
            state = GoalState.from_json(f.read_text())
        except Exception:
            continue
        if state.status == STATUS_ACTIVE:
            out.append(state)
    return out


# ── Wrapper Anthropic SDK opcional ────────────────────────────────────────

def judge_with_anthropic(prompt: str,
                         model: str = "claude-sonnet-4-6") -> dict:
    import os
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return {"decision": DECISION_CONTINUE,
                "reason": "(sin ANTHROPIC_API_KEY: continue por defecto)"}
    try:
        import anthropic  # type: ignore
    except ImportError:
        return {"decision": DECISION_CONTINUE,
                "reason": "(anthropic SDK no instalado)"}
    client = anthropic.Anthropic(api_key=api_key)
    try:
        msg = client.messages.create(
            model=model,
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in msg.content if hasattr(b, "text"))
        return parse_judge_decision(text)
    except Exception as ex:
        return {"decision": DECISION_CONTINUE,
                "reason": f"(juez error: {type(ex).__name__})"}
