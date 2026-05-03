# /apex:goal — Goal persistente con turn-budget loop

Inspirado en Hermes `/goal` (Eric Traut, OpenAI Codex CLI 0.128.0). Adaptado a
APEX: el juez además de `done | continue` detecta **degeneración** (3+ turnos
sin progreso) y aborta antes de agotar budget.

## Uso

```
/apex:goal Fix every failing test in tests/ and verify pytest passes
/apex:goal --budget=10 Port feature X from repo Y including tests
/apex:goal --resume <goal_id>   # retoma uno pausado
/apex:goal --list                # lista goals activos
```

`$ARGUMENTS` se trata como el goal completo si no empieza por `--`.

## Flujo de ejecución (lo que hace el agente)

```
[1] start_goal(goal, turn_budget=20)
        → escribe .apex/goal/{id}.json
        → muestra al usuario: "○ Goal set ({budget}-turn budget): <goal>"

[2] LOOP:
    a. El agente trabaja el goal con sus herramientas habituales
       (Read, Edit, Bash, Agent, MCP tools, etc.).
    b. Al final del turno, llama a record_turn(goal_id, summary, tools_used)
       para incrementar el contador y guardar resumen.
    c. Si turns_used >= turn_budget:
       → status = budget_exhausted, salir del loop.
    d. Construye prompt vía build_judge_prompt(state).
    e. Invoca al juez:
       - Si ANTHROPIC_API_KEY: judge_with_anthropic(prompt) (Sonnet 4.6)
       - Si no: usa Agent tool con subagent_type=feature-dev:code-reviewer
                con el prompt y subir su respuesta a parse_judge_decision().
    f. apply_judge_decision(goal_id, decision):
       - "done" → status = done, salir y mostrar "✓ Goal achieved: <razón>"
       - "degenerate" → status = degenerate, salir y mostrar
                        "✗ Goal aborted (no progress): <razón>"
       - "continue" → mostrar "↻ Continuing toward goal ({n}/{budget}): <razón>"
                       y volver a [2a].

[3] SALIDA — siempre uno de:
       - ✓ Goal achieved: <reason>
       - ✗ Goal aborted (degenerate): <reason>
       - ‖ Goal paused — N/{budget} turns used (con flag --pause)
       - ⊘ Budget exhausted — N/{budget} turns used
```

## Cuándo usarlo

Tareas iterativas donde Vicente tendría que decir "sigue" varias veces:

- "Arregla cada lint error y verifica que `ruff check` pasa"
- "Migra esta feature de repo X y deja CI verde"
- "Investiga por qué el test Y falla a veces y deja el reporte"

**Mal encaje**: tareas one-shot (`crea un archivo X`), exploración abierta
(`explora el repo`), conversación.

## Reglas

- El juez **no ve el código**, solo el goal + resumen de últimos 5 turnos.
  Eso es deliberado: barato, suficiente para detectar finalización o loops.
- El juez **no relaja** decisiones del grader (Sprint 8.1). Si una fase
  está bloqueada por el grader, el goal no puede declararse "done" sobre
  esa fase.
- Si el usuario interrumpe con cualquier mensaje, **pausar el goal**
  (`pause_goal(id)`) y atender. Reanudar con `--resume <id>`.
- Goals activos persisten entre sesiones. `--list` los muestra.

## Estado en disco

```
.apex/goal/{id}.json
{
  "id": "ab12cd34ef56",
  "goal": "Fix every failing test in tests/",
  "turn_budget": 20,
  "turns_used": 4,
  "status": "active",
  "history": [
    {"turn": 1, "summary": "Read tests/test_x.py", "tools_used": ["Read"], "ts": "..."},
    {"turn": 2, "summary": "Edited tests/test_x.py — fixed assertion", "tools_used": ["Edit"], "ts": "..."},
    ...
  ],
  "created_at": "...",
  "updated_at": "..."
}
```

## Implementación de referencia

El módulo `lib/goal_loop.py` expone:

- `start_goal(project_root, goal, turn_budget)` → `GoalState`
- `record_turn(project_root, goal_id, summary, tools_used)` → `GoalState`
- `build_judge_prompt(state)` → `str`
- `parse_judge_decision(text)` → `dict`
- `apply_judge_decision(project_root, goal_id, decision)` → `GoalState`
- `pause_goal(project_root, goal_id)` → `GoalState`
- `list_active_goals(project_root)` → `list[GoalState]`
- `judge_with_anthropic(prompt, model='claude-sonnet-4-6')` → `dict`

Tests de regresión en `tests/test_goal_loop.py` (18 tests).

$ARGUMENTS
