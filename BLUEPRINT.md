# BLUEPRINT — APEX

> Snapshot del estado actual y arranque de la próxima sesión. Se
> sobrescribe en cada handoff. Última actualización: **2026-05-07**
> tras cierre de **Sprint 16.1 + 16.5**.

---

## Estado actual

- **Branch:** `main`
- **HEAD:** `ba4e306 feat(s16.5): get/set_advisor_constants con fallback a defaults`
- **Suite:** 501 verde (7s)
- **`git status`:** limpio
- **Origin:** `Everything up-to-date`
- **Sprint en curso:** **Sprint 16 — Advisor Feedback Loop** (rating
  implícito vía facets + escape hatch manual)

### Progreso S16 (blueprint v2)

| ID    | Subtarea                                                    | Estado | Tests | Suite delta |
|-------|-------------------------------------------------------------|--------|-------|-------------|
| S16.1 | Schema (`advice_outcomes`, `advisor_tuning_history`)        | ✅ `5bed398` | 8     | 484 → 492   |
| S16.5 | Migración constantes `advisor.py` → `project_meta`          | ✅ `ba4e306` | 9     | 492 → 501   |
| S16.2 | `lib/advisor_outcomes.py` + `apex_advisor_compute_outcomes` | 🔜 next     | (14)  | 501 → ~515  |
| S16.6 | `apex_rate_advice` (escape hatch) + validación              | pendiente   | (6)   |             |
| S16.3 | `lib/advisor_health.py` + `apex_advisor_health`             | pendiente   | (8)   |             |
| S16.4 | `lib/advisor_tuning.py` + `apex_advisor_apply_tuning`       | pendiente   | (12)  |             |
| S16.7 | Hook `advisor-outcome-watch.py`                             | pendiente   | (4)   |             |
| S16.8 | (Opcional) `skills/advisor-feedback/SKILL.md`               | pendiente   | (0)   |             |

Orden recomendado (§8 del blueprint): `S16.1 ✓ → S16.5 ✓ → **S16.2** →
S16.6 → S16.3 → S16.4 → S16.7 → S16.8`.

---

## Próximo paso (sesión nueva): S16.2

**Objetivo:** motor implícito que rellena `advice_outcomes` cruzando
`advisor_advice` con facets de `~/.claude/usage-data/facets/`.

### Entregables

1. **`lib/advisor_outcomes.py`** (~180 LoC):
   - `compute_outcomes(db_path, lookback_days=14, force=False) -> ComputeResult`
   - Lee `advisor_advice` reciente, asocia con sesión de facets vía
     `usage_data_reader.find_session_for_timestamp(advice.created_at,
     project_path, slack_minutes=5)`.
   - Si match: extrae `outcome`, `helpfulness`, `satisfaction`,
     `friction_keys` con count>0 desde `UsageFacets`.
   - Infiere `inferred_rating ∈ {useful, not_useful, unclear}` con
     heurística del blueprint §3.
   - INSERT en `advice_outcomes` con `assoc_method='temporal'`.
   - `UNIQUE (advice_id, assoc_method)` → idempotente.
   - `force=True` permite UPDATE en lugar de skip.
   - Si no hay facet match → skip (no row, próximo pase del hook S16.7
     reintenta).

2. **Tool MCP `apex_advisor_compute_outcomes(force=False, lookback_days=14)`**
   en `mcp/apex_server.py` (list_tools + dispatch). Total tools: 49 → **50**.

3. **`tests/test_advisor_outcomes.py`** (14 tests):
   - Asociación temporal con facet en rango.
   - Inferencia rating: `fully_achieved + essential` → `useful`.
   - Inferencia rating: `not_achieved + frustrated` → `not_useful`.
   - Inferencia rating: facets ausentes (sólo friction) → `unclear`.
   - Caso sin facet match → no crea row.
   - Idempotencia: misma llamada 2x no duplica.
   - `force=True` recomputa rating si cambian facets.
   - `lookback_days` filtra advices viejos.
   - Etc. (resto del catálogo §11).

### Heurística de inferencia (resumen del §3, no canónico)

```
useful     ← outcome ∈ {fully_achieved, mostly_achieved}
              AND helpfulness ∈ {essential, very_helpful}
              AND satisfaction ∉ {dissatisfied, frustrated}

not_useful ← outcome ∈ {not_achieved, partially_achieved}
              OR helpfulness ∈ {unhelpful, slightly_helpful}
              OR satisfaction ∈ {dissatisfied, frustrated}

unclear    ← cualquier otro caso (mixed/medio o señales contradictorias)
```

`unclear` se EXCLUYE del denominador del FP rate del auto-tuning S16.4
(es ausencia de señal, no señal negativa).

### Suite objetivo

501 → ~515 verde (+14 tests).

---

## Cómo arrancar la próxima sesión

```bash
cd ~/RoadToDevOps/apex
PYTHONPATH=lib .venv/bin/pytest tests/ -q       # 501 verde
git status                                       # limpio
git log --oneline -3                             # ba4e306 head
```

Y dentro de Claude Code:

```
apex_resume_session(session_id="b1d2e3f4-567")
Read .apex/sprints/sprint-16-advisor-feedback-loop-blueprint.md  # spec completa
Read BLUEPRINT.md                                                 # este doc
```

Empezar TDD de S16.2:
1. Red phase: escribir `tests/test_advisor_outcomes.py` con 14 tests
   fallando.
2. Green phase: implementar `lib/advisor_outcomes.py` + wiring tool.
3. Suite full → commit `feat(s16.2)` → push.

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
- `.apex/handoff/b1d2e3f4-567.md` — handoff de esta sesión (con contexto rico)
- `lib/advisor.py` — añadidas `get_advisor_constants` / `set_advisor_constants`
- `lib/context_db.py` — añadido schema S16
- `lib/usage_data_reader.py` — base de S16.2 (lee `~/.claude/usage-data/`)
- `tests/test_advice_outcomes_schema.py` — 8 tests S16.1
- `tests/test_advisor_constants_migration.py` — 9 tests S16.5

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
