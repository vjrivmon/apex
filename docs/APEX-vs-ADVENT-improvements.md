# APEX vs Advent of Claude 2025 — Análisis y mejoras propuestas

> Comparativa entre [`docs/ADVENT-OF-CLAUDE.md`](./ADVENT-OF-CLAUDE.md) (recopilatorio de los 24 días del Advent of Claude 2025 + 42 tips de comunidad + best practices Anthropic) y el sistema [`/apex`](file:///home/vicente/RoadToDevOps/apex/) en su estado actual (post Sprint 15, 49 tools MCP, 23 skills, 466+ tests).
>
> **Objetivo**: identificar qué valor del Advent NO está cubierto por APEX y proponer las integraciones de mayor ROI.

---

## TL;DR

| Bloque | Cobertura APEX | Conclusión |
|---|---|---|
| Workflow guiado (planificar → codificar → testear → deploy) | ✅ Supera | APEX 14 fases > Advent 4 pasos |
| Memoria persistente | ✅ Supera | `context.db` SQLite + FTS5 + temporal facts > `#` prefix de Claude Code |
| Skills, subagentes, hooks | ✅ Cubre | 23 skills + 3 hooks + advisor subagent |
| Seguridad estructural | ✅ Supera | Gate 10.5 AgentArmor 8 capas > permissions deny |
| **Atajos CLI / UX de prompt** | ✗ No aplica | Es responsabilidad de Claude Code, no de APEX |
| **Pre-commit hooks de seguridad** (gitleaks/secrets) | ⚠️ Parcial | APEX tiene templates DevOps pero NO `gitleaks` automático |
| **`/init` que genere CLAUDE.md proyecto-específico** | ⚠️ Parcial | `apex_init_project` crea `.apex/` pero NO `CLAUDE.md` |
| **Slash commands cortos con `$ARGUMENTS` / `!bash` / `@file`** | ✗ No documentado | Patrón potente sin guidance APEX |
| **Project rules condicionales por path** | ✗ No | Día 10 muestra `paths: src/api/**` con reglas YAML |
| **GitHub Action APEX-aware (validar decisiones en PR)** | ⚠️ Parcial | Templates CI/CD existen pero no validan decisiones vigentes |
| **`apex_export_session` para handoffs entre humanos** | ✗ No | `apex_log_session` registra resumen pero no exporta archivo |
| **Guidance worktree vs subagent** | ⚠️ Parcial | Skill `parallel-coordinator` existe sin docs de decisión |
| **Hook context-monitor (auto-log al 80%)** | ✗ No | Día 20 advierte de buffer 32k; APEX no monitoriza |
| **`/chrome` integration en Fase 9** | ✗ No | Playwright sí, Chrome interactivo no |

→ **10 mejoras propuestas, priorizadas por ROI** en §4.

---

## 1. Lo que APEX YA cubre o supera

### 1.1 Workflow estructurado
| Advent (Día 17, "Explorar → Planificar → Codificar → Commit") | APEX |
|---|---|
| 4 pasos genéricos | **14 fases (0-14)** con sub-pasos secuenciales obligatorios, gate 10.5 de seguridad, edge cases pre-código, mini-socrático para iteraciones (fase 12) |

### 1.2 Memoria persistente
| Advent (Día 5, `#` prefix; Día 12 handoff.md) | APEX |
|---|---|
| `#` guarda en memoria de sesión / handoff manual | `context.db` SQLite por proyecto con **temporal facts** (Graphiti pattern), FTS5 wiki, `apex_get_context(level=compact/timeline/full)`, error memory bidireccional con `recurrence_count`, **cross-project hub** (`apex-hub`) |

### 1.3 Skills + Subagentes
| Advent (Día 20 SKILL.md, Día 9 skills+subagents, Día 21 async) | APEX |
|---|---|
| Estructura `SKILL.md` + frontmatter, subagentes asíncronos | **23 skills** (apex, socratic, architect, flow-guardian, iterate, design-system, security-audit, grader, apex-goal, prototype, grill-with-docs, tdd, diagnose, improve-architecture, etc.) + subagent Opus `apex-advisor` con whitelist restringida |

### 1.4 Hooks
| Advent (Día 14-15 SessionStart/UserPromptSubmit/Pre/PostToolUse) | APEX |
|---|---|
| Configuración base de hooks | 3 hooks Sprint 15: `advisor-trigger`, `advice-injector`, `trace-prompt` + `phase-gate.py` (PreToolUse) que bloquea `apex_set_phase` si verdict del grader marca `should_block` |

### 1.5 Seguridad estructural
| Advent (Día 12-13 permissions/deny + sandbox) | APEX |
|---|---|
| Lista deny y `/sandbox` | **Gate 10.5 AgentArmor 8 capas** (L1-L8 con templates) que bloquea fase 11 si alguna capa != passed |

### 1.6 Plan mode / pensamiento profundo
| Advent (Día 17 Plan Mode + Shift+Tab + ultrathink) | APEX |
|---|---|
| Pensamiento extendido manual | `apex_goal_loop` (turn-budget loop con detección de degeneración estilo Hermes /goal) + `reasoning_traces` (4 categorías subset Hermes 3) |

### 1.7 CI/CD y deploy
| Advent (Día 7 headless `claude -p`, Día 22 GH Actions) | APEX |
|---|---|
| `claude -p`, claude-code-action genérico | `lib/scaffold_devops.py` + `templates/`: GH Actions (ci, deploy-staging, deploy-prod, release-please), Dockerfile multi-stage, docker-compose.prod.yml, Prometheus + Grafana + Loki + alerts |

### 1.8 Cross-project (no existe en Advent)
APEX exclusivo: `apex-hub` agrega errores/decisiones/componentes de múltiples proyectos en `hub.db`, expone endpoint `/api/hub/search-cross-project`, y `apex_search_cross_project()` devuelve lecciones de OTROS proyectos antes de tomar decisiones de stack/diseño/arquitectura. Esta sesión misma usa esa memoria cross-project (5 lecciones inyectadas en `SessionStart`).

---

## 2. Lo que ADVENT cubre y APEX NO

### Gap A — Atajos teclado / UX de prompt (Día 1, 2, 6, 22)
**ADVENT**: `!bash`, `Esc Esc` retroceder, `Ctrl+R` búsqueda inversa, `Ctrl+S` stash de prompt, `Ctrl+G` editor externo (`VISUAL=vim/code/cursor`), `Ctrl+B` background, navegación `Ctrl+A/E/W/U`, `vim_mode` en settings.

**Status APEX**: No aplica. Estos atajos son del CLI de Claude Code, no son responsabilidad de APEX.

**Acción recomendada**: Documentar en el README de APEX una sección "Atajos recomendados durante una sesión APEX" para que usuarios nuevos los aprovechen sin tener que descubrirlos.

---

### Gap B — Slash commands con `$ARGUMENTS` + `!bash` previo + `@file` references (Día 26)
**ADVENT** (líneas 222-280): patrón `.claude/commands/<nombre>.md` con frontmatter `description` + `allowed-tools` + cuerpo que admite:
- `$ARGUMENTS` substitución del input del usuario
- `!comando` ejecuta bash y inyecta output
- `@src/file.ts` añade archivo al contexto

Ejemplos: `/review src/api/auth.ts`, `/test-file foo.spec.ts`, `/smart-commit`, `/security`.

**Status APEX**: Tiene `commands/apex.md` (la skill maestra) pero NO documenta el patrón corto. Los usuarios deben escribir prompts completos para invocar `apex_add_decision`, `apex_add_error`, etc.

**Acción recomendada**: añadir en `apex/templates/commands/` shortcuts:
- `apex-decision.md` → `apex_add_decision(category=$1, decision=$2, reasoning=$3)`
- `apex-error.md` → `apex_add_error(...)` con `!git diff` previo para contexto
- `apex-component.md` con `@src/$1` para añadir archivo al contexto antes de registrar
- `apex-search.md` → `apex_search($ARGUMENTS)` formateado

ROI: alto. Reduce fricción de uso diario sin añadir complejidad al core.

---

### Gap C — Sesiones nombradas y `apex_resume_session` smart (Día 11, 4)
**ADVENT**: `/rename api-migration`, `/resume api-migration`, `claude --resume <id>`. "Tus branches tienen nombres. Tus sesiones también deberían."

**Status APEX**: Tiene `apex_resume_session` pero no se integra con el `session-id` del propio Claude Code. Vicente probablemente acaba con varias sesiones APEX huérfanas sin nombre.

**Acción recomendada**: en `apex_log_session`, capturar también el `session_id` (variable env `CLAUDE_SESSION_ID` si existe) y permitir `apex_resume_session(name=...)` que devuelva el comando `claude --resume <id>` exacto a ejecutar.

---

### Gap D — `/init` automático que genere CLAUDE.md APEX-aware (Día 23)
**ADVENT** (líneas 175-220): `/init` lee codebase y genera `CLAUDE.md` con build commands, test instructions, directorios clave, convenciones.

**Status APEX**: `apex_init_project` crea `.apex/context.db` y wiki scaffold pero NO genera `CLAUDE.md` en el root del proyecto.

**Acción recomendada**: `apex_init_project` debería ofrecer (o generar por defecto) un `CLAUDE.md` que:
1. Documente el flow APEX activo en este proyecto (qué fase, qué decisiones vigentes)
2. Incluya un bloque "Para Claude Code: usa `apex_get_context(level=timeline)` antes de empezar"
3. Liste las skills APEX recomendadas para este dominio

ROI: alto. La fricción más grande de APEX hoy es que sesiones nuevas no saben que está APEX activo hasta que se ejecuta `mcp__apex__apex_get_context` manualmente.

---

### Gap E — Project rules condicionales por path (Día 10)
**ADVENT** (líneas 195-210):
```yaml
# .claude/rules/api.md
---
paths: src/api/**/*.ts
---
- Usar Zod para validación
- Rate limiting obligatorio
```

**Status APEX**: APEX registra componentes con `apex_add_component(files=[...])` pero NO genera reglas condicionales por path.

**Acción recomendada**: cuando un componente APEX se marca como `verified`, opción de auto-generar `.claude/rules/<component-id>.md` con frontmatter `paths:` y un bullet por cada decisión vigente que aplique a ese componente. Mantiene el contexto disponible solo cuando se editan archivos relevantes (ahorra tokens).

---

### Gap F — Pre-commit hook con gitleaks como template DevOps (relacionado Día 14-15)
**ADVENT**: muestra `validate-prompt.sh` que detecta `(API_KEY|SECRET|PASSWORD)` en el prompt antes de enviarlo.

**Status APEX**: `lib/scaffold_devops.py` genera `.github/workflows/ci.yml` pero NO instala `gitleaks` como pre-commit hook ni como step de CI por defecto. La fase 10 (seguridad) menciona `audit: revisar que no hay secretos en el codigo` pero no automatiza la detección.

**Status este proyecto** (vicente-portfolio-profesional): la negligencia detectada el 2026-05-08 (`incidents/2026-05-08-secrets-leak-prepublic`) confirma el ROI altísimo de este gap. 4 secrets en el historial 4 meses por falta de `gitleaks protect --staged`.

**Acción recomendada CRÍTICA**:
1. Añadir a `apex/templates/devops/` un `.husky/pre-commit` con `gitleaks protect --staged --redact`
2. Añadir a `templates/github-actions/` un step `gitleaks-action` que falle el CI si encuentra secrets en el diff de un PR
3. Hacer que `apex_set_phase(phase=10)` falle si no detecta `gitleaks` configurado en el repo
4. Documentar en lección cross-project (ya hecho en `apex_add_error` de esta sesión)

ROI: máximo. Previene la categoría de error que motivó esta sesión.

---

### Gap G — Sandbox mode en fases 0-4 (Día 13)
**ADVENT**: `/sandbox` restringe Edit/Read/Bash al directorio de trabajo.

**Status APEX**: no integra `/sandbox`. Las fases 0-4 son de análisis y diseño puro pero APEX permite escritura.

**Acción recomendada**: la skill `socratic` (fase 0) podría sugerir entrar a `/sandbox` para impedir cualquier escritura accidental durante la fase de cuestionamiento. Bajo coste, alto valor anti-pulsión-de-codear.

---

### Gap H — `/chrome` integration en Fase 9 (Día 18-19)
**ADVENT**: `/chrome` integra con Chrome para navegar, click, leer console, grabar GIFs. "Fix el bug y verifica que funciona" en un solo prompt.

**Status APEX**: la fase 9 (testing) usa Playwright para E2E pero NO integra `/chrome` para verificación interactiva durante desarrollo.

**Acción recomendada**: la skill `flow-guardian` (en su sub-paso `[8c]` "conectar frontend al backend") podría usar `/chrome` además de Playwright. Especialmente útil cuando el bug es visual y requiere ojo humano + Claude colaborando.

---

### Gap I — Worktree vs subagent guidance (Día 23)
**ADVENT**: tres patrones de paralelización:
1. Subagentes (mismo branch, contexto aislado)
2. `git worktree add` (branches paralelos, dirs paralelos)
3. Multi-Claude tmux (varias terminales)

**Status APEX**: tiene skill `parallel-coordinator` pero no documenta cuándo elegir cada patrón. El error #4 cross-project (focusnow no inicializó git) sugiere que los usuarios no piensan en branching.

**Acción recomendada**: añadir en `skills/parallel-coordinator/PATTERNS.md` una matriz:

| Caso | Patrón |
|---|---|
| Tareas read-only paralelas (research, search) | Subagentes (Task tool) |
| Features independientes en branches paralelos | `git worktree` |
| Writer + Reviewer simultáneos | Multi-Claude tmux con handoff vía `apex_handoff_skill` |
| Mismo proyecto, fase 12 con bug crítico + feature | Subagent para feature, ventana principal para bug |

---

### Gap J — Headless `claude -p` invocando APEX (Día 7)
**ADVENT**: `claude -p "tu prompt aquí" --output-format stream-json` para automatización.

**Status APEX**: las tools MCP funcionan en sesiones interactivas. NO hay un wrapper headless documentado tipo `apex doctor` que ejecute `claude -p "..."` y devuelva JSON estructurado.

**Acción recomendada**: documentar en `apex/docs/HEADLESS.md` cómo invocar tools APEX desde scripts (ej: cron job que llame `apex_doctor_run` y publique en Slack si encuentra problemas).

---

### Gap K — GitHub Action APEX-aware que valide decisiones en PR (Día 22)
**ADVENT**: `claude-code-action` genérico para review de PRs.

**Status APEX**: tiene `apex_invalidate_decision` pero ninguna automatización detecta cuándo una PR rompe una decisión vigente. Por ejemplo, si una decisión dice "stack: Next.js App Router" y la PR introduce Pages Router, debería disparar warning.

**Acción recomendada**: template `.github/workflows/apex-validate.yml` que:
1. Carga `apex_get_context(level=full)` para extraer decisiones vigentes
2. Lee diff del PR
3. Pregunta a Claude (vía `claude -p`) si el diff contradice alguna decisión
4. Comenta en el PR con findings (no bloqueante por defecto, configurable)

ROI: medio-alto en proyectos con varios contribuidores; bajo en solo-Vicente.

---

### Gap L — `apex_export_session` para handoffs humanos (Día 24 `/export`, Día 12 handoff.md)
**ADVENT**: `/export` exporta conversación a documento; handoff.md como patrón manual.

**Status APEX**: `apex_log_session` registra resumen en context.db; `apex_handoff_skill` cambia de modo intra-sesión. NO hay export a archivo plano para entregarle a otra persona o a otra sesión.

**Acción recomendada**: nueva tool `apex_export_session(format="md|json", since="<phase|date>")` que genere un archivo con:
- Decisiones vigentes en formato compacto
- Errores con lecciones
- Componentes registrados
- Próximos pasos pendientes
- Estado de fase actual

Útil para abrir Issues, PRs descriptivos, o pasarle el contexto a un compañero.

---

### Gap M — Hook context-monitor (Día 20)
**ADVENT** (líneas 715-740): "Default 32k tokens (22.5%) buffer. Con max output 64k, ~40%". Recomienda iniciar nueva sesión cuando contexto crece.

**Status APEX**: no monitoriza el uso de contexto. Si Claude llega al auto-compact sin que APEX haya registrado el estado, se pierde información.

**Acción recomendada**: hook `PreCompact` que dispare `apex_log_session` automáticamente con resumen breve antes de que el compact arrastre detalles. Backup automático del estado de la sesión.

---

### Gap N — Auditoría de overhead MCP (Día 7, "8-30% del contexto")
**ADVENT**: `/context` muestra overhead de MCP tools. APEX tiene 49 tools registradas, lo cual es overhead alto.

**Status APEX**: no documenta el coste en tokens de tener APEX MCP activo.

**Acción recomendada**: medir y documentar en README cuánto contexto consume APEX al inicio de una sesión (ToolSearch dinámico ayuda — APEX podría no exponer las 49 tools por defecto, sino solo las 5-7 más frecuentes y dejar las demás detrás de `ToolSearch`).

---

### Gap O — `/init` plugin de migración (Día 1)
**ADVENT**: `anthropics/claude-code/tree/main/plugins/claude-opus-4-5-migration` migra código entre versiones de Opus.

**Status APEX**: no aplica directamente, pero APEX podría tener un mini-plugin de migración entre versiones de APEX (ej: cuando un proyecto tiene `.apex/` de Sprint 8 y necesita migrarse a esquema Sprint 15 con `state_machines` y `reasoning_traces`).

---

## 3. Decisiones explícitas de NO integrar

Hay tips del Advent que APEX **deliberadamente** no debería adoptar:

| Tip Advent | Razón para no integrar |
|---|---|
| `--dangerously-skip-permissions` (Día 15, YOLO mode) | Contradice gate 10.5 AgentArmor. APEX prioriza determinismo seguro. |
| `#` prefix para memoria persistente (Día 5) | APEX tiene `context.db` propio. Mezclar capas confunde fuente de verdad. |
| Atajos CLI (`Ctrl+R/S/G/B`, vim_mode) | Son del runtime de Claude Code, no responsabilidad de APEX. Mencionar en README, no implementar. |
| Multi-Claude con tmux para "rotar permisos" | APEX prefiere skill handoffs explícitos vía `apex_handoff_skill`. |

---

## 4. Mejoras propuestas — priorizadas

### Tier 1 (alto ROI, esfuerzo bajo)

1. **Gap F — Pre-commit gitleaks como template DevOps** ⚠️ CRÍTICO
   - Justifica retroactivamente el incidente `2026-05-08`.
   - Esfuerzo: ~30 min (template `.husky/pre-commit` + step en `ci.yml`).
   - Impacto: previene categoría completa de errores cross-project.

2. **Gap D — `apex_init_project` genera `CLAUDE.md` APEX-aware**
   - Cierra el bucle "sesiones nuevas no saben que APEX está activo".
   - Esfuerzo: ~1 h (template + lógica de detección de stack).
   - Impacto: reduce fricción inicial drásticamente.

3. **Gap B — Slash commands cortos con `$ARGUMENTS`**
   - 4 comandos: `apex-decision`, `apex-error`, `apex-component`, `apex-search`.
   - Esfuerzo: ~45 min (4 archivos `.md`).
   - Impacto: acelera registro diario de signals.

### Tier 2 (ROI medio, esfuerzo medio)

4. **Gap M — Hook PreCompact que dispare `apex_log_session`**
   - Esfuerzo: ~1.5 h (hook script + integración).
   - Impacto: cero pérdida de contexto en sesiones largas.

5. **Gap L — `apex_export_session(format=md|json)`**
   - Esfuerzo: ~2 h (tool + template + tests).
   - Impacto: handoffs humanos triviales.

6. **Gap E — Project rules condicionales auto-generadas desde componentes**
   - Esfuerzo: ~3 h (lógica de generación + test E2E).
   - Impacto: reduce overhead de contexto + reglas relevantes solo donde aplican.

### Tier 3 (ROI alto pero esfuerzo grande)

7. **Gap K — GitHub Action APEX-aware que valida decisiones en PRs**
   - Esfuerzo: ~6-8 h (workflow YAML + script Python + test E2E con repo dummy).
   - Impacto: alto en equipos, bajo en solo-Vicente. Postergar hasta tener colaboradores.

### Tier 4 (mejoras documentales, esfuerzo bajo, ROI continuo)

8. **Gap A — README "Atajos recomendados durante sesión APEX"** (~15 min)
9. **Gap I — Matriz worktree/subagent/multi-claude en `parallel-coordinator/PATTERNS.md`** (~30 min)
10. **Gap N — Auditoría y documentación del overhead MCP de APEX** (~1 h, requiere `/context` real)

---

## 5. Cómo aplicar las mejoras

Si aceptas las propuestas, el orden sugerido es:

1. **Esta sesión (urgente)**: Gap F (pre-commit gitleaks) — directamente útil para cerrar la fase 2 del trabajo de limpieza de este repo. Aplicar primero a `vicente-portfolio-profesional` como caso de prueba.

2. **Próxima sesión APEX-meta**: Tier 1 completo en `~/RoadToDevOps/apex/` con un sprint dedicado (~3 h).

3. **Sprint 16 de APEX** (si planeas seguir iterando): Tier 2 + Tier 4.

4. **Diferido**: Tier 3 hasta tener proyecto multi-contribuidor.

---

## Referencias

- [`docs/ADVENT-OF-CLAUDE.md`](./ADVENT-OF-CLAUDE.md) — fuente original (850 líneas).
- [`/home/vicente/RoadToDevOps/apex/CLAUDE.md`](file:///home/vicente/RoadToDevOps/apex/CLAUDE.md) — estado actual de APEX (post Sprint 15).
- [`.apex/wiki/incidents/2026-05-08-secrets-leak-prepublic.md`](file:///home/vicente/RoadToDevOps/vicente-portfolio-system/.apex/wiki/incidents/2026-05-08-secrets-leak-prepublic.md) — caso que motiva la prioridad de Gap F.
- Decision #9 y #10 en context.db de este proyecto — estrategia de limpieza.

---

*Documento generado: 2026-05-08 — sesión de limpieza pre-publicación del portfolio.*
