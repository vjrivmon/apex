# Sprint 19 — Advent Integration (mejoras Advent of Claude 2025)

> Origen: `docs/APEX-vs-ADVENT-improvements.md` (análisis comparativo
> APEX vs Advent of Claude 2025, 348 líneas, generado 2026-05-08).
>
> Objetivo: integrar las 10 mejoras priorizadas (Tier 1-4) que cierran
> los gaps A-O detectados respecto al estado de APEX post-Sprint 15.
>
> **Pre-requisito:** Sprint 16 cerrado (S16.1 ✓, S16.5 ✓, S16.2 ✓,
> S16.6 → S16.3 → S16.4 → S16.7 → S16.8 pendientes). S17 (VirtualFS)
> y S18 (Granite Curator) siguen detrás.

---

## Por qué este sprint

El doc fuente identifica que APEX **supera** a Advent en workflow,
memoria, skills, seguridad estructural y cross-project, pero deja
agujeros en:

- Atajos UX y slash-commands cortos (Gap A, B).
- `CLAUDE.md` APEX-aware automático (Gap D).
- Pre-commit gitleaks como template DevOps (Gap F) — **crítico**, ya
  motivó incidente real en `vicente-portfolio-system` el 2026-05-08.
- Hooks `PreCompact` + `apex_export_session` para handoffs humanos
  (Gap M, L).
- Reglas condicionales por path (Gap E).
- GitHub Action APEX-aware (Gap K).

S19 cierra Tier 1 + Tier 2 + Tier 4 en un solo sprint. Tier 3 (Gap K)
queda diferido a S20+ por esfuerzo y por tener bajo ROI en solo-Vicente.

---

## Decisiones (entrada al sprint)

| Decisión | Razón |
|----------|-------|
| Crear sprint nuevo (S19) en lugar de meterlo en S16 | S16 vigente es feedback loop del advisor; mezclar contextos rompe traza del blueprint commiteado. |
| Doc fuente vive en `apex/docs/` (copiado) | El portfolio-system seguirá iterando; APEX necesita su propia copia versionada. |
| Tier 1 antes que Tier 2; ambos antes que Tier 4 | Gap F crítico; D + B son enablers de fricción diaria; documentación al final. |
| Tier 3 (Gap K) diferido a S20 | Esfuerzo 6-8h, ROI bajo en solo-Vicente. Reabrir cuando haya colaboradores. |
| Decisiones explícitas de NO integrar (§3 del doc) | YOLO mode (`--dangerously-skip-permissions`), `#` prefix de Claude Code, vim_mode, multi-claude tmux para rotar permisos. Documentar en README, no implementar. |

---

## Subtareas

### Tier 1 — alto ROI, esfuerzo bajo (~2.5h)

| ID    | Subtarea                                                       | Esfuerzo | Tests |
|-------|----------------------------------------------------------------|----------|-------|
| S19.1 | Gap F — `templates/devops/.husky/pre-commit` con gitleaks      | 30 min   | (3)   |
| S19.1b | Gap F — step `gitleaks-action` en `templates/github-actions/ci.yml` | 15 min | (1) |
| S19.1c | Gap F — `apex_set_phase(phase=10)` falla si no detecta gitleaks | 30 min  | (4)  |
| S19.2 | Gap D — `apex_init_project` genera `CLAUDE.md` APEX-aware       | 1 h      | (5)   |
| S19.3 | Gap B — slash commands cortos en `templates/commands/`          | 45 min   | (4)   |

**Detalle S19.1 (gitleaks como template):**

- `templates/devops/husky-pre-commit.sh` con shebang + `gitleaks protect
  --staged --redact`.
- `lib/scaffold_devops.py` instala el hook al ejecutar
  `apex_scaffold_devops` (idempotente).
- En `lib/security_gate.py`, función nueva
  `_check_gitleaks_configured(project_root)` que devuelve `True` si
  `.husky/pre-commit` o `.gitleaks.toml` existen, `False` si no.
- Fase 10.5 falla con mensaje claro si gitleaks no está configurado;
  mensaje sugiere correr `apex_scaffold_devops`.

**Detalle S19.2 (`CLAUDE.md` APEX-aware):**

- `lib/init_claude_md.py` (~120 LoC): genera `CLAUDE.md` con secciones:
  1. "Para Claude Code: usa `mcp__apex__apex_get_context(level=timeline)`
     antes de empezar."
  2. "Fase actual del flujo APEX: [se rellena en cada `apex_set_phase`]"
  3. "Decisiones vigentes (top 5 más recientes)" — query a context.db.
  4. "Skills APEX recomendadas para este dominio."
- `apex_init_project` lo escribe **solo si no existe** ya un `CLAUDE.md`.
  Si existe, deja un bloque marcable `<!-- APEX-AWARE START -->` /
  `<!-- APEX-AWARE END -->` que se actualiza en cada
  `apex_set_phase`.

**Detalle S19.3 (slash commands cortos):**

- `templates/commands/apex-decision.md` con `$ARGUMENTS` parseado por
  `,` para `category,decision,reasoning`.
- `templates/commands/apex-error.md` con `!git diff --staged` previo
  para inyectar contexto.
- `templates/commands/apex-component.md` con `@<path>` para añadir el
  archivo al contexto antes de invocar `apex_add_component`.
