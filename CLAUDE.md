# CLAUDE.md — APEX

> Fuente de verdad del estado del proyecto. Última actualización: 2026-05-03 (post Sprint 13)

## Qué es APEX

Sistema de skills + MCP server para Claude Code que guía el ciclo completo
de desarrollo de software. Usa una BD SQLite contextual por proyecto
(`.apex/context.db`) + un segundo cerebro (ingest/lint/synthesis) + un
dashboard cross-project (`apex-hub`) para que Claude Code nunca pierda el
hilo — ni al inicio ni en las fases intermedias.

**Arquitectura: puro CLI + MCP + skills.** El frontend/backend web legacy
(commits previos a Sprint 7) vive en rama `archive/legacy-web` y NO se
carga en el flujo actual. El único frontend es `apex-hub` (repo aparte
en `~/RoadToDevOps/apex-hub/`).

---

## Estado Actual (post Sprint 7)

### Completado

- [x] **Context DB v2** (`lib/context_db.py`) con **hybrid retrieval** 70/30
  - Temporal facts (valid_from / invalid_from, patrón Graphiti)
  - Progressive disclosure (compact ~200tk / timeline ~800tk / full ~2000tk)
  - Error memory bidireccional con recurrence_count
  - Wiki pages en SQLite con FTS5
  - `search_hybrid()` combina BM25 + keyword overlap
  - 46 tests pasando

