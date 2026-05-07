# BLUEPRINT — APEX

> Snapshot del estado actual y arranque de la próxima sesión. Se
> sobrescribe en cada handoff. Última actualización: **2026-05-07**
> tras cierre de **Sprint 16.1 + 16.5 + 16.2**.

---

## Estado actual

- **Branch:** `main`
- **HEAD:** `feat(s16.2): advisor_outcomes motor implícito + tool MCP` (pendiente commit)
- **Suite:** 515 verde (7.5s)
- **Tools MCP:** 50 (49 → 50 con `apex_advisor_compute_outcomes`)
- **`git status`:** working dir con cambios S16.2 (lib + tests + mcp)
- **Sprint en curso:** **Sprint 16 — Advisor Feedback Loop** (rating
  implícito vía facets + escape hatch manual)

### Progreso S16 (blueprint v2)

| ID    | Subtarea                                                    | Estado      | Tests | Suite delta |
|-------|-------------------------------------------------------------|-------------|-------|-------------|
| S16.1 | Schema (`advice_outcomes`, `advisor_tuning_history`)        | ✅ `5bed398` | 8     | 484 → 492   |
| S16.5 | Migración constantes `advisor.py` → `project_meta`          | ✅ `ba4e306` | 9     | 492 → 501   |
| S16.2 | `lib/advisor_outcomes.py` + `apex_advisor_compute_outcomes` | ✅ pending commit | 14    | 501 → 515   |
| S16.6 | `apex_rate_advice` (escape hatch) + validación              | 🔜 next     | (6)   |             |
| S16.3 | `lib/advisor_health.py` + `apex_advisor_health`             | pendiente   | (8)   |             |
| S16.4 | `lib/advisor_tuning.py` + `apex_advisor_apply_tuning`       | pendiente   | (12)  |             |
| S16.7 | Hook `advisor-outcome-watch.py`                             | pendiente   | (4)   |             |
| S16.8 | (Opcional) `skills/advisor-feedback/SKILL.md`               | pendiente   | (0)   |             |

Orden recomendado (§8 del blueprint): `S16.1 ✓ → S16.5 ✓ → S16.2 ✓ →
**S16.6** → S16.3 → S16.4 → S16.7 → S16.8`.

---

## Próximo paso (sesión nueva): S16.6 — escape hatch manual

**Objetivo:** escape hatch manual `apex_rate_advice(advice_id, rating,
reason)` para casos donde el rating implícito no llega (sesión
globalmente buena con una card específicamente ruidosa, o `/insights`
sin correr).

### Entregables (blueprint §4 + §11)

1. **`apex_rate_advice` en `lib/advisor.py`** (~60 LoC):
   - Inserta fila en `advice_outcomes` con `assoc_method='manual'`.
   - `rating ∈ {'useful', 'not_useful'}` (sin `unclear` para forzar
     señal explícita).
   - `reason` obligatoria (>=10 chars).
   - `manual_reason` se guarda en la columna correspondiente.
   - Coexiste con outcome temporal por la `UNIQUE (advice_id,
     assoc_method)` del schema.
   - FK inválida → `ValueError("advice_id no existe")`.

2. **Tool MCP `apex_rate_advice`** (49 → 51 tools tras S16.2 + S16.6).

3. **`tests/test_apex_rate_advice.py`** (6 tests):
   - Inserta manual outcome con reason válida.
   - Reason vacía o < 10 chars → ValueError.
   - FK inválida (advice_id inexistente) → ValueError.
   - UNIQUE compuesto permite coexistir con outcome temporal previo.
   - Valida rating enum (rechaza `'unclear'` y `'foo'`).
   - Idempotencia: dos manuales sobre el mismo advice → segundo falla
     o sobreescribe (decisión: sobreescribir vía `INSERT OR REPLACE`
     respetando UNIQUE).

### Suite objetivo

515 → ~521 verde (+6 tests).

---

## Cierre de S16.2 (esta sesión)

- `lib/advisor_outcomes.py` (~245 LoC con docstrings + helpers).
- `tests/test_advisor_outcomes.py` (14 tests: 4 heurística pura + 10
  integración compute).
- `mcp/apex_server.py`: import `_advisor_outcomes`, tool definition,
  dispatch handler con resumen `computed/skipped/no_facet_yet/force_updated`.
- Heurística §3 implementada literal: `not_useful` ante CUALQUIER señal
  negativa (orden de checks importa); `useful` solo si outcome+helpfulness
  positivos y satisfaction no negativa; `unclear` el resto.
