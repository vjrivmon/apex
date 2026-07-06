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
- `⚠ Context threshold — handoff escrito, pide /clear al usuario`

(Sin emojis. Esos símbolos son glifos Unicode tipográficos, no emojis.)

## Trigger nuevo: context_threshold (auto-handoff)

Al llamar `apex_goal_loop(action="record_turn", ...)` el agente puede pasar
opcionalmente:

- `transcript_path`: ruta al JSONL de la sesión actual (Claude Code lo
  expone vía hook payload con clave `transcript_path`).
- `session_id`: ID de la sesión actual (para nombrar el handoff).
- `threshold_tokens` (opcional): override del umbral; si no se pasa, lee la
  env `APEX_HANDOFF_THRESHOLD_TOKENS` (default 200_000).

Cuando los tokens estimados del transcript cruzan el umbral, el goal pasa
a `status=context_threshold` (status terminal, mismo plano que
`budget_exhausted`) y la tool **escribe el handoff automáticamente** vía
`serialize_handoff(session_id)`. La respuesta de la tool incluye
literalmente las dos acciones que el usuario debe ejecutar:

```
1. Teclea /clear para liberar contexto.
2. En la sesión nueva: apex_resume_session(session_id="<sid>")
```

El agente **debe** retransmitir ese mensaje sin reformular ni omitir el
session_id — es la única vía para que la sesión nueva rehidrate el estado.

**Coherencia con el hook `context-watch.py`**: los dos sistemas leen la
misma env. Si ya disparó el hook y el usuario no actuó, el goal acabará
disparándolo igual al siguiente `record_turn`. No es redundancia: el hook
avisa en cada prompt, el goal lo aplica al cerrar el turno.

## Cómo escribir un buen goal (contrato de 5 partes)

Un goal vago quema turnos sin aportar más que un prompt normal. Antes de
`start_goal`, define el contrato — es lo que hace el loop verificable:

1. **Objetivo** — una frase, un resultado concreto.
2. **Restricciones** — qué NO debe cambiar (API pública, libs, convenciones,
   archivos fuera de alcance).
3. **Comando de validación** — el shell exacto que prueba el progreso
   (`PYTHONPATH=lib .venv/bin/pytest tests/ -q`, `pnpm test`, ...).
4. **Condición de parada** — verificable: "para cuando X pase" O "cuando el
   siguiente cambio requiera decisión humana/de producto".
5. **Documentación** — una frase comprometiendo al agente a registrar cada
   cambio en `wiki/` / decisiones (nunca ADRs nuevos sin aprobación del
   usuario).

**Prohíbe el reward-hacking explícitamente** en el goal: "No borres, saltes,
debilites ni acotes tests para que el goal pase." Sin esto, el agente puede
gamear la condición de parada. Prohíbe también el scope creep: "No refactorices
código no relacionado. No añadas dependencias."

**Truco de meta-prompting (el de mayor palanca)**: los goals escritos a mano
sub-especifican. Pide a una segunda pasada (el propio agente con el código
cargado) que (1) inspeccione el repo, (2) saque a la superficie supuestos,
restricciones y edge cases ocultos, (3) emita el contrato de 5 partes. Ese
goal afinado rinde un orden de magnitud mejor que el improvisado.

## Reglas

- El juez **no ve el código**, sólo el goal + summary de últimos 5 turnos.
- Si grader bloquea una fase, el goal no puede declararse "done".
- Cualquier mensaje del usuario → pausar goal automáticamente.
- Goals activos persisten cross-session.
- **Siempre revisa el diff antes de mergear**: más autonomía = más código que
  validar, no menos. El juez verifica el goal, no la calidad línea a línea.

## Próximos pasos (Sprints 9+)

- Integración con `apex_resume_session` (Sprint 9): goals activos aparecen
  en el handoff a 40% de contexto.
- Stream de decisiones del juez al apex-hub `/live` (Sprint 8.3).
- Multi-goal paralelo (Sprint 12 con virtual office).
