# CLAUDE.md — APEX

## What is APEX?

APEX is a multi-agent system (SMA) that designs and creates other multi-agent
systems. It combines the best of three worlds:

- **agent-forge**: 7 SMA patterns, decision tree, conversational design flow
- **.claude/ system**: SPEC→Stories→Tasks→Skills→Swarm MVP workflow, 150+ skills
- **gstack**: Sprint lifecycle quality gates (Think→Plan→Build→Review→Test→Ship)

## Architecture

Hexagonal (Clean Architecture) with Python backend and Next.js frontend.

```
backend/
├── core/domain/      # Entities (Session, Architecture, AgentSpec, Pattern, Skill, Project, Phase)
├── core/agents/      # 8 agents: Orchestrator, Conversation, Architect, RAG, CodeGen, SkillGen, Review, Eval
├── core/ports/       # Interfaces (ILLMProvider, IVectorStore, ISessionRepository, etc.)
├── infrastructure/   # Adapters (Ollama, VRAIN, ChromaDB, SQLite, ZipExporter)
├── application/      # FastAPI + WebSocket + use cases
└── shared/           # Config, errors, logging
```

## Dual-Mode LLM

- **Development**: Claude Code + MAX subscription is the brain (no API keys
  needed)
- **Production**: Ollama (Slimbook local) + VRAIN (UPV) for zero API cost

## Key Concepts

- **Smart Assessment**: Evaluates if an idea has enough info → skip interview or
  start rounds
- **Option-Based Interview**: Structured questions with clickable options,
  enriched by RAG
- **Learning Loop**: Each completed project feeds knowledge back into ChromaDB
- **Dual Output**: Generates both SMA code (hexagonal) and Claude Code skills

## Stack

- Backend: Python 3.12+, FastAPI, Pydantic, aiosqlite, ChromaDB
- Frontend: Next.js 15 (App Router), TypeScript, Tailwind CSS
- Design: Linear style (dark, minimal, professional)
- Database: SQLite (local), Supabase (if scaling)
- Ports: 8020 (backend), 3020 (frontend)

## Commands

```bash
# Backend
cd backend && PYTHONPATH=. uvicorn application.api:app --host 0.0.0.0 --port 8020 --reload

# Frontend
cd frontend && npm run dev

# Docker
docker compose up -d
```

## Golden Rules (SMA Design)

1. One agent, one responsibility. If you can't describe it in one sentence, it's
   two agents.
2. The orchestrator NEVER processes. It coordinates and delegates.
3. Fail gracefully. Every agent must have a degradation output.
4. Evaluate before deploying. No benchmark = no SMA, just hope.
5. RAG when knowledge changes. Static domain → parameterize. Dynamic →
   vectorize.

## Code Style

- Python: Black formatter, Ruff linter, type hints required
- TypeScript: strict mode, ESLint + Prettier
- Comments explain WHY, not WHAT
