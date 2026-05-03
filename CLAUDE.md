# CLAUDE.md — APEX

> Fuente de verdad del estado del proyecto. Última actualización: 2026-05-03 (post Sprint 11.1)

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

- [x] **MCP server** completo con 34 tools (Sprints 8-11 cierran esta deuda)

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

- [ ] **Sprint 11 — Living ecosystem** (~~11.1 browser-trace~~ ✓, 11.2 skill_forge auto-creation, 11.3 ingest library-skills.io)
- [ ] **Sprint 12 — Virtual office** (Architect/Implementer/Reviewer/QA/DevOps roles)
- [ ] **Sprint 13 — Apex-doctor** (cron diario, clusters de overrides, self-improvement)
- [ ] **Dreaming** — Promoción automática de señales a memoria permanente
- [ ] **Embeddings locales** — nomic-embed-text para búsqueda semántica en wiki
- [ ] **Integración Pencil MCP** — Diseños automáticos en fase 2

---

## Stack

| Componente    | Tecnología                         | Estado        |
| ------------- | ---------------------------------- | ------------- |
| Context DB    | Python + aiosqlite + FTS5 + grader_verdicts + tool_output_archive | Verificado |
| Wiki Scaffold | Python puro (Markdown)             | Verificado    |
| Skills        | Markdown (SKILL.md)                | 19 skills     |
| MCP server    | Python + mcp.server                | 34 tools      |
| Hooks         | Python scripts                     | 5 (session, design-lint, phase-gate, context-watch, post-tool-archive) |
| Browser trace | lib/browser_trace.py (Sprint 11.1) | 17 tests, CDP nativo |
| Grader        | lib/grader.py (Sprint 8.1)         | 25 tests      |
| /goal loop    | lib/goal_loop.py (Sprint 8.2)      | 18 tests      |
| Handoff       | lib/handoff.py (Sprint 9.1)        | 14 tests      |
| Token filter  | lib/token_filter.py (Sprint 9.2)   | 14 tests      |
| DESIGN.md     | lib/design_md.py (Sprint 10.1)     | 17 tests      |
| Research      | lib/research.py (Sprint 10.2)      | 11 tests      |
| Hub bridge    | apex-hub `/api/live/event` + `/api/hub/search-cross-project` | Sprint 8.3 |
| Tests totales | pytest                             | 171 pasando   |
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
