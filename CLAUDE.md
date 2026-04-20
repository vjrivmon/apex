# CLAUDE.md — APEX

> Fuente de verdad del estado del proyecto. Última actualización: 2026-04-20

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

- [x] **12 Skills**
  - Core: `socratic`, `architect`, `flow-guardian`, `iterate`,
    `onboard-existing`, `tools-integration`
  - Diseño: `design-system`, `design-research`, `brand-identity`
  - Entrega: `portfolio-publisher`, `devops`, `monitor`
  - Segundo cerebro: `second-brain`
  - Seguridad: `security-audit` (con AgentArmor)
  - Revisión: `code-review`
  - `flow-guardian/SKILL.md` — Vigilante de 14 fases + gate 10.5 con criterios
  - `iterate/SKILL.md` — Guía para fases 12-14

- [x] **Backend web** (modo producción con Ollama)
  - Arquitectura hexagonal (core/domain/agents/ports + infrastructure +
    application)
  - 8 agentes: Orchestrator, Conversation, Architect, RAG, CodeGen, SkillGen,
    Review, Eval
  - FastAPI + WebSocket + 14 endpoints REST
  - RAG: 7 patrones SMA + 21 casos reales de Vicente indexados en ChromaDB

- [x] **Frontend** (Next.js 15, estilo Linear dark)
  - 9 páginas: landing, dashboard, session, patterns, projects, skills, monitor
  - Componentes: ChatInterface, OptionCards, PhaseIndicator, ArchitectureCard,
    CodePreview
  - Todo en español con tildes

### NO Completado

- [ ] **MCP server** para acceder a context.db desde Claude Code
- [ ] **Dreaming** — Promoción automática de señales a memoria permanente
- [ ] **Skill security audit** — Inspirado en gstack `/cso` (OWASP + STRIDE)
- [ ] **Skill code review** — Agente verificador post-implementación
- [ ] **Embeddings locales** — nomic-embed-text para búsqueda semántica en wiki
- [ ] **Integración Pencil MCP** — Diseños automáticos en fase 2
- [ ] **Tests del backend web** — Solo context_db está testeado (28 tests)
- [ ] **Frontend no conectado al backend** — Existe pero no se usa en modo CLI

---

## Stack

| Componente    | Tecnología                         | Estado        |
| ------------- | ---------------------------------- | ------------- |
| Context DB    | Python + aiosqlite + FTS5          | ✅ Verificado |
| Wiki Scaffold | Python puro (Markdown)             | ✅ Verificado |
| Skills        | Markdown (SKILL.md)                | ✅ 4 skills   |
| Backend       | Python 3.12+ / FastAPI             | ✅ Compila    |
| Frontend      | Next.js 15 / TypeScript / Tailwind | ✅ Compila    |
| LLMs (prod)   | Ollama (gemma4, deepseek-r1, qwen) | Configurado   |
| RAG           | ChromaDB (7 patrones + 21 casos)   | Indexado      |
| Tests         | pytest                             | 28 pasando    |

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