- `templates/commands/apex-search.md` con `apex_search($ARGUMENTS)`.
- Se instalan en el proyecto al ejecutar `apex_init_project` o al
  llamar tool nueva `apex_install_commands(force=False)`.

### Tier 2 — ROI medio, esfuerzo medio (~6.5h)

| ID    | Subtarea                                                  | Esfuerzo | Tests |
|-------|-----------------------------------------------------------|----------|-------|
| S19.4 | Gap M — Hook `PreCompact` dispara `apex_log_session`       | 1.5 h    | (6)   |
| S19.5 | Gap L — `apex_export_session(format=md\|json, since=...)` | 2 h      | (8)   |
| S19.6 | Gap E — auto-generar `.claude/rules/<comp>.md` desde `apex_add_component(verified=True)` | 3 h | (7) |

**Detalle S19.4 (PreCompact hook):**

- Hook `.claude/hooks/pre-compact-log.py` que escucha `PreCompact` y
  llama `apex_log_session(summary=...)` con resumen breve.
- Idempotente con dedupe por `session_id`.

**Detalle S19.5 (`apex_export_session`):**

- Nueva tool MCP `apex_export_session(format='md|json',
  since='phase|date|all')`.
- Genera archivo en `.apex/exports/<session_id>-<timestamp>.<ext>` con
  decisiones vigentes, errores+lecciones, componentes registrados,
  next_steps pendientes, fase actual.
- Útil para abrir Issues, PRs, o pasar contexto a humano/sesión.

**Detalle S19.6 (project rules condicionales):**

- En `apex_add_component`, cuando se marca `status='verified'`, opción
  (`auto_generate_rules=True`) que crea `.claude/rules/<component-id>.md`
  con frontmatter `paths: [files...]` y un bullet por cada decisión
  vigente que aplique al componente.
- Mantenimiento: si una decisión se invalida con
  `apex_invalidate_decision`, regenera el archivo `.claude/rules/`
  correspondiente.

### Tier 4 — documentales, esfuerzo bajo, ROI continuo (~2h)

| ID    | Subtarea                                                       | Esfuerzo |
|-------|----------------------------------------------------------------|----------|
| S19.7 | Gap A — README "Atajos recomendados durante sesión APEX"        | 15 min   |
| S19.8 | Gap I — Matriz worktree/subagent en `skills/parallel-coordinator/PATTERNS.md` | 30 min |
| S19.9 | Gap N — Auditoría overhead MCP en README + recomendación ToolSearch dinámico | 1 h |

### Diferido a S20+

- Gap K — GH Action APEX-aware que valida decisiones vigentes en PRs
  (6-8h, esperar a colaboradores).
- Gap C — sesiones nombradas con captura de `CLAUDE_SESSION_ID`
  (depende de que Claude Code exponga la env var; revisar).
- Gap G — sandbox mode en fases 0-4 (depende de cómo evolucione `/sandbox`).
- Gap H — `/chrome` integration en fase 9 (esperar a estabilidad de `/chrome`).
- Gap J — wrapper headless `claude -p` (low priority).
- Gap O — mini-plugin de migración entre sprints de APEX (low priority).

---

## Suite objetivo

Tras Tier 1 + Tier 2 (S19.1-S19.6): **+38 tests** sobre 521 base
(post-S16) → ~559 verde.

Tier 4 no añade tests (documentación pura).

---

## Orden recomendado

S19.1 (gitleaks template + CI) → S19.1c (security_gate hook) → S19.2
(CLAUDE.md auto) → S19.3 (slash commands) → **commit Tier 1** → S19.4
(PreCompact) → S19.5 (export_session) → S19.6 (project rules) →
**commit Tier 2** → S19.7 + S19.8 + S19.9 → **commit Tier 4** → cerrar sprint.

---

## Riesgos y mitigación

| Riesgo | Mitigación |
|--------|------------|
| `gitleaks` no instalado en máquina del usuario | Template hook detecta `command -v gitleaks` y falla gracefully con instrucciones de instalación (`brew install gitleaks` / `apt`). |
| `CLAUDE.md` autogenerado pisa contenido manual | Bloque marcable `<!-- APEX-AWARE START/END -->`; nunca toca fuera del bloque. |
| Slash commands chocan con shortcuts del usuario | Namespace `apex-*` reduce colisiones. Si existe ya, el `apex_install_commands` salta con warning. |
| `PreCompact` hook se dispara antes de que `apex_log_session` complete | Timeout 3s + best-effort: si falla, log a stderr y continúa. |
| `auto_generate_rules` en `apex_add_component` introduce churn en `.claude/rules/` | Idempotente: regenera solo si decisiones cambian. Diff limpio. |

---

## Métricas de éxito

- 0 incidents de secretos commiteados en repos `~/RoadToDevOps/*` post-S19
  (medible vía `gitleaks detect` en cron).
- Sesiones nuevas en proyectos con APEX activo invocan
  `apex_get_context` en el primer turno (medible vía `tool_call_log`).
- ≥3 slash commands `apex-*` usados/semana en uso real.

---

## Referencias

- `docs/APEX-vs-ADVENT-improvements.md` — doc fuente con los 15 gaps.
- `BLUEPRINT.md` raíz — estado actual.
- `CLAUDE.md` raíz — roadmap actualizado con S19.
- `.apex/sprints/sprint-16-advisor-feedback-loop-blueprint.md` — sprint vigente.

---

*Sprint planificado: 2026-05-08. Pendiente de iniciar tras cierre de S16.*
