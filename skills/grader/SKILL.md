---
name: grader
description: Evaluador outcome-based del cierre de fase. Reemplaza el checklist binario de flow-guardian por checks deterministas + juicio LLM cualitativo. Bloquea apex_set_phase si los outcomes reales no se cumplen.
---

# Grader (Sprint 8)

Outcome-based, no checklist. Inspirado en el Self-Healing Agent Harness de
CREAO y en /goal de Hermes — adaptado a la realidad operativa de APEX
(1 usuario, ~10 sesiones/semana → juez único Sonnet 4.6, no panel).

## Cuándo se invoca

Se ejecuta automáticamente:

- Antes de `apex_set_phase(N)` (vía hook `phase-gate.py`).
- Manualmente por el agente con la herramienta MCP `apex_grader_evaluate(phase)`.
- Al final de cada turno relevante dentro de `/apex:goal` (Sprint 8.2).

## Cómo funciona

```
gather_evidence(project_root, phase)
        │
        ▼
run_deterministic_checks(evidence)
        │
        ├── git_initialized? (fase ≥ 5)
        ├── tests_present? (fase ≥ 6)
        ├── os_detected? (fase ≥ 1)
        ├── no_emojis_in_frontend? (fase ≥ 2 y hay frontend)
        ├── schema_contracts? (fase ≥ 7)
        └── e2e_for_web_ui? (fase ≥ 8 y component_type incluye "web")
        │
        ▼
¿Algún issue BLOQUEANTE? (no_git_init, mock_data, no_e2e_for_ui, emoji)
        │
   sí ──┴── no
   │         │
   ▼         ▼
 BLOCK    Juicio LLM Sonnet 4.6 (si ANTHROPIC_API_KEY disponible)
            │
            ▼
   merge_verdicts(determinista, llm)
            │
            ▼
       Verdict final → context.db.add_verdict()
```

## Política de bloqueo

- Issues **bloqueantes**: `no_git_init`, `mock_data`, `no_e2e_for_ui`, `emoji_in_frontend`.
- Issues **avisos** (no bloquean pero bajan quality): `missing_tests`, `no_so_detection`, `no_schema_contract`, `no_cross_project_search`.
- El bloqueo determinista **nunca se relaja por el LLM**. El LLM puede subirlo, no bajarlo.

## Quality scale

| Quality | Cuándo |
|---|---|
| 4 excellent | Outcome verificable + tests pasan + cero issues |
| 3 good | Determinista pasa, LLM neutral, sin avisos |
| 2 acceptable | Avisos no-bloqueantes |
| 1 poor | Bloqueo determinista o LLM detecta cáscara/mock |

## Formas de invocar

```python
from grader import gather_evidence, evaluate_deterministic, evaluate_full

# Modo rápido (sin LLM, sin red)
evidence = gather_evidence(".", phase=5,
                           component_types=["web"],
                           decisions_metadata={"detected_os": "Linux"})
verdict = evaluate_deterministic(evidence)
print(verdict.should_block, verdict.issues)

# Modo completo (con LLM si hay API key, sino cae a determinista)
verdict = evaluate_full(evidence, use_anthropic=True)
```

Desde el MCP:

```
apex_grader_evaluate(phase=8, mode="full")
```

## Override manual

Si Vicente sabe que el bloqueo es falso positivo:

```
apex_set_phase(N, force=True)
```

Esto registra automáticamente un `apex_add_error` con motivo del override.
El grader aprende de la frecuencia de overrides para ajustar umbrales.

## No reemplaza al agente

El grader detecta **señales objetivas** (git, tests, schema, emojis,
Playwright). Para el juicio cualitativo del outcome (¿está mock?, ¿falta
contexto?, ¿es ambigua la salida?) sigue dependiendo del LLM. Por eso el
prompt del juez es self-contained y la salida es JSON estricto.

## Errores cross-project que bloquea automáticamente

| Lección | Issue code | Fase mínima |
|---|---|---|
| focusnow#1 (uname -s) | `no_so_detection` | 1 (aviso) |
| focusnow#2 (no emojis) | `emoji_in_frontend` | 2 (bloquea) |
| focusnow#3 (mock data) | `mock_data` (vía LLM) | 6/8 (bloquea) |
| focusnow#4 (git init) | `no_git_init` | 5 (bloquea) |
| tfg-tutor#5 (datos sin contrato) | `no_schema_contract` | 7 (aviso) |

## Próximos pasos (Sprint 9+)

- Persistir verdicts también al apex-hub vía `_debug_log` (Sprint 8.3, ya planificado).
- Tendencia por proyecto: ¿qué issue se repite más? Feed de `apex-doctor` (Sprint 13).
- Cliente Anthropic con prompt caching (reduce coste por verdict).
