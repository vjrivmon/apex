# APEX — Auditoría pre-Sprint 8

**Fecha:** 2026-05-03
**Autor:** Claude (ultrathink, sesión 6041+)
**Branch:** `main` · diff pendiente trivial (`mcp/apex_server.py` añade campo `project` al debug log)

## Estado del repo

| Capa | Conteo | Estado |
|---|---|---|
| Fases | 16 archivos (00–14 + 10.5 + README) | Estructura sólida |
| Reglas globales | 3 archivos (absolute, errors, ux-verification) | Bien escritas, sin enforcement |
| Skills | 19 directorios; **17 con SKILL.md, 2 vacíos** (implement, verify) | Deuda visible |
| MCP tools | 24 herramientas registradas | 4 con tests, 20 sin tests |
| Hooks | 2 (`session-start.py`, `weekly-design-lint.py`) | Faltan 3 para roadmap |
| `lib/` módulos | 11 archivos · 3.925 líneas | Cobertura desigual |
| Tests | 4 archivos (`test_context_db`, `_reverse_engineer`, `_second_brain`, `_security_gate`) | Cubre 4 de 11 módulos |

---

## 0. Hallazgos CRÍTICOS (Sprint 8 P0)

| ID | Hallazgo | Origen | Acción |
|---|---|---|---|
| CRIT-A | **flow-guardian es checklist binario, no outcome-based.** Es la raíz que permitió FocusNow#3 (frontend mock declarado completo). | `skills/flow-guardian/SKILL.md` líneas de criterios `[ ] Idea cuestionada`, `[ ] Tests pasando`, etc. | Reescribir como **Grader** que evalúa evidence + outcome con Sonnet 4.6. |
| CRIT-B | **20 reglas absolutas escritas, 0 con enforcement técnico.** Dependen del agente recordándolas. La regla 11 ("Playwright antes de presentar") y la 10 ("uname -s antes de stack") fueron las que falló FocusNow. | `commands/rules/absolute-rules.md` | Cada regla absoluta → un check programático invocado por el Grader. |
| CRIT-C | **Gate 10.5 no bloquea técnicamente fase 11.** El criterio dice "requiere passed" pero `apex_set_phase(11)` no consulta el verdict de AgentArmor. | `mcp/apex_server.py` (apex_set_phase no llama a apex_security_gate). Confirmado en GAP-11-1 del agente A. | Bloquear `apex_set_phase` si fase pedida es 11 y `security_gate.passed != True`. |
| CRIT-D | **2 skills vacíos en repo** (`skills/implement/`, `skills/verify/` sin SKILL.md). Deuda hace 4+ semanas. | `ls -la skills/implement/ skills/verify/` (vacíos) | Reciclar: `implement` → `grader` (Sprint 8) o poblarlos. `verify` → poblar como skill de fase 9. |
| CRIT-E | **Hub recibe NADA.** Hub v2 expone `POST /api/live/event` pero `_debug_log()` no lo llama. Toda la actividad de /apex se pierde. | Auditoría apex-hub: GAP-7 y GAP-8. `apex_search_cross_project` no implementado. | Sprint 8 sub-paso: `_debug_log()` POSTea al endpoint del Hub. Y crear endpoint `/api/hub/search-cross-project`. |

---

## 1. Hallazgos MEDIOS (Sprints 9-11)

