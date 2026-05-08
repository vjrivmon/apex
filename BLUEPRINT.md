# BLUEPRINT — APEX

> Snapshot del estado actual y arranque de la próxima sesión. Se
> sobrescribe en cada handoff. Última actualización: **2026-05-08**
> tras cierre de **Sprint 16** y arranque de **Sprint 17**.

---

## Estado actual

- **Branch:** `main` (limpia, alineada con `origin/main`)
- **HEAD:** `bdddf6b feat(s16.7): advisor-outcome-watch hook UserPromptSubmit`
- **Suite:** 545 verde (7.95s)
- **Tools MCP:** 53
- **`git status`:** árbol limpio
- **Sprint en curso:** **Sprint 17 — VirtualFS cross-project read-only**
  (mount lógico RO `/projects/<slug>/...` + `/lessons/...` + `/vault/`
  navegable con primitivas UNIX)

### Progreso S16 (cerrado en su núcleo)

| ID    | Subtarea                                                    | Estado            | Tests | Suite delta |
|-------|-------------------------------------------------------------|-------------------|-------|-------------|
| S16.1 | Schema (`advice_outcomes`, `advisor_tuning_history`)        | ✅ `5bed398`       | 8     | 484 → 492   |
| S16.5 | Migración constantes `advisor.py` → `project_meta`          | ✅ `ba4e306`       | 9     | 492 → 501   |
| S16.2 | `lib/advisor_outcomes.py` + `apex_advisor_compute_outcomes` | ✅ `e6844c8`       | 14    | 501 → 515   |
| S16.6 | `apex_rate_advice` (escape hatch) + validación              | ✅ `4bf3624`       | 6     | 515 → 521   |
| S16.3 | `lib/advisor_health.py` + `apex_advisor_health`             | ✅ `8b610c5`       | 8     | 521 → 529   |
| S16.4 | `lib/advisor_tuning.py` + `apex_advisor_apply_tuning`       | ✅ `3107c52`       | 12    | 529 → 541   |
| S16.7 | Hook `advisor-outcome-watch.py`                             | ✅ `bdddf6b`       | 4     | 541 → 545   |
| S16.8 | (Opcional) `skills/advisor-feedback/SKILL.md`               | 🔄 deferido       | (0)   |             |

S16.8 deferido por decisión explícita 2026-05-08 (deuda fría tolerable;
la skill se redactará cuando haya datos reales del feedback loop sin
bloquear S17). Sprint 16 cerrado en su núcleo (7/8 subtareas, todas las
de código + tests).

---

## Próximo paso (sesión actual): Sprint 17 — VirtualFS cross-project

S16 cerrado en núcleo (S16.8 deferido como deuda fría). Decisión 2026-
05-08: respetar **orden estricto del roadmap** (S17 → S18 → S19) en
lugar de saltar a S19 por urgencia de Gap F (gitleaks). El gap F sigue
siendo crítico pero puede esperar al cierre ordenado de S17/S18.

### Subtareas S17 (orden TDD)

| ID     | Subtarea                                                  | LoC est. | Tests |
|--------|-----------------------------------------------------------|----------|-------|
| S17.1  | Schema `vfs_render_cache` + `vfs_query_log` + auto-mig    | ~80      | 4     |
| S17.2  | Path resolver + RBAC whitelist (`vfs_allowed_roots`)      | ~120     | 6     |
| S17.3  | `VirtualFS.ls` + `cat` sobre mounts reales (RO/EROFS)     | ~100     | 6     |
| S17.4  | `VirtualFS.find` + glob                                   | ~80      | 4     |
| S17.5  | `vfs_grep` + flags `-i/-r/-n/-l/-E` + FTS5 pre-filter     | ~150     | 6     |
| S17.6  | `vfs_sql_render`: errors/skills-history/lessons → md      | ~200     | 5     |
| S17.7  | Render cache + invalidation                               | ~80      | 3     |
| S17.8  | `apex_vfs_exec` parser (whitelist, sin shell injection)   | ~120     | 5     |
| S17.9  | Wiring 4 tools MCP en `apex_server.py`                    | ~60      | 4     |
| S17.10 | Commit + actualizar BLUEPRINT/CLAUDE.md/handoff           | —        | —     |

Suite objetivo S17: **545 → ~588 verde** (+43 tests netos).
Tools MCP: **53 → 57** (`apex_vfs_exec`, `apex_vfs_ls`, `apex_vfs_cat`,
`apex_vfs_grep`).

### Tras S17 cierra: S18 → S19

- **S18 — Granite Curator opcional** (opt-in vía `APEX_CURATOR_MODEL`),
  blueprint en `.apex/sprints/sprint-17-vfs-and-sprint-18-curator-blueprint.md`.
- **S19 — Advent Integration** (Tier 1+2+4: gitleaks crítico, CLAUDE.md
  APEX-aware, slash commands cortos, PreCompact hook, export_session,
  rules condicionales). Blueprint en `.apex/sprints/sprint-19-advent-integration-blueprint.md`.

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

## Sprints encolados tras S17

| Sprint | Foco | Blueprint |
|--------|------|-----------|
| **S17** | **VirtualFS cross-project** (en curso) | `.apex/sprints/sprint-17-vfs-and-sprint-18-curator-blueprint.md` |
| S18 | Granite Curator opt-in | (mismo archivo que S17) |
| S19 | Advent Integration (Tier 1+2+4) — gitleaks crítico, CLAUDE.md auto, slash commands cortos, PreCompact hook, `apex_export_session`, rules condicionales | `.apex/sprints/sprint-19-advent-integration-blueprint.md` |

Decisión 2026-05-08: orden estricto **S17 → S18 → S19** en lugar de
priorizar S19 por urgencia. S19 sigue manteniendo Gap F (gitleaks)
como prioridad cero dentro del propio sprint. Tier 3 (Gap K, GH
Action APEX-aware) diferido a S20+ hasta tener colaboradores.

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