- `_derive_satisfaction(counts)`: prioridad `frustrated > dissatisfied >
  satisfied > likely_satisfied > mixed > ""`.
- `_friction_keys_active(counts)`: solo keys con count>0, ordenadas por
  count desc + key asc para reproducibilidad.
- `_parse_db_timestamp`: acepta tanto `'YYYY-MM-DD HH:MM:SS'` (default
  SQLite) como ISO8601.

---

## Cómo arrancar la próxima sesión

```bash
cd ~/RoadToDevOps/apex
PYTHONPATH=lib .venv/bin/pytest tests/ -q       # 515 verde
git status                                       # limpio
git log --oneline -3                             # commit s16.2 head
```

Y dentro de Claude Code:

```
apex_resume_session(session_id="b1d2e3f4-567")
Read .apex/sprints/sprint-16-advisor-feedback-loop-blueprint.md  # spec completa
Read BLUEPRINT.md                                                 # este doc
```

Empezar TDD de S16.6:
1. Red phase: escribir `tests/test_apex_rate_advice.py` con 6 tests
   fallando.
2. Green phase: añadir `rate_advice()` en `lib/advisor.py` + wiring
   tool MCP `apex_rate_advice`.
3. Suite full → commit `feat(s16.6)` → push.

---

## Decisiones del Sprint 16 (acumuladas)

| Decisión | Razón |
|----------|-------|
| Path B (rating implícito vía facets) como camino principal | Cero fricción TDAH + 100 sesiones de facets ya acumuladas + reuso del patrón A5/A6 del Sprint 13.9. |
| Path A (manual) como escape hatch | Cards en sesiones globalmente buenas pasarían inadvertidas sin manual override. |
| 3 enums (`useful` / `not_useful` / `unclear`) en lugar de 2 | `unclear` no es rating, es ausencia de señal — se excluye del denominador del FP rate. |
| Solo enums, nunca texto libre | Privacidad (R5): facets pueden contener briefs/código sensible. |
| Cooldown 7 días entre auto-tunings | Anti-oscilación. |
| Mín 20 outcomes/categoría | Mediana FP rate estable; <20 = ruido. |
| `UNIQUE (advice_id, assoc_method)` | Permite coexistir 1 implícito + 1 manual por advice sin colisión. |
| Constantes en `project_meta.advisor_constants` (JSON) | Auto-tuning S16.4 muta valores sin tocar código; fallback a defaults si falla. |
| Constantes con keys lowercase sin prefijo `ADVISOR_` | Namespace ya es `advisor.py`; keys son contractuales con S16.4. |

---

## Archivos clave de la sesión

- `.apex/sprints/sprint-16-advisor-feedback-loop-blueprint.md` — spec completa S16 v2
- `.apex/sprints/sprint-17-vfs-and-sprint-18-curator-blueprint.md` — siguientes sprints
- `.apex/handoff/b1d2e3f4-567.md` — handoff de la sesión origen (contexto rico)
- `lib/advisor.py` — añadidas `get_advisor_constants` / `set_advisor_constants` (S16.5)
- `lib/advisor_outcomes.py` — motor implícito de outcomes (S16.2, NUEVO)
- `lib/context_db.py` — schema S16 (advice_outcomes + advisor_tuning_history)
- `lib/usage_data_reader.py` — base reusada por S16.2
- `mcp/apex_server.py` — tool `apex_advisor_compute_outcomes` (S16.2)
- `tests/test_advice_outcomes_schema.py` — 8 tests S16.1
- `tests/test_advisor_constants_migration.py` — 9 tests S16.5
- `tests/test_advisor_outcomes.py` — 14 tests S16.2 (NUEVO)

---

## Lecciones a respetar en la próxima sesión

1. **Auditar antes de presentar decisiones.** Cuando presente "puntos
   a decidir" tras un blueprint, distinguir explícitamente entre
   decisiones ya tomadas que estoy modificando vs genuinamente
   undefined. La sesión origen elevó silenciosamente niveles de
   rating de 2 a 3; Vicente lo detectó.

2. **Sprint por sprint, verifica antes de cerrar.** `pytest -q` antes
   de declarar verde; commit con mensaje conventional; push tras cada
   sub-sprint cerrado.

3. **No emojis en código ni docs**, español con tildes y eñes.

4. **Cuando el grader o tests fallen, no bypasear** — root cause y
   commit de fix limpio.
