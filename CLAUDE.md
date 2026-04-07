# CLAUDE.md — APEX

> Fuente de verdad del estado del proyecto. Última actualización: 2026-04-07

## Qué es APEX

Sistema de skills para Claude Code que guía el ciclo completo de desarrollo de
software. Usa una BD SQLite contextual por proyecto (`.apex/context.db`) para
que Claude Code nunca pierda el hilo — ni al inicio ni en las fases intermedias.

**No es una app web.** Es un sistema de commands + skills + librería Python que
vive dentro de Claude Code y potencia el flujo de desarrollo.

---

## Estado Actual

### Completado

- [x] **Context DB v2** (`lib/context_db.py`)
  - Temporal facts (valid_from / invalid_from, patrón Graphiti)
  - Progressive disclosure (compact ~200tk / timeline ~800tk / full ~2000tk)
  - Error memory bidireccional con recurrence_count
  - Wiki pages en SQLite con FTS5
  - 28 tests pasando en 0.14s

- [x] **Wiki Scaffold** (`lib/wiki_scaffold.py`)
  - Patrón Karpathy: SCHEMA.md + index.md + log.md
  - 5 directorios: entities, concepts, comparisons, queries, raw
  - Funciones: create_wiki(), append_log(), update_index()

- [x] **Comando /apex** (`commands/apex.md`)
  - 14 fases guiadas (0-socrático a 14-mantenimiento)
  - Detecta proyecto nuevo vs existente
  - 11 errores documentados a evitar
  - Reglas absolutas (Pencil MCP, backend-first, AskUserQuestion)

- [x] **4 Skills core**
  - `socratic/SKILL.md` — Tutor socrático (3-5 rondas)
  - `architect/SKILL.md` — SolutionTypeAdvisor (CLI/bot/MCP/app)
  - `flow-guardian/SKILL.md` — Vigilante de 14 fases con criterios
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
