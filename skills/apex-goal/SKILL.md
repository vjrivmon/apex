---
name: apex-goal
description: Bucle persistente con turn-budget. Mantiene un goal activo entre turnos, juez Sonnet 4.6 decide done|continue|degenerate tras cada turno. Adaptación de Hermes /goal con detección de degeneración.
---

# apex-goal (Sprint 8.2)

Goal persistente que sobrevive turnos. El agente trabaja, el juez evalúa,
APEX decide si continuar.

## Cuándo se invoca

- El usuario escribe `/apex:goal <prompt>` (o con `--budget`, `--resume`, `--list`).
- El agente decide internamente que una tarea iterativa se beneficia de
  goal-loop (raro: preferir que sea explícito del usuario).

## Cuándo NO usar

- Tareas one-shot (`crea X`, `explica Y`).
- Exploración abierta sin criterio de finalización.
- Cuando el grader (Sprint 8.1) ya marca la fase como bloqueada — primero
  desbloquear, luego goal.

## Flujo

Ver `commands/apex-goal.md` para el flujo detallado. Resumen:

1. `start_goal` → escribe estado en `.apex/goal/{id}.json`.
2. Loop: agente trabaja → `record_turn` → juez con `build_judge_prompt` →
   `parse_judge_decision` → `apply_judge_decision`.
3. Termina por: `done`, `degenerate`, `budget_exhausted`, `paused`.

## Salida visible al usuario

El agente debe mostrar al inicio y en cada transición:

- `○ Goal set (20-turn budget): <goal>`
- `↻ Continuing toward goal (3/20): <razón del juez>`
- `✓ Goal achieved: <razón>`
- `✗ Goal aborted (degenerate): <razón>`
- `‖ Goal paused — 5/20 turns used`
- `⊘ Budget exhausted — 20/20 turns used`

(Sin emojis. Esos símbolos son glifos Unicode tipográficos, no emojis.)

## Reglas

- El juez **no ve el código**, sólo el goal + summary de últimos 5 turnos.
- Si grader bloquea una fase, el goal no puede declararse "done".
- Cualquier mensaje del usuario → pausar goal automáticamente.
- Goals activos persisten cross-session.

## Próximos pasos (Sprints 9+)

- Integración con `apex_resume_session` (Sprint 9): goals activos aparecen
  en el handoff a 40% de contexto.
- Stream de decisiones del juez al apex-hub `/live` (Sprint 8.3).
- Multi-goal paralelo (Sprint 12 con virtual office).