| ID | Hallazgo | Sprint |
|---|---|---|
| MED-1 | Fases 5-6 completables sin git init y sin tests unitarios. E2E demasiado tarde (fase 9). | S8 (subir a CRIT) |
| MED-2 | Fase 2 acepta mockups Pencil sin verificar que el UX se implementa. Sin baseline E2E. | S10 (DESIGN.md) |
| MED-3 | Fase 8 acepta Streamlit como "validación" para producto web. No cuenta como E2E real. | S8 |
| MED-4 | Datos entre adapters (fase 7) y casos de uso (fase 8) sin schema contracts (Pydantic). tfg-tutor#5 antecedente. | S8 |
| MED-5 | `weekly-design-lint.py` no es lint real, sólo deja una nota. No bloquea ni detecta. | S10 |
| MED-6 | 20 de 24 MCP tools sin tests (`apex_search`, `apex_set_phase`, `apex_log_session`, …). | S8 (subset) |
| MED-7 | `commands/apex.md` tabla de tools no incluye `apex_search_cross_project` ni `apex_reverse_*` ni `apex_log_session`. Doc desincronizada con código. | S8 |
| MED-8 | CLAUDE.md dice "12 skills" — son 19. CLAUDE.md desactualizado. | S8 (chore) |
| MED-9 | `apex_search_cross_project` declarada (línea 696) pero según hub-audit NO implementada en backend del Hub. Devuelve "offline". | S8 |
| MED-10 | Cross-project retrieval (regla absoluta #18) sólo se invoca desde flow-guardian para "stack/arquitectura". Otras decisiones no lo usan. | S8 |

## 2. Hallazgos BAJOS (Sprints 12-13)

- `lib/embeddings.py` (128L) — sin uso documentado, sin tests. ¿Stub abandonado?
- `lib/synthesis.py` — funciones `dream_deep` y density-trigger no se invocan desde MCP automáticamente, sólo bajo demanda.
- Coverage thresholds (80% domain / 60% global) sin diferenciación por tipo de archivo.
- Sin Pagination en `apex_search` (límite 100 hardcoded).
- Templates AgentArmor (L1-L8) tienen checklist subjetivo sin criterios binarios.

---

## 3. Capa: Reglas globales

### 3.1 absolute-rules.md (20 reglas)

Robustas y exhaustivas. **Mapeo a enforcement técnico** propuesto:

| Regla | Concepto | Enforcement actual | Enforcement Sprint 8 |
|---|---|---|---|
| 1 | ToolSearch("apex") al inicio | Texto | Hook SessionStart hace prime |
| 5 | Nunca emojis | `ux-verification.md` lo menciona | Grader: regex `[\U0001F300-\U0001FAFF]` en frontend |
| 7 | Nunca declarar fase completa sin sub-pasos | flow-guardian textual | **Grader bloqueante** |
| 9 | Backend-first | Texto | Grader: si fase 8 cierra sin endpoint POST verificado → block |
| 10 | uname -s antes de stack | Texto | Grader fase 1: `decisions.metadata.detected_os` requerido |
| 11 | Playwright antes de presentar | `ux-verification.md` cita Playwright | Grader fase 8/11: requiere screenshot adjunto en evidence |
| 14 | Nunca inventar diseño | Texto | Grader fase 2: requiere referencia a DESIGN.md (Sprint 10) |
| 18 | Cross-project obligatorio | flow-guardian (parcial) | Grader: cualquier `apex_add_decision` obliga search previa |
| 19 | Español con tildes | `ux-verification.md` | Grader: regex de tildes/eñes en strings UI |

### 3.2 errors-to-avoid.md (17 errores)

Cubre los 5 críticos cross-project (focusnow#1-4 + tfg-tutor#5). **Sólo 1 tiene check técnico** (emojis vía `ux-verification.md`). Los otros 16 dependen del agente recordándolos.

### 3.3 ux-verification.md

Bien diseñado: cubre spacing 16px, touch 44px, contraste WCAG AA, Fitts' Law, emojis, tildes, ancho editorial. **Pero no se invoca automáticamente en transición de fase.** Es texto que el agente debe acordarse de aplicar.

**Acción Sprint 8:** Grader llama a `ux-verification` programáticamente cuando fase = 2, 8 ó 11.

---

## 4. Capa: Hooks

### 4.1 session-start.py (✅ vivo)
Inyecta 5 lecciones críticas cross-project desde `apex-hub/data/hub.db`. Verificado funcionando (memoria 2020).

### 4.2 weekly-design-lint.py (⚠️ no es lint real)
Rota 3 URLs/semana de `LIBRARY` (18 URLs). Escribe nota en wiki, no detecta nada. Acción S10: convertir en lint real (compara DESIGN.md actual contra principios).

### 4.3 Hooks que faltan según roadmap

- `phase-gate.py` (Sprint 8) — `PreToolUse` matcher `apex_set_phase`: bloquea si grader devuelve `should_block`.
- `pre-tool-filter.py` (Sprint 9) — `PostToolUse`: comprime outputs de Bash/Playwright a SQLite, devuelve resumen al contexto.
- `context-watch.py` (Sprint 9) — Periódico: a 40% de contexto, escribe handoff a `.apex/handoff/{session}.md`.

---

## 5. Capa: MCP tools (24)

Lista completa con cobertura:

| Tool | Línea | Test | Uso desde apex.md |
|---|---|---|---|
| apex_get_context | 405 | ✅ | ✅ |
| apex_init_project | 420 | ✅ | ✅ |
| apex_set_phase | 434 | ✅ | ✅ |
| apex_add_decision | 447 | ✅ | ✅ |
| apex_invalidate_decision | 466 | ✅ | ✅ |
| apex_add_error | 478 | ✅ | ✅ |
| apex_add_component | 493 | ✅ | ✅ |
| apex_update_component | 510 | ✅ | ✅ |
| apex_add_next_step | 522 | ✅ | ✅ |
| apex_complete_step | 535 | ✅ | ✅ |
| apex_search | 546 | ✅ | ✅ |
| apex_set_portfolio_meta | 563 | ❌ | ✅ |
| apex_portfolio_draft | 584 | ❌ | ✅ |
| apex_security_gate | 602 | ✅ (test_security_gate) | ✅ |
| apex_scaffold_devops | 619 | ❌ | ✅ |
| apex_ingest_source | 645 | ❌ | ✅ |
| apex_lint_second_brain | 664 | ❌ | ✅ |
| apex_synthesize | 681 | ❌ | ✅ |
| apex_search_cross_project | 696 | ❌ | ❌ (no listada en tabla apex.md) |
| apex_log_session | 723 | ❌ | ❌ (no listada) |
| apex_wiki_add | 736 | ❌ | ✅ |
| apex_reverse_scan | 751 | ✅ (test_reverse_engineer) | ✅ (apex-reverse.md) |
| apex_reverse_plan | 772 | ✅ | ✅ |
| apex_onboard_apply | 789 | ✅ | ✅ |

**Tools que el Sprint 8 añadirá:**
- `apex_grader_evaluate(phase, evidence)` → `{quality, issues[], should_block, reasoning}`
- `apex_goal_loop(goal, turn_budget)` → bucle supervisor estilo Hermes
- `apex_resume_session(session_id)` → rehidrata desde handoff (Sprint 9)

---

## 6. Capa: Skills (19)

| Skill | Estado | Fase | Acción Sprint 8 |
|---|---|---|---|
| socratic | live | 0 | Mantener |
| brainstorming | live | 0-4 | Mantener |
| architect | live | 1 | Mantener |
| tools-integration | live | 2-8 | Mantener |
| design-research | live | 2 | Mantener (S10 expand) |
| brand-identity | live | 2 | Mantener |
| design-system | live | 2 | Mantener (S10 expand DESIGN.md) |
| **flow-guardian** | live, **CHECKLIST** | siempre | **REESCRIBIR a outcome-based** |
| **implement** | **VACÍO** | 6-8 | **Reciclar como `grader`** |
| **verify** | **VACÍO** | 9 | **Poblar como skill de tests/coverage real** |
| iterate | live | 12 | Mantener |
| code-review | live | 8-10 | Mantener |
| security-audit | live | 10/10.5 | Mantener |
| devops | live | 11 | Mantener |
| monitor | live | 13 | Mantener |
| portfolio-publisher | live | 14 | Mantener |
| second-brain | live | transversal | Mantener |
| onboard-existing | live | onboarding | Mantener |
| reverse-engineer | live | onboarding | Mantener |

**Skills nuevas Sprint 8-13:**
- `grader` (S8) — reciclando `implement/`
- `apex-goal` (S8)
- `handoff` (S9)
- `browser-trace` (S11)
- `meta-forge` (S11)
- `apex-doctor` (S13)

---

## 7. Capa: Fases (16)

Tabla síntesis (tipo de criterios). Detalle por fase en agente A:

| Fase | Tipo criterios | Top gap | Acción S8 |
|---|---|---|---|
| 00 socratic | outcomes | sin criterio "suficiente investigación" | refinar |
| 01 solution-type | outcomes | uname -s no enforced | **CRIT — enforce** |
| 02 design | mixto | E2E ausente, mockups bastan | refinar (S10) |
| 03 spec | outcomes | checkpoints sin "deployable" | refinar |
| 04 edge-cases | outcomes | "30+" arbitrario | low |
| 05 scaffold | outcomes | **sin git init obligatorio** | **CRIT — enforce** |
| 06 core | outcomes | **sin tests unit obligatorios** | **CRIT — enforce** |
| 07 infra | outcomes | sin schema contracts | enforce Pydantic |
| 08 integration | mixto | **Streamlit acepta UI web** | **CRIT — enforce Playwright** |
| 09 testing | outcomes | coverage no diferenciado | low |
| 10 security | outcomes | OWASP sólo top 4 | refinar |
| 10.5 gate | outcomes | **subjetivo, no bloquea fase 11** | **CRIT — enforce** |
| 11 deploy | outcomes | go-live sin smoke E2E | enforce smoke |
| 12 iteration | viva | sin auditoría continua | S13 (apex-doctor) |
| 13 scaling | outcomes | "3 cuellos" sin "resueltos" | refinar |
| 14 maintenance | outcomes | docs sin actualización auto | refinar |

---

## 8. Hallazgos del ecosistema (cross-repo)

- **APEX↔Hub roto**: el bus de eventos está descableado. Ver `apex-hub-audit.md` apartado 7.
- **CLAUDE.md desactualizado**: dice 12 skills (son 19), dice frontend Next.js (no se usa).
- **Frontend Next.js huérfano**: arquitectura legacy en rama `archive/legacy-web` según CLAUDE.md, pero todavía hay `frontend/` en raíz. Confirmar y limpiar.

---

## 9. Plan Sprint 8 detallado

### S8.1 — Grader outcome-based (3-4 días)

1. **Crear `lib/grader.py`** (~250L estimadas)
   - Función `evaluate_phase(phase, evidence) -> Verdict`
   - `Verdict = {quality: 1-4, category, issues[], should_block, reasoning}`
   - Modelo: Sonnet 4.6 vía Anthropic SDK con prompt caching.
   - Inputs: `apex_get_context(level=full)`, `git diff`, últimas 50 líneas de `session_logs`, regla aplicable de `absolute-rules.md`.
   - 9-item taxonomía de issues (incomplete, hallucination, mock_data, missing_test, no_git_init, no_e2e, no_schema_contract, no_cross_project_search, no_so_check).

2. **Reciclar `skills/implement/` → `skills/grader/`**
   - `SKILL.md` con criterios de invocación (cada `apex_set_phase`).

3. **Nueva tool MCP `apex_grader_evaluate`** (~80L en `apex_server.py`)

4. **Bloqueo en `apex_set_phase`**
   - Antes de cambiar fase, llama al grader con evidence de la fase a cerrar.
   - Si `should_block=True`, devuelve diagnóstico en lugar de avanzar.
   - Override manual con flag `force=True` (registra `apex_add_error`).

5. **Reescribir `skills/flow-guardian/SKILL.md`**
   - Pasa de checklist a delegación al Grader.
   - Mantiene la regla cross-project obligatoria.

6. **Hook `phase-gate.py`** (PreToolUse para `apex_set_phase`)

### S8.2 — /goal turn-budget loop (1-2 días)

1. **Crear `lib/goal_loop.py`** (~150L)
   - `run_goal(goal, turn_budget=20) -> GoalResult`
   - Tras cada turno, juez (Sonnet 4.6) decide `done | continue` con razón.
   - Si `continue`, re-emite prompt al modelo principal.
   - Termina por: `done`, budget agotado, o pause manual.

2. **`commands/apex-goal.md`** (~60L) — comando user-facing.

3. **Reciclar `skills/verify/` → `skills/apex-goal/`** O poblar `verify/` con su SKILL real (decidir).

4. **Tool MCP `apex_goal_loop`** opcional (puede ser solo comando).

### S8.3 — Bridge APEX↔Hub (1 día)

1. **`_debug_log()` POSTea al endpoint del Hub**
   - Detecta puerto desde `~/.apex/hub-v2-port`.
   - Endpoint: `POST /api/live/event` (ya existe).
   - Retry exponencial, timeout 2s, no falla la sesión.

2. **Endpoint `GET /api/hub/search-cross-project?q=X`** (en apex-hub)
   - Wrapper sobre `hub_search` FTS5 con filtros `source_type IN (decision, error)`.

3. **Implementar `apex_search_cross_project`** (que hoy devuelve offline)
   - HTTP GET al endpoint del Hub.
   - Cache local en `.apex/cross-project-cache.db` con TTL 1h.

### S8.4 — Tests + sincronización docs (1 día)

1. **`tests/test_grader.py`** — 3 rutas: pass, block, edge case.
2. **`tests/test_goal_loop.py`** — turn-budget agotamiento, done detection.
3. **Actualizar `commands/apex.md`** tabla con todas las 24+3 tools nuevas.
4. **Actualizar `CLAUDE.md`** — 19 skills, sin frontend Next.js, estado real.
5. **Conventional commits** por sub-paso (S8.1.1, S8.1.2, etc.).

**Definition of Done Sprint 8:**
- [ ] Grader bloquea una fase con mock data en proyecto piloto.
- [ ] /goal completa una tarea trivial en ≤5 turnos.
- [ ] Hub recibe ≥1 evento real desde APEX (verificable en `/live`).
- [ ] `apex_search_cross_project("emojis")` devuelve la lección de focusnow#2.
- [ ] Tests verde (`pytest tests/`).

---

## 10. Decisiones arquitectónicas registradas

- **Modelo del Grader:** Sonnet 4.6 único. Razón: N estadístico es 1 usuario × 10 sesiones/semana, panel tri-judge CREAO es overkill (memoria S5102). Si el sesgo de juez se vuelve problema, se añade un segundo modelo con quorum 1-de-2.
- **Browser-trace (Sprint 11):** acceso al perfil real de Chrome del sistema, no sandbox. Razón: Vicente quiere observabilidad sobre sesiones reales (cookies, login). Mitigación: opt-out por dominio (lista negra editable en `.apex/browser-trace-blocklist.txt`), nunca capturar campos `<input type=password>`, encriptar artefactos at-rest.
- **Roadmap aprobado:** Sprint 8 (Grader+/goal+Bridge) → 9 (Context hygiene) → 10 (DESIGN.md+Scrapling) → 11 (browser-trace+meta-forge+library-skills) → 12 (Virtual office) → 13 (apex-doctor).

---

## 11. Anexo: lecciones cross-project que YA están enforced

| Lección | Estado | Fase aplicable |
|---|---|---|
| focusnow#1 (uname -s antes de stack) | escrito en regla #10, no enforced | 1 |
| focusnow#2 (no emojis) | enforced parcial via `ux-verification.md` | 2, 8, 11 |
| focusnow#3 (no fase con mock) | NO enforced | 6, 8, 11 |
| focusnow#4 (git init en fase 5) | escrito en flow-guardian checklist, no técnico | 5 |
| tfg-tutor#5 (datos entre agentes) | NO mencionado | 6, 7, 8 |

**Sprint 8 cierra los 5 con enforcement técnico.**