- [x] **Wiki Scaffold + segundo cerebro** (`lib/wiki_scaffold.py`)
  - Karpathy: `wiki/` con SCHEMA, index, log, entities/concepts/
    comparisons/queries/raw + **synthesis/** nuevo
  - Segundo cerebro: `.apex/brand/` (identity, design-system, strategy,
    performance), `.apex/raw/` (research, socratic, papers, decisions-log),
    `.apex/releases/` (drafts, staging, published)

- [x] **Ingest pipeline** (`lib/ingest.py`) — 8 pasos
  - Resuelve URLs con source_type, extrae signals, clasifica, genera
    páginas wiki con frontmatter + cross-links + bias flags

- [x] **Self-heal** (`lib/lint.py`) — 6 reglas
  - Contradicciones, errores sin decisión, huérfanos, wiki stale, sin
    wikilinks, next_steps mal bloqueados

- [x] **Synthesis** (`lib/synthesis.py`) — density-triggered dream_deep

- [x] **Portfolio bridge** (`lib/portfolio_publish.py` → vr-web/content/cases/)

- [x] **Scaffold DevOps** (`lib/scaffold_devops.py` + `templates/`)
  - GH Actions (ci, deploy-staging, deploy-prod, release-please)
  - Dockerfile multi-stage + docker-compose.prod.yml
  - Prometheus + Grafana + Loki + alerts

- [x] **Security Gate** (`lib/security_gate.py` + `templates/apex-security/`)
  - AgentArmor 8 capas mapeadas a fases
  - Fase 10.5 bloquea fase 11 si alguna capa != passed
  - Templates L1-L8 con checklist específico

- [x] **Comando /apex** (`commands/apex.md`)
  - 14 fases guiadas (0-socrático a 14-mantenimiento) + gate 10.5 AgentArmor
  - Detecta proyecto nuevo vs existente
  - 11 errores documentados a evitar

- [x] **19 Skills** (post Sprint 8)
  - Core flow: `socratic`, `architect`, `flow-guardian` (v2 outcome-based),
    `iterate`, `onboard-existing`, `reverse-engineer`, `tools-integration`
  - Diseño: `design-system`, `design-research`, `brand-identity`
  - Entrega: `portfolio-publisher`, `devops`, `monitor`
  - Segundo cerebro: `second-brain`, `brainstorming`
  - Seguridad: `security-audit` (AgentArmor)
  - Revisión: `code-review`
  - **Sprint 8 (nuevos)**: `grader` (outcome-based judge), `apex-goal`
    (turn-budget loop)
  - Eliminados (eran huérfanos vacíos): `implement`, `verify`

- [x] **Sprint 8 — Grader + /goal + Bridge Hub** (2026-05-03)
  - `lib/grader.py` (430L): checks deterministas (git, tests, OS, emojis,
    Pydantic, Playwright) + LLM judge prompt builder + Anthropic SDK
    wrapper opcional
  - `lib/goal_loop.py` (240L): turn-budget loop con detección de
    degeneración estilo Hermes /goal
  - Tabla `grader_verdicts` en context.db con CRUD
  - 2 tools MCP nuevas: `apex_grader_evaluate`, `apex_goal_loop`
  - Hook `phase-gate.py` (PreToolUse) bloquea apex_set_phase si verdict
    should_block
  - Bridge APEX↔Hub: detección hub-v2-port, endpoint
    `/api/hub/search-cross-project` en apex-hub
  - Tests: 25 grader + 18 goal_loop (98 totales, todos verde)

- [x] **MCP server** completo con 42 tools (Sprints 8-13 cierran esta deuda)

- [x] **Sprint 13.9 — usage_data_signals (cruce con `/insights`)** (2026-05-03)
  - `lib/usage_data_reader.py` (~165L): reader puro de
    `~/.claude/usage-data/{facets,session-meta}/`. Dataclasses `UsageMeta`
    (project_path, start_time, duration, tool_counts, tool_errors,
    tool_error_categories, lines_added/removed) y `UsageFacets` (outcome,
    claude_helpfulness, primary_success, friction_counts, friction_detail,
    user_satisfaction_counts, brief_summary). Iteradores `iter_meta` con
    filtro por `project_path`, `iter_facets` con filtro por `session_ids`.
    Helper `find_session_for_timestamp(ts, project_path, slack_minutes=5)`
    para asociar verdicts del grader con sesiones de Claude Code sin migrar
    schema (`UsageMeta.contains_timestamp` cruza ts contra
    `[start, start + duration + slack]`). Env `APEX_USAGE_DATA_ROOT` para
    tests. Best-effort: si el dir no existe, devuelve `[]`.
  - **A5 grader_false_positives** (`lib/apex_doctor.py`): cruza
    `grader_verdicts` locales con `should_block=0` contra facets del
    observer ajeno. Si el observer dice `outcome in {not_achieved,
    partially_achieved}` O `claude_helpfulness in {unhelpful,
    slightly_helpful}` O `user_satisfaction in {dissatisfied, frustrated}`,
    el grader pasó algo que no debería. Asociación verdict↔sesión vía
    heurística temporal (`created_at` del verdict vs `start_time + duration`
    de session-meta) — evita migración invasiva. >=2 falsos positivos en
    misma fase para emitir propuesta. Signature por fase
    (`grader_false_positive:phase=N`).
  - **A6 friction_recurrence** (`lib/apex_doctor.py`): agrega
    `friction_counts` del observer cross-sesión filtradas a `project_path`.
    Si una key (`buggy_code`, `wrong_approach`, `misunderstood_request`,
    `excessive_changes`, ...) aparece total >=3 veces en >=2 sesiones
    distintas del proyecto, propone afinarlo con
    `apex_skill_forge_scan(force=True)` o reforzar la fase relevante.
    Signature por friction key (`friction_recurrence:<key>`).
  - **Constantes nuevas**: `A5_MIN_FALSE_POSITIVES=2`,
    `A5_OUTCOMES_BAD={not_achieved, partially_achieved}`,
    `A5_HELP_BAD={unhelpful, slightly_helpful}`,
    `A5_SAT_BAD={dissatisfied, frustrated}`, `A5_LOOKBACK=200`,
    `A6_MIN_FRICTION_OCCURRENCES=3`, `A6_MIN_FRICTION_SESSIONS=2`.
  - **Idempotencia**: signatures canónicas, mismo `INSERT OR IGNORE` que
    A1-A4 vía `record_proposal`. Re-correr el doctor sobre los mismos
    datos no duplica propuestas.
  - **Sin tool MCP nueva**: `apex_doctor_run` ya invoca `run_doctor()`,
    que ahora incluye A5+A6 en el `all_props +=` chain. Total tools
    sigue en **42**.
  - **No migración de schema**: `grader_verdicts` no necesita columna
    `session_id` porque la heurística temporal cubre el cruce. Trade-off:
    si dos sesiones del usuario solapan en tiempo (raro, Claude Code
    serializa una activa), podría asociar mal — aceptable para detección
    de patrones agregados.
  - **No requiere `/insights`**: A5/A6 son best-effort sobre archivos que
    Claude Code ya escribe a `~/.claude/usage-data/` por su cuenta. Si
    el usuario nunca corre `/insights`, los archivos pueden estar pero
    no ser frescos — A5/A6 simplemente no fire.
  - 20 tests nuevos (`tests/test_apex_doctor_usage.py`): reader (8 tests
    cubriendo dir missing, project_path filter, JSON corrupto,
    session_ids filter, timestamp matching dentro/fuera de rango y
    cross-project), A5 (6 tests cubriendo BD limpia, threshold,
    signature por fase, outcome unclear no cuenta, blocked verdicts
    excluidos), A6 (4 tests: vacío, project_path filter, threshold,
    threshold de sesiones únicas), integración con `run_doctor` y render
    de markdown (2 tests). Total: **396 verde** en 6.2s.

- [x] **Sprint 13 — Apex-doctor (auto-mejora dirigida por intención)** (2026-05-03)
  - `lib/apex_doctor.py` (~530L): tres analizadores síncronos sobre
    `context.db` + `.apex/handoff/`. **A1 override_clusters** detecta
    errores con `recurrence_count>=3` o severidad `critical|high` (1
    propuesta por error, no agrupado, para que la signature sea estable).
    **A2 grader_block_patterns** agrupa issues bloqueantes que aparecen
    en >=2 fases distintas (umbral más bajo que el D1 del skill_forge:
    aquí la propuesta es afinar la regla del grader, no crear skill).
    **A3 stale_handoffs** marca handoffs en `.apex/handoff/` con mtime
    >7 días.
  - **Idempotencia**: cada `DoctorProposal` lleva una `signature` canónica;
    `doctor_proposals.signature UNIQUE` rechaza duplicados silenciosamente
    vía `INSERT OR IGNORE`. Re-ejecutar el doctor sobre la misma evidencia
    devuelve `proposals_count=0` sin tocar nada.
  - **Throttle**: `MIN_RUN_GAP_SECONDS=3600` (1h) entre runs;
    `is_throttled()` consulta `last_run_at()` y devuelve un `DoctorRun`
    con `status='throttled'` + `skipped_reason` cuando aplica. `force=True`
    lo salta.
  - **Trigger semántico (no cron)**: hook nuevo
    `.claude/hooks/end-of-day-doctor.py` (UserPromptSubmit). Dos
    disparadores: (a) frase de cierre detectada vía
    `lib/wrapup_phrases.py` (lista cerrada de 25 frases ES con normalización
    NFD para acentos y matching case-insensitive con límites de palabra),
    (b) edad de sesión >`APEX_DOCTOR_SESSION_AGE_HOURS` (default 3.5h)
    medida desde `session_starts.started_at`. Ambos triggers etiquetan el
    run en `doctor_runs.trigger`.
  - **Acción del hook**: corre `apex_doctor.run_doctor()` con timeout
    wall-clock 8s, escribe handoff via `lib/handoff.serialize_handoff()`,
    e inyecta a stdout (additionalContext) un bloque con resumen + ruta del
    MD + instrucción explícita de mencionar hallazgos al usuario. NO
    bloquea: si falla, sólo emite aviso y deja seguir.
  - **Schema nuevo**: tablas `doctor_runs(id, started_at, finished_at,
    proposals_count, trigger, status)`, `doctor_proposals(id, run_id,
    kind, signature UNIQUE, title, body, status, created_at)`,
    `session_starts(session_id PK, started_at)`. Auto-migración via el
    `_SCHEMA` constant + `_ensure_db_schema` ya existente.
  - **MD report**: `render_run_md` separa propuestas por kind; con 0
    hallazgos imprime "Sin hallazgos. APEX está limpio en estos
    analizadores." (decisión de diseño: silencio total no, mensaje
    explícito sí — petición Vicente).
  - 1 tool MCP nueva: `apex_doctor_run(force=False, trigger='manual')`.
    Total tools: **42**.
  - 72 tests nuevos (`tests/test_apex_doctor.py` 38 + `test_wrapup_phrases.py`
    34): schema migration, los 3 analizadores con datos sintéticos,
    idempotencia, throttle 1h, session_starts CRUD + age, render MD vacío
    vs con propuestas, lista cerrada normalizada, matching ES con
    acentos/mayúsculas. Total: **350 verde** en 5.6s.

- [x] **Sprint 12 — Virtual office (5 roles agentes)** (2026-05-03)
  - `lib/roles.py` (~430L): registry `ROLES` con 5 specs (`apex-architect`,
    `apex-implementer`, `apex-reviewer`, `apex-qa`, `apex-devops`). Cada
    spec lleva nombre, descripción con `<example>` (consumido por Claude
    Code para decidir cuándo invocar), whitelist de tools (incluye
    `mcp__apex__*`), modelo (`sonnet`), color y system prompt extenso con
    reglas absolutas alineadas a APEX (anti-emojis, español con tildes,
    `wiki/decisions/` antes de proponer stack, no datos mock, etc.).
  - **Mapping fase → rol**: 2-3 architect · 4 qa · 5-7 implementer · 8
    reviewer · 9 qa · 10 reviewer · 11 devops. Fases 0-1, 10.5, 12 sin
    rol (las maneja el orquestador main).
  - **Subagents nativos**: los archivos `.md` se instalan en
    `~/.claude/agents/apex-<role>.md` con frontmatter YAML (name, csv de
    tools, model, color, description-one-line). Claude Code los lee al
    arrancar y los expone vía `Task(subagent_type="apex-...")`. APEX no
    ejecuta el subagent — sólo prepara el prompt; quien dispara el `Task`
    es Claude Code main. Sin coste API: todo bajo suscripción MAX.
  - **Telemetría**: tabla nueva `role_invocations(id, session_id, role,
    phase, fired_at, context_summary, status)` con auto-migración via
    `_ensure_db_schema`. Helpers `record_invocation`,
    `update_invocation_status`, `get_invocations`.
  - 3 tools MCP nuevas (total: **41**):
    - `apex_install_roles(force, agents_root)` — escribe los 5 archivos.
      Idempotente.
    - `apex_recommend_role(phase)` — devuelve rol + razón + flag
      `installed`.
    - `apex_invoke_role(role, phase, context_summary,
      extra_instructions, session_id)` — construye `{subagent_type,
      description, prompt}` listos para `Task` y registra la invocación.
  - **Hook `phase-gate.py` extendido**: tras pasar el grader, si la
    transición es a `in_progress` y la fase tiene rol asociado, imprime
    a stderr (no bloqueante) la recomendación de invocar el rol. Tabla
    `_PHASE_ROLE_MAP` duplicada en el hook para evitar import circular.
  - 45 tests nuevos (`tests/test_roles.py`): registry, frontmatter YAML,
    install/idempotencia/force, mapping fase→rol, build_invocation con
    todos los placeholders, CRUD de telemetría, schema migration en BD
    limpia. Total: **278 verde** en 4.4s.

- [x] **Sprint 11.3 — Library Ingest (skills externas)** (2026-05-03)
  - `lib/library_ingest.py` (~700L): pipeline fetch → validate → propose para
    skills externas. Dos fuentes: (a) **GitHub Search API** (repos populares
    con `claude-skills` en nombre/topic + awesome-lists curadas, ordenados
    por estrellas; descarga `SKILL.md` vía `raw.githubusercontent.com`) y
    (b) **library-skills CLI** de tiangolo (`uvx library-skills --dry-run
    --claude`) cuando el proyecto tiene `pyproject.toml`/`package.json`.
  - **Validación determinista** que BLOQUEA antes de escribir ruido a disco:
    frontmatter YAML obligatorio (`name`, `description`), longitud (max name
    60 chars, max description 200, body 100B–50KB), y filtro de **secretos**
    (regex anti-keys: `sk-ant-…`, `ghp_…`, `AKIA…`, `AIza…`, BEGIN PRIVATE
    KEY, etc.). `validate_skill()` devuelve `(valid, issues)`; si invalid,
    se acumula en `IngestResult.invalid` y no se propone.
  - **Persistencia**: tabla `library_imports(slug, source, source_url, sha,
    imported_at, status)` en `context.db` (auto-migración) para no
    re-descargar el mismo SHA. Reusa `skill_forge_rejections` (Sprint 11.2)
    para que no se proponga lo ya rechazado. Reusa `apex_skill_forge_approve`
    /`apex_skill_forge_reject` (mismo dir `.apex/skill-proposals/`, mismo
    formato de propuesta con bloque ```` ```markdown ```` de 4 backticks
    para soportar SKILL.md con triple-backtick interno).
  - **Counter cross-project**: `session-start.py` cuenta proyectos visitados
    en `hub.db.global_meta.library_ingest_visit_set` (set JSON). Tras N=5
    proyectos sin ingerir, inyecta recordatorio sugiriendo
    `apex_ingest_library_skills(source="both")`. `reset_visit_counter` se
    llama tras un ingest exitoso.
  - **HTTP**: stdlib `urllib.request` (sin deps nuevas), timeout 10s wall-
    clock, max body 50KB. Token GitHub via `GITHUB_TOKEN`/`GH_TOKEN` env.
  - 1 tool MCP nueva: `apex_ingest_library_skills(source, query, min_stars,
    limit_repos, max_skills_per_repo)`. Total tools: **38**.
  - **Patch a skill_forge**: `_extract_skill_block` ahora soporta delimitador
    de 4 backticks (proposals nuevas) y cae a 3 (compat con Sprint 11.2).
  - 35 tests nuevos (frontmatter, validación, secretos, dedup, fixtures
    HTTP locales, fixture CLI dry-run). Total: **233 verde** en 5.3s.
  - **Fix de hook duplicado**: `apex/.claude/settings.json` registraba
    `session-start.py` que también está en `~/.claude/settings.json`
    (path absoluto). Quitado el duplicado del nivel proyecto: ahora la
    inyección de lecciones cross-project ocurre **una sola vez** por
    sesión (antes: doble bloque en `additionalContext`, ~2.5K tokens
    desperdiciados por sesión + counter avanzando dos veces).

- [x] **Sprint 11.2 — Skill Forge auto-detector** (2026-05-03)
  - `lib/skill_forge.py` (~440L): tres detectores `scan_grader_blocks` (D1
    >=3 fases con mismo issue bloqueante), `scan_tool_call_patterns` (D2
    secuencias de 3 tools repetidas >=5 veces) y `scan_cross_project_repeats`
    (D3 decisiones que aparecen en >=2 proyectos via `hub.db`).
  - Builders de propuesta deterministas (slug = sha1(signature)[:8]),
    output a `.apex/skill-proposals/<slug>.md`. Aprobación con
    `apex_skill_forge_approve(slug)` que mueve a `~/.claude/skills/<slug>/`;
    rechazo con `apex_skill_forge_reject(slug, reason)` que registra en
    `skill_forge_rejections` para no proponer lo mismo.
  - Schema: tablas `tool_call_log` (alimenta D2) y `skill_forge_rejections`
    (auto-migración via `_ensure_db_schema`).
  - Hook `.claude/hooks/skill-forge-watch.py` (PostToolUse): inserta una
    fila en `tool_call_log` por cada call no-skip y dispara `scan_and_write`
    cuando el tool es trigger (`apex_set_phase`/`apex_grader_evaluate`/
    `apex_add_decision`/`apex_complete_step`) o cuando han pasado >=25 calls
    desde el último scan (high-water mark en `project_meta.forge_last_scan_id`).
    Timeout wall-clock 2s, NO bloquea, sólo stderr `[skill-forge] N propuesta(s) nueva(s): ...`.
  - 3 tools MCP nuevas: `apex_skill_forge_scan`, `apex_skill_forge_approve`,
    `apex_skill_forge_reject`. Total tools: **37**.
  - 27 tests nuevos. Total: **198 verde** en 2.8s.

- [x] **Sprint 11.1 — Browser trace CDP nativo** (2026-05-03)
  - `lib/browser_trace.py` (~520L): launch_chrome con
    `--remote-debugging-port`, `_CDPSession` send/fire/drain sobre
    websockets nativo, captura de DOM final + network log + console +
    lifecycle. Patrón send+recv-loop sin reader-task (más robusto frente
    a quirks de Chrome 147 con `Page.navigate`).
  - Fallback automático a Playwright si CDP falla (lanza `Trace`
    con `error` en vez de raise).
  - Helpers `trace_to_markdown`, `trace_to_jsonl`, `third_party_domains`.
  - Tool MCP nueva: `apex_browser_trace` (capture_dom, save_jsonl,
    use_fallback, include_dom_in_output).
  - 17 tests: puros (modelos/serialización) + integración real contra
    HTTP server local (1.5s con Chrome). Total: **171 verde**.
  - Lección: Chrome 147 emite eventos network sólo si la red llega al
    target — sin internet la pestaña queda en about:blank pese a que la
    URL del target cambia. Tests usan loopback local, no `example.com`.

- [x] **Sprint 10 — Phase 1-3 v2** (2026-05-03)
  - `lib/design_md.py` (220L): scaffold DESIGN.md estándar Google Labs
    (5 secciones obligatorias: Brand, Color, Type, Components,
    Accessibility/Dark) + validador WCAG AA contraste text/bg.
  - `lib/research.py` (180L): fetch_static (httpx) + fetch_spa
    (chromium --dump-dom con virtual-time-budget=8000ms) + extract_signals
    (title, H1, H2, nav, CTAs, paleta hex, fuentes). Sin obligar Scrapling.
  - 3 tools MCP nuevas: `apex_design_md_init`, `apex_design_md_validate`,
    `apex_research_competitor`.
  - Fase 02-design.md endurecida: nuevo paso `[2f-bis]` exige DESIGN.md
    commiteado validado, nuevo Bloque C de research mínimo de 3
    competidores, paso `[2o]` valida antes de cerrar y `[2p]` invoca
    grader.
  - Fase 03-spec.md endurecida: paso `[3c-bis]` exige referenciar tokens
    reales del DESIGN.md en lugar de descripciones textuales.
  - 28 tests nuevos (17 design_md + 11 research). Total: **154 verde**.

- [x] **Sprint 9 — Context hygiene** (2026-05-03)
  - `lib/handoff.py` (213L): estimate_tokens_in_transcript (chars/4),
    serialize_handoff a `.apex/handoff/{session_id}.md` con fase actual,
    verdicts del grader bloqueando, goals activos, decisiones recientes.
  - `lib/token_filter.py` (105L): should_archive (chars/líneas/patrones
    pip/npm/dep-trees), summarize_for_context (head+omitidos+tail).
  - `.claude/hooks/context-watch.py` (UserPromptSubmit): mide transcript
    JSONL, si >40% del context limit (env APEX_HANDOFF_THRESHOLD,
    default 0.40 sobre 200K), inyecta aviso al agente con instrucciones
    para handoff.
  - `.claude/hooks/post-tool-archive.py` (PostToolUse): stderr aviso
    cuando output de Bash/Read/Playwright/GitHub supera 5000 chars
    (env APEX_ARCHIVE_THRESHOLD_CHARS).
  - Tabla `tool_output_archive` en context.db con CRUD.
  - 4 tools MCP nuevas: `apex_handoff_write`, `apex_resume_session`,
    `apex_archive_output`, `apex_get_archived`.
  - 28 tests nuevos (14 handoff + 14 token_filter). Total: **126 verde**.
  - Auto-migración del schema en BDs APEX existentes (commit `0bee3aa`):
    `_ensure_db_schema` se llama una vez por path en cada vida del
    proceso MCP. Aplica a las 10 BDs en `~/RoadToDevOps/*/.apex/`.

### Legacy (rama `archive/legacy-web`, no se usa en CLI)

El backend web (FastAPI + ChromaDB) y el frontend Next.js fueron
explorados al inicio del proyecto pero **NO se usan en el flujo actual**.
APEX en producción es puro CLI + MCP + skills + apex-hub. Los directorios
`backend/` y `frontend/` siguen en main por inercia histórica; se moverán
a la rama `archive/legacy-web` en un chore futuro.

### NO Completado (Sprints 11-13 del roadmap aprobado)

- [x] **Sprint 11 — Living ecosystem** (~~11.1 browser-trace~~ ✓, ~~11.2 skill_forge~~ ✓, ~~11.3 library_ingest~~ ✓)
- [x] **Sprint 12 — Virtual office** ✓ (5 roles: architect, implementer, reviewer, qa, devops como subagents nativos)
- [x] **Sprint 13 — Apex-doctor** ✓ (auto-mejora dirigida por intención: hook UserPromptSubmit con triggers semánticos + edad de sesión, 3 analizadores)
- [ ] **Dreaming** — Promoción automática de señales a memoria permanente
- [ ] **Embeddings locales** — nomic-embed-text para búsqueda semántica en wiki
- [ ] **Integración Pencil MCP** — Diseños automáticos en fase 2

---

## Stack

| Componente    | Tecnología                         | Estado        |
| ------------- | ---------------------------------- | ------------- |
| Context DB    | Python + aiosqlite + FTS5 + grader_verdicts + tool_output_archive + tool_call_log + skill_forge_rejections + library_imports + role_invocations + doctor_runs + doctor_proposals + session_starts | Verificado |
| Usage data reader (Sprint 13.9) | lib/usage_data_reader.py — `~/.claude/usage-data/` cruce con grader vía heurística temporal | 8 tests |
| Apex-doctor A5+A6 (Sprint 13.9) | grader_false_positives + friction_recurrence | 12 tests |
| Wiki Scaffold | Python puro (Markdown)             | Verificado    |
| Skills        | Markdown (SKILL.md)                | 19 skills     |
| MCP server    | Python + mcp.server                | 42 tools      |
| Apex-doctor (Sprint 13) | lib/apex_doctor.py + lib/wrapup_phrases.py | 72 tests, 3 analizadores |
| Roles (Sprint 12) | lib/roles.py (5 subagents)     | 45 tests      |
| Hooks         | Python scripts                     | 7 (session, design-lint, phase-gate, context-watch, post-tool-archive, skill-forge-watch, end-of-day-doctor) |
| Library Ingest| lib/library_ingest.py (Sprint 11.3)| 35 tests, GitHub + library-skills CLI |
| Skill Forge   | lib/skill_forge.py (Sprint 11.2)   | 27 tests, 3 detectores |
| Browser trace | lib/browser_trace.py (Sprint 11.1) | 17 tests, CDP nativo |
| Grader        | lib/grader.py (Sprint 8.1)         | 25 tests      |
| /goal loop    | lib/goal_loop.py (Sprint 8.2)      | 18 tests      |
| Handoff       | lib/handoff.py (Sprint 9.1)        | 14 tests      |
| Token filter  | lib/token_filter.py (Sprint 9.2)   | 14 tests      |
| DESIGN.md     | lib/design_md.py (Sprint 10.1)     | 17 tests      |
| Research      | lib/research.py (Sprint 10.2)      | 11 tests      |
| Hub bridge    | apex-hub `/api/live/event` + `/api/hub/search-cross-project` | Sprint 8.3 |
| Tests totales | pytest                             | 396 pasando   |
| Backend web   | FastAPI (legacy, no usado)         | archive/legacy-web |
| Frontend web  | Next.js 15 (legacy, no usado)      | archive/legacy-web |

---

## Cómo Ejecutar

### Tests

```bash
cd ~/RoadToDevOps/apex
PYTHONPATH=lib .venv/bin/pytest tests/ -v
```

### Backend (modo producción con Ollama)

```bash
cd ~/RoadToDevOps/apex/backend
PYTHONPATH=. .venv/bin/uvicorn application.api:app --port 8020 --reload
```

### Frontend

```bash
cd ~/RoadToDevOps/apex/frontend
npm run dev
```

---

## Errores Conocidos a Evitar

1. Construir frontend antes de verificar backend
2. No investigar fuentes de datos antes de escribir scrapers
3. Tomar decisiones de diseño sin consultar al usuario
4. SPEC monolítica sin checkpoints
5. Hardcoded data en frontend
6. Sin tildes ni eñes en español
7. CORS abierto y sin auth al inicio
8. No generar edge cases antes del código
9. Asumir siempre "app web con dashboard"
10. No usar awesome-design-md como referencia visual
11. Ir de prisa en vez de diseñar bien

---

## Próximos Pasos (Priorizados)

### P0 — Core (sin esto APEX no funciona en producción)

1. MCP server para context.db (Claude Code accede sin scripts)
2. Hook de SessionStart que lee context.db automáticamente
3. Probar flujo completo: /apex en proyecto nuevo de verdad

### P1 — Calidad

4. Dreaming: promoción de señales cortas a memoria permanente
5. Skill de security audit (OWASP + STRIDE)
6. Skill de code review (verificador)
7. Embeddings locales para wiki (nomic-embed-text)

### P2 — Polish

8. Tests E2E del flujo completo
9. Documentación de cada skill con ejemplos
10. Integración con Pencil MCP para fase 2

### P3 — Open Source

11. Limpiar código para publicación
12. Escribir CONTRIBUTING.md
13. Crear issues de GitHub para roadmap
14. Publicar como open source
