# BLUEPRINT — APEX

> Snapshot del estado actual y arranque de la próxima sesión. Se
> sobrescribe en cada handoff. Última actualización: **2026-05-08**
> tras cierre de **Sprint 16.7**.

---

## Estado actual

- **Branch:** `main`
- **HEAD:** `feat(s16.4): apex_advisor_apply_tuning auto-tuner determinista` (S16.7 pendiente commit)
- **Suite:** 545 verde (10.4s)
- **Tools MCP:** 53
- **`git status`:** sin track → `.claude/hooks/advisor-outcome-watch.py`
  + `tests/test_advisor_outcome_hook.py` + edit en `.claude/settings.json`
- **Sprint en curso:** **Sprint 16 — Advisor Feedback Loop** (rating
  implícito vía facets + escape hatch manual)

### Progreso S16 (blueprint v2)

| ID    | Subtarea                                                    | Estado            | Tests | Suite delta |
|-------|-------------------------------------------------------------|-------------------|-------|-------------|
| S16.1 | Schema (`advice_outcomes`, `advisor_tuning_history`)        | ✅ `5bed398`       | 8     | 484 → 492   |
| S16.5 | Migración constantes `advisor.py` → `project_meta`          | ✅ `ba4e306`       | 9     | 492 → 501   |
| S16.2 | `lib/advisor_outcomes.py` + `apex_advisor_compute_outcomes` | ✅ `e6844c8`       | 14    | 501 → 515   |
| S16.6 | `apex_rate_advice` (escape hatch) + validación              | ✅ `4bf3624`       | 6     | 515 → 521   |
| S16.3 | `lib/advisor_health.py` + `apex_advisor_health`             | ✅ `8b610c5`       | 8     | 521 → 529   |
| S16.4 | `lib/advisor_tuning.py` + `apex_advisor_apply_tuning`       | ✅ `3107c52`       | 12    | 529 → 541   |
| S16.7 | Hook `advisor-outcome-watch.py`                             | ✅ pending commit | 4     | 541 → 545   |
| S16.8 | (Opcional) `skills/advisor-feedback/SKILL.md`               | pendiente         | (0)   |             |

Orden recomendado (§8 del blueprint): `S16.1 ✓ → S16.5 ✓ → S16.2 ✓ →
S16.6 ✓ → S16.3 ✓ → S16.4 ✓ → S16.7 ✓ → **S16.8** (opcional)`.

---

## Próximo paso (sesión nueva): commit S16.7 + decidir S16.8

### Pendiente inmediato (1 minuto)

Hay un commit S16.7 staged sin cerrar (la sesión anterior cerró por
error la terminal antes del commit). Working tree:

```
.claude/hooks/advisor-outcome-watch.py    (nuevo, +178L)
.claude/settings.json                     (3 hooks UserPromptSubmit → 4)
tests/test_advisor_outcome_hook.py        (nuevo, 4 tests)
BLUEPRINT.md                              (este archivo, actualizado)
```

Acción:

```bash
cd ~/RoadToDevOps/apex
PYTHONPATH=lib .venv/bin/pytest tests/ -q       # confirmar 545 verde
git status                                       # 4 archivos staged
git commit -m "feat(s16.7): advisor-outcome-watch hook UserPromptSubmit"
git push
```

Mensaje de commit recomendado:

```
feat(s16.7): advisor-outcome-watch hook UserPromptSubmit

- .claude/hooks/advisor-outcome-watch.py: high-water mark en
  project_meta.outcome_watch_prompt_count, cada N=10 prompts ejecuta
  compute_outcomes(lookback=14d) + apply_tuning(dry_run=True) con
  timeout 3s. Inyecta additionalContext si hay propuestas de tuning
  o si facets_freshness > 7d (sugerir /insights). Nunca bloquea.
- tests/test_advisor_outcome_hook.py: 4 tests (counter increment,
  silent below threshold, emite proposal en threshold, no bloquea
  con stdin corrupto).
- .claude/settings.json: registra el hook como tercer UserPromptSubmit.
- BLUEPRINT.md: marca S16.7 ✓, suite 545 verde.

Suite: 541 → 545 verde.
```

### Decisión a tomar antes de seguir: ¿S16.8 ahora o saltar a S17?

`S16.8` es la skill opcional `skills/advisor-feedback/SKILL.md` (~80
LoC, 0 tests). El blueprint v2 §7 la marca opcional. Dos caminos:

- **A)** Cerrar S16.8 con la skill y declarar Sprint 16 cerrado
  oficialmente (~30 min: redactar SKILL.md con 4 triggers, anti-
  patrones, puente APEX al Advisor + escape hatch).
- **B)** Saltar S16.8 (declarar Sprint 16 cerrado en su núcleo) y
  arrancar **Sprint 17 — VirtualFS cross-project** o **Sprint 19 —
  Advent Integration** (Tier 1+2+4, gitleaks crítico).

Recomendación: **B** (saltar). La skill es deuda fría; S19 incluye
gitleaks como Gap F crítico (incidente de leak ya documentado en
`hub.db`). S16.8 se puede recuperar más adelante sin coste.

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

## Sprints encolados tras S16

| Sprint | Foco | Blueprint |
|--------|------|-----------|
| S17 | VirtualFS cross-project | `.apex/sprints/sprint-17-vfs-and-sprint-18-curator-blueprint.md` |
| S18 | Granite Curator opt-in | (mismo archivo que S17) |
| **S19** | **Advent Integration (Tier 1+2+4)** — gitleaks template, `CLAUDE.md` auto, slash commands cortos, PreCompact hook, `apex_export_session`, project rules condicionales, docs UX | **`.apex/sprints/sprint-19-advent-integration-blueprint.md`** (planificado 2026-05-08) |

S19 nace del análisis `docs/APEX-vs-ADVENT-improvements.md`. **Pre-requisito:** S16 cerrado. Tier 3 (Gap K, GH Action APEX-aware) diferido hasta tener colaboradores.

---

## Archivos clave de la sesión

- `.apex/sprints/sprint-16-advisor-feedback-loop-blueprint.md` — spec completa S16 v2
- `.apex/sprints/sprint-17-vfs-and-sprint-18-curator-blueprint.md` — S17 + S18
- `.apex/sprints/sprint-19-advent-integration-blueprint.md` — S19 (mejoras Advent)
- `docs/APEX-vs-ADVENT-improvements.md` — análisis comparativo fuente
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
