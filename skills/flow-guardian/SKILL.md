---
name: flow-guardian
description: Vigilante de las 14 fases + gate 10.5. Delega la evaluación de outcomes al skill `grader` (Sprint 8.1) y enforces la regla absoluta de cross-project retrieval. NO usa checklist binario — el grader decide should_block según outcomes verificables.
---

# FlowGuardian — Vigilante de fases (v2, post Sprint 8)

## Cambio respecto a v1

La v1 era **checklist binario**: cada fase tenía sus `[ ] X completed`,
`[ ] Y verified`, y se podía marcar `completed` con cáscara/mock. Eso fue
la raíz que permitió incidentes tipo FocusNow#3.

La v2 **delega outcomes al grader** (`skills/grader/SKILL.md`) y se queda
como capa de orquestación + invariantes cross-project.

## Cuándo activar

SIEMPRE que se ejecute una acción dentro de un proyecto APEX. El hook
`SessionStart` ya prima esta skill al inicio. Antes de:

- Cambiar de fase (`apex_set_phase`)
- Tomar una decisión estructural (stack, arquitectura, diseño visual, UX,
  scraping, auth, deploy)
- Empezar la fase 11 (deploy)

## Tres responsabilidades

### 1. Verdict del grader antes de avanzar fase

```
Antes de apex_set_phase(N, status="completed" | "in_progress"):
  1. Ejecutar apex_grader_evaluate(phase=fase_a_cerrar, mode="deterministic")
  2. Si verdict.should_block:
     a. Mostrar al usuario los issues + razón
     b. NO llamar apex_set_phase. Atacar issues primero.
     c. Si el usuario insiste por motivo justificado:
        apex_set_phase(..., force=True, force_reason="...")
        (esto registra apex_add_error severity=high automáticamente)
  3. Si verdict pasa: apex_set_phase normalmente.
```

El **handler MCP** y el **hook PreToolUse `phase-gate.py`** ya enforcen
esto técnicamente — esta skill describe el flujo para que el agente lo
entienda y lo respete.

### 2. Cross-project retrieval obligatorio (regla absoluta #18)

ANTES de proponer una decisión de stack, arquitectura, diseño visual, UX,
scraping, auth, deploy o cualquier elección estructural, ejecutar:

```
apex_search_cross_project(query="<términos relevantes>")
```

Procesar el resultado:

- **Errores** previos: NO los repitas. Explica al usuario qué error
  ocurrió en qué proyecto y por qué no vamos a repetirlo.
- **Decisiones vigentes**: propónlas como primera opción salvo contexto
  contraindicado.
- **Decisiones invalidadas**: explícitamente evita el camino invalidado.

Si la tool devuelve "hub.db no disponible":
- Continuar es opcional pero AVISAR explícitamente al usuario.
- Registrar `apex_add_error(source="claude", description="hub.db offline en sesión", severity="medium")`.
- Sugerir lanzar `apex-hub` para habilitar segundo cerebro.

### 3. Gate 10.5 (AgentArmor) bloqueante para fase 11

Antes de cualquier `apex_set_phase(11, ...)`:

```
1. apex_grader_evaluate(phase=10) — fase 10 debe estar PASS
2. apex_security_gate(...)         — 8 capas L1-L8 deben estar 'passed'
3. Si alguna no es 'passed' → bloquear con diagnóstico
```

El handler MCP de `apex_set_phase` consulta `grader_verdicts`. Si la fase
10 tiene verdict `should_block=true`, la transición a 11 falla. Esto
cierra el GAP CRIT-C del audit pre-Sprint 8.

## Política de bloqueo (resumen)

| Origen del bloqueo | Cómo enforce |
|---|---|
| Checks deterministas (git, tests, emojis, schema, e2e) | Grader → handler `apex_set_phase` → hook `phase-gate.py` (doble red) |
| Juicio LLM (mock_data, hallucination, ambiguous_outcome) | Grader modo `full` → handler |
| Gate AgentArmor 10.5 | `apex_security_gate` + grader verdict de fase 10 |
| Cross-project retrieval omitido | Esta skill (orquestación) — el agente debe llamar `apex_search_cross_project` antes de decisiones estructurales |

## Antipatterns que esta skill detecta

1. Marcar fase `completed` sin haber llamado `apex_grader_evaluate`.
2. Usar `force=true` sin `force_reason` documentado.
3. Avanzar a fase 11 sin gate 10.5 passed.
4. Tomar decisión de stack sin `apex_search_cross_project` previa.
5. Continuar trabajo cuando hub.db está offline sin avisar al usuario.

## Skills relacionadas

- `skills/grader/SKILL.md` — evaluador outcome-based (delegación principal)
- `skills/apex-goal/SKILL.md` — bucle persistente con turn-budget
- `skills/security-audit/SKILL.md` — AgentArmor 8 capas
- `skills/iterate/SKILL.md` — fase 12 (in_progress perpetuo)
- `skills/code-review/SKILL.md` — review estilo staff engineer

## Próximos pasos (post Sprint 8)

- Sprint 9 (handoff a 40%): el flow-guardian inyecta el verdict pendiente
  en el handoff a la siguiente sesión.
- Sprint 11 (browser-trace): traces capturados se adjuntan como evidence
  al grader en fases 8-11.
- Sprint 13 (apex-doctor): clusters de overrides `force=true` se
  promueven a issues en hub.db automáticamente.
