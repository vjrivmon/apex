"""Standalone script to populate ChromaDB with SMA patterns and real cases.

Run once (or re-run to upsert):
    python -m infrastructure.rag.ingest_patterns
"""

from __future__ import annotations

import asyncio
import logging
import sys

# Ensure backend root is on sys.path when invoked as a script
from pathlib import Path

_backend_root = str(Path(__file__).resolve().parent.parent.parent)
if _backend_root not in sys.path:
    sys.path.insert(0, _backend_root)

from infrastructure.rag.chroma_adapter import ChromaAdapter  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SMA Patterns
# ---------------------------------------------------------------------------

SMA_PATTERNS: list[dict] = [
    {
        "id": "pattern-pipeline",
        "document": (
            "Pipeline Pattern: Agents are chained sequentially — the output of one "
            "agent becomes the input of the next.  Best for linear, well-defined "
            "workflows where each stage adds incremental value (e.g. ETL, document "
            "processing, multi-step reasoning).  Pros: simple to reason about, easy "
            "to debug, deterministic ordering.  Cons: high latency (serial), single "
            "point of failure per stage, no parallelism.  "
            "Ref: 'Multi-Agent Software Development' (Qian et al., 2023)."
        ),
        "metadata": {
            "pattern": "pipeline",
            "when_to_use": "Linear workflows, ETL, sequential document processing",
            "pros": "Simple, deterministic, easy to debug",
            "cons": "High latency, no parallelism, single point of failure per stage",
            "paper_ref": "Qian et al. 2023 — ChatDev",
        },
    },
    {
        "id": "pattern-orchestrator-worker",
        "document": (
            "Orchestrator-Worker Pattern: A central orchestrator agent decomposes tasks "
            "and delegates sub-tasks to specialised worker agents.  The orchestrator "
            "collects results and synthesises the final output.  Best for complex "
            "problems that can be decomposed into independent sub-tasks.  "
            "Pros: parallel execution, clear separation of concerns, workers are "
            "replaceable.  Cons: orchestrator is a bottleneck and single point of "
            "failure, requires careful task decomposition.  "
            "Ref: 'AutoGen: Enabling Next-Gen LLM Applications' (Wu et al., 2023)."
        ),
        "metadata": {
            "pattern": "orchestrator-worker",
            "when_to_use": "Complex decomposable problems, parallel sub-tasks",
            "pros": "Parallel execution, separation of concerns, workers replaceable",
            "cons": "Orchestrator bottleneck, complex task decomposition",
            "paper_ref": "Wu et al. 2023 — AutoGen",
        },
    },
    {
        "id": "pattern-consensus",
        "document": (
            "Consensus Pattern: Multiple agents independently solve the same problem, "
            "then a judge/aggregator agent selects or synthesises the best answer.  "
            "Best for high-stakes decisións where reliability matters more than speed "
            "(e.g. code review, medical diagnosis triage).  "
            "Pros: fault tolerance, diverse perspectives, reduces hallucination.  "
            "Cons: expensive (N x computation), needs a good aggregation strategy.  "
            "Ref: 'LLM-Debate: Improving Factuality' (Du et al., 2023)."
        ),
        "metadata": {
            "pattern": "consensus",
            "when_to_use": "High-stakes decisións, reliability over speed",
            "pros": "Fault tolerant, diverse perspectives, reduces hallucination",
            "cons": "Expensive (N x computation), needs aggregation strategy",
            "paper_ref": "Du et al. 2023 — LLM-Debate",
        },
    },
    {
        "id": "pattern-expert-network",
        "document": (
            "Expert Network Pattern: A router agent analyses the incoming request and "
            "directs it to one or more domain-expert agents.  Each expert has deep "
            "knowledge in a specific area (e.g. security expert, UX expert, DB expert).  "
            "Best for multi-domain problems that require specialised knowledge.  "
            "Pros: high quality per domain, scalable (add experts independently), "
            "natural mapping to real team structures.  "
            "Cons: routing accuracy is critical, expert silos can miss cross-domain "
            "issues.  "
            "Ref: 'Mixture-of-Agents' (Wang et al., 2024)."
        ),
        "metadata": {
            "pattern": "expert-network",
            "when_to_use": "Multi-domain problems, specialised knowledge needed",
            "pros": "High quality per domain, scalable, maps to team structures",
            "cons": "Routing accuracy critical, expert silos",
            "paper_ref": "Wang et al. 2024 — Mixture-of-Agents",
        },
    },
    {
        "id": "pattern-reactor",
        "document": (
            "Reactor Pattern: An event-driven architecture where agents react to events "
            "asynchronously.  An event bus dispatches messages; agents subscribe to "
            "relevant event types.  Best for real-time systems, monitoring, and "
            "workflows with unpredictable timing (e.g. IoT, chatbots, alert systems).  "
            "Pros: decoupled, highly scalable, natural async model.  "
            "Cons: harder to debug (non-deterministic ordering), eventual consistency, "
            "complex error handling.  "
            "Ref: 'Event-Driven Multi-Agent Systems' (Wooldridge, 2009)."
        ),
        "metadata": {
            "pattern": "reactor",
            "when_to_use": "Real-time systems, IoT, monitoring, chatbots",
            "pros": "Decoupled, scalable, natural async model",
            "cons": "Hard to debug, eventual consistency, complex error handling",
            "paper_ref": "Wooldridge 2009 — Multi-Agent Systems",
        },
    },
    {
        "id": "pattern-reflection",
        "document": (
            "Reflection Pattern: An executor agent produces output, then a critic/reviewer "
            "agent evaluates it and sends feedback.  The executor iterates until the "
            "critic approves.  Best for tasks that benefit from iterative refinement "
            "(e.g. code generation, essay writing, design).  "
            "Pros: self-improving output, catches errors iteratively, mirrors human "
            "review process.  Cons: convergence not guaranteed, can loop forever "
            "without a max-iterations cap.  "
            "Ref: 'Reflexion: Language Agents with Verbal Reinforcement Learning' "
            "(Shinn et al., 2023)."
        ),
        "metadata": {
            "pattern": "reflection",
            "when_to_use": "Iterative refinement, code review, quality improvement",
            "pros": "Self-improving, catches errors, mirrors human review",
            "cons": "Convergence not guaranteed, may loop without cap",
            "paper_ref": "Shinn et al. 2023 — Reflexion",
        },
    },
    {
        "id": "pattern-hybrid",
        "document": (
            "Hybrid Pattern: Combines two or more patterns to address complex "
            "requirements.  For example: an orchestrator-worker backbone with "
            "reflection loops on each worker, or a pipeline with consensus voting "
            "at critical stages.  Best for production systems that need both "
            "parallelism and quality guarantees.  "
            "Pros: flexible, best-of-breed composition, mirrors real-world "
            "complexity.  Cons: highest design complexity, harder to test, "
            "requires clear documentation of which sub-pattern governs each "
            "interaction.  "
            "Ref: 'APEX Design Methodology' (Rivas, 2025)."
        ),
        "metadata": {
            "pattern": "hybrid",
            "when_to_use": "Complex production systems needing multiple guarantees",
            "pros": "Flexible, best-of-breed, mirrors real complexity",
            "cons": "Highest design complexity, harder to test",
            "paper_ref": "Rivas 2025 — APEX Design Methodology",
        },
    },
]

# ---------------------------------------------------------------------------
# Real Cases
# ---------------------------------------------------------------------------

REAL_CASES: list[dict] = [
    # --- Proyectos reales de Vicente Rivas (~/RoadToDevOps/) ---
    {
        "id": "case-claude-007-agents",
        "document": (
            "claude-007-agents: Sistema avanzado de orquestación multi-agente con "
            "68 agentes especializados en una jerarquía de 4 niveles. "
            "Nivel 1: Master Orchestrator (coordinación estratégica). "
            "Nivel 2: Directors (decisión por dominio: backend, frontend, infra, seguridad). "
            "Nivel 3: Planners (análisis especializado). "
            "Nivel 4: Specialists (implementación). "
            "Incluye matrices de compatibilidad entre agentes, circuit breakers, "
            "retries con backoff, y logging estructurado JSON. "
            "Stack: Node.js, TypeScript, MCP (Model Context Protocol), Claude models. "
            "Ubicación: ~/RoadToDevOps/claude-007-agents/. "
            "Lección clave: la jerarquía de 4 niveles permite escalar a 68+ agentes "
            "sin perder coherencia; las matrices de compatibilidad evitan conflictos."
        ),
        "metadata": {
            "case": "claude-007-agents",
            "domain": "Desarrollo de software / Orquestación IA",
            "pattern": "orchestrator-worker",
            "agents": 68,
            "stack": "Node.js, TypeScript, MCP, Claude",
            "result": "68 agentes coordinados en 4 niveles jerárquicos",
        },
    },
    {
        "id": "case-claude-agent-bootstrap",
        "document": (
            "claude-agent-bootstrap: Framework para construir sistemas de agentes "
            "inteligentes con separación clara de responsabilidades. "
            "Arquitectura jerárquica de 4 niveles con selección de modelo por nivel: "
            "Level 1 Orchestrator (Claude Opus, coordinación estratégica), "
            "Level 2 Directors (Claude Sonnet, decisiones por dominio), "
            "Level 3 Planners (Claude Haiku, análisis especializado), "
            "Level 4 Specialists (Sonnet/Opus, implementación). "
            "Generación de proyectos basada en templates. Auto-configuración "
            "según stack tecnológico detectado. "
            "Stack: Node.js, TypeScript, Claude Opus/Sonnet/Haiku. "
            "Ubicación: ~/RoadToDevOps/claude-agent-bootstrap/. "
            "Lección clave: asignar modelos por coste/capacidad a cada nivel "
            "optimiza el presupuesto sin sacrificar calidad en decisiones críticas."
        ),
        "metadata": {
            "case": "claude-agent-bootstrap",
            "domain": "Framework de agentes / Meta-herramienta",
            "pattern": "orchestrator-worker",
            "agents": 4,
            "stack": "Node.js, TypeScript, Claude Opus/Sonnet/Haiku",
            "result": "Framework reutilizable con selección de modelo por nivel",
        },
    },
    {
        "id": "case-catan-coach",
        "document": (
            "Catan Coach: Asistente de coaching IA para el juego Colonos de Catan. "
            "Arquitectura hexagonal con patrón expert-network y 7 agentes: "
            "RouterAgent (clasifica preguntas reglas vs estrategia), "
            "RulesAgent (RAG sobre reglas oficiales), "
            "StrategyAgent (RAG sobre guías de estrategia), "
            "GeneratorAgent (generación de respuestas), "
            "SuggestionAgent (preguntas relacionadas), "
            "LevelDetector (progresión de nivel del jugador), "
            "ConceptTracker (persistencia de aprendizaje). "
            "Stack: Next.js 16, Ollama (gemma3:27b, qwen3:8b), ChromaDB. "
            "Mobile-first, offline-capable (localStorage), Web Speech API. "
            "Ubicación: ~/RoadToDevOps/catan-coach/. "
            "Lección clave: RAG dual (reglas + estrategia) en colecciones separadas "
            "mejoró drásticamente la precisión; detección de nivel progresiva "
            "personaliza la experiencia."
        ),
        "metadata": {
            "case": "Catan Coach",
            "domain": "Gaming / Educación",
            "pattern": "expert-network",
            "agents": 7,
            "stack": "Next.js, Ollama, ChromaDB",
            "result": "RAG dual con 7 agentes especializados, mobile-first",
        },
    },
    {
        "id": "case-agent-forge",
        "document": (
            "AgentForge: Chat conversacional que transforma un problema real en un "
            "Sistema Multi-Agente (SMA) con arquitectura hexagonal. "
            "El propio AgentForge es un SMA con patrón orquestador-worker: "
            "ConversationAgent (gemma4:e4b, chat fluido), "
            "ArchitectAgent (deepseek-r1:14b, árbol de decisión), "
            "RAGAgent (gemma4:e2b, recupera patrones), "
            "CodeGenAgent (qwen3:32b via VRAIN, genera hexagonal), "
            "OrchestratorAgent (coordina sin procesar). "
            "7 patrones SMA en ChromaDB + 5 casos reales. "
            "Flujo: KICKOFF -> ANALYSIS -> AGENT_DESIGN -> ARCHITECTURE -> CODE_GEN -> EVAL -> EXPORT. "
            "Stack: FastAPI, Next.js 15, Ollama/VRAIN, ChromaDB. "
            "Ubicación: ~/RoadToDevOps/agent-forge/. "
            "Lección clave: dogfooding (el sistema usa su propio patrón) valida "
            "la arquitectura; modelos 100% locales eliminan dependencia de APIs."
        ),
        "metadata": {
            "case": "AgentForge",
            "domain": "Meta-herramienta / Diseño de agentes",
            "pattern": "orchestrator-worker",
            "agents": 5,
            "stack": "FastAPI, Next.js 15, Ollama, VRAIN, ChromaDB",
            "result": "Genera SMAs completos con código hexagonal",
        },
    },
    {
        "id": "case-smart-agent-workflow",
        "document": (
            "Smart Agent Workflow MCP: Automatización de flujos de desarrollo con "
            "MCP (Model Context Protocol) y gestión de estado. "
            "Patrón reactor (event-driven): eventos de git disparar agentes. "
            "Funcionalidades: aislamiento con git worktrees, gates obligatorios "
            "de tests E2E, verificación de build con auto-rollback, "
            "persistencia de memoria entre sesiones, knowledge graph. "
            "Stack: TypeScript, Node.js, MCP SDK, Playwright (E2E). "
            "Ubicación: ~/RoadToDevOps/smart-agent-workflow-mcp/. "
            "Lección clave: los worktrees de git proporcionan aislamiento "
            "perfecto para desarrollo paralelo; los gates de E2E previenen "
            "regressions antes del merge."
        ),
        "metadata": {
            "case": "Smart Agent Workflow MCP",
            "domain": "DevOps / Automatización",
            "pattern": "reactor",
            "agents": 3,
            "stack": "TypeScript, Node.js, MCP SDK, Playwright",
            "result": "Workflow automatizado con gates E2E y knowledge graph",
        },
    },
    {
        "id": "case-career-ops",
        "document": (
            "Career Ops: Pipeline de orquestación de tareas para búsqueda de "
            "empleo automatizada. Patrón pipeline con worker coordination. "
            "Componentes: portal scanners (45+ empresas preconfiguradas), "
            "procesamiento batch con coordinación de workers, "
            "generación de PDF (CVs optimizados para ATS), "
            "verificación de integridad. "
            "Stack: Node.js, TypeScript, Playwright (PDF), YAML config. "
            "Ubicación: ~/RoadToDevOps/career-ops/. "
            "Lección clave: la configuración basada en YAML permitió "
            "añadir 45+ portales sin cambiar código; Playwright para "
            "PDF es más fiable que librerías dedicadas."
        ),
        "metadata": {
            "case": "Career Ops",
            "domain": "Automatización / Productividad",
            "pattern": "pipeline",
            "agents": 4,
            "stack": "Node.js, TypeScript, Playwright, YAML",
            "result": "45+ portales automatizados, CVs ATS-optimized",
        },
    },
    {
        "id": "case-osyris",
        "document": (
            "Osyris: Sistema de gestión para grupo scout con agentes IA "
            "especializados por área operativa. "
            "Patrón expert-network: cada dominio (actividades, tesorería, "
            "comunicación, formación) tiene su propio agente. "
            "Stack: Next.js 15, React 19, TypeScript, Express.js, MySQL, JWT. "
            "Integración con Google Drive, dark mode, mobile-first. "
            "Testing: Jest + Playwright. "
            "Ubicación: ~/RoadToDevOps/osyris/. "
            "Lección clave: agentes por dominio operativo mapean "
            "perfectamente la estructura organizacional real."
        ),
        "metadata": {
            "case": "Osyris",
            "domain": "Gestión organizacional / ONG",
            "pattern": "expert-network",
            "agents": 5,
            "stack": "Next.js 15, Express.js, MySQL, JWT",
            "result": "Gestión scout completa con agentes por área",
        },
    },
    {
        "id": "case-encesa",
        "document": (
            "Encesa: PWA offline-first para gestión de gastos con OCR. "
            "Patrón pipeline: captura imagen -> OCR (Tesseract.js client-side) -> "
            "extracción de datos -> almacenamiento IndexedDB -> sync manual a Supabase. "
            "Funciona 100% offline, instalable en iOS Safari. "
            "Stack: Vite, React 18, TypeScript, Dexie.js (IndexedDB), Supabase, Tesseract.js. "
            "Ubicación: ~/RoadToDevOps/encesa/. "
            "Lección clave: IndexedDB como almacenamiento primario con sync "
            "manual elimina la dependencia de conectividad; OCR client-side "
            "con Tesseract.js evita enviar imágenes al servidor."
        ),
        "metadata": {
            "case": "Encesa",
            "domain": "Finanzas personales / PWA",
            "pattern": "pipeline",
            "agents": 4,
            "stack": "Vite, React, Dexie.js, Supabase, Tesseract.js",
            "result": "PWA 100% offline con OCR client-side",
        },
    },
    {
        "id": "case-neurospot",
        "document": (
            "NeuroSpot: Plataforma de detección temprana de TDAH en niños "
            "mediante juegos cognitivos + análisis de voz e imagen. "
            "Patrón pipeline: SessionCoordinator -> GameDataCollectors -> "
            "NeuroAnalyzer -> ReportGenerator. "
            "Usa AWS SageMaker para ML, Rekognition para análisis facial, "
            "S3 para almacenamiento. "
            "Stack: Next.js, AWS (SageMaker, Rekognition, S3), React. "
            "Ubicación: ~/RoadToDevOps/NeuroSpot/. "
            "Lección clave: combinar múltiples señales (cognitiva, vocal, visual) "
            "mejora drásticamente la precisión del screening; "
            "AWS services permiten escalar el ML sin infra propia."
        ),
        "metadata": {
            "case": "NeuroSpot",
            "domain": "Salud / Detección TDAH",
            "pattern": "pipeline",
            "agents": 4,
            "stack": "Next.js, AWS SageMaker/Rekognition/S3",
            "result": "Screening TDAH multi-señal con ML en cloud",
        },
    },
    {
        "id": "case-meridian",
        "document": (
            "Meridian: IDE agéntico de escritorio que automatiza el desarrollo de software "
            "a través de 13 fases autónomas, cada una con un agente dedicado. "
            "Fases: Discovery, Specification, Architecture, UX/Flows, User Stories, Tasks, "
            "Scaffold, Core, Interfaces, Testing, Review, Staging, Production. "
            "Stack: React 19 + TypeScript + Tailwind CSS + Monaco Editor (frontend), "
            "Tauri (Rust) con SQLite (backend), Ollama (LLM local). "
            "Zustand para estado persistido, xterm.js para terminal integrado. "
            "21 tests pasando, auto-commits por fase. "
            "Ubicación: ~/RoadToDevOps/meridian/. "
            "Lección clave: un agente por fase de desarrollo permite flexibilidad; "
            "Monaco Editor proporciona edición potente sin dependencias externas."
        ),
        "metadata": {
            "case": "Meridian",
            "domain": "Herramientas de desarrollo / IDE",
            "pattern": "pipeline",
            "agents": 13,
            "stack": "React 19, Tauri/Rust, SQLite, Ollama, Monaco Editor",
            "result": "IDE con 13 fases autónomas de desarrollo",
        },
    },
    {
        "id": "case-feedback-juanmi",
        "document": (
            "FeedbackIA (feedback-juanmi): SMA con arquitectura hexagonal para generar "
            "feedback académico personalizado a estudiantes universitarios. "
            "10 agentes: FeedbackAgent, QualityAgent, StyleAgent, MetricsAgent, "
            "SessionReviewAgent, CoherenceAgent, DiffExplanationAgent, "
            "PromptEvolutionAgent, OrchestratorAgent, BenchmarkAgent. "
            "A/B testing ciego con 4 modelos (gemma3:27b, llama3.3:70b, deepseek-v3.2, qwen3:32b). "
            "Dashboard de observabilidad en tiempo real con grafo de agentes. "
            "Stack: FastAPI (port 8002), Next.js 16, Ollama via VRAIN UPV, SQLite. "
            "24 tests pasando. "
            "Ubicación: ~/RoadToDevOps/feedback-juanmi/. "
            "Lección clave: style profile learning del profesor mejora consistencia; "
            "A/B testing ciego revela diferencias reales entre modelos."
        ),
        "metadata": {
            "case": "FeedbackIA",
            "domain": "Educación / EdTech",
            "pattern": "orchestrator-worker",
            "agents": 10,
            "stack": "FastAPI, Next.js 16, Ollama/VRAIN, SQLite",
            "result": "10 agentes con A/B testing y observabilidad real-time",
        },
    },
    {
        "id": "case-catan-advisor-api",
        "document": (
            "Catan Advisor API: Backend FastAPI con visión IA y algoritmo genético "
            "para coaching en Catan. Analiza fotos del tablero con qwen2.5vl:7b "
            "y recomienda movimientos óptimos usando un cromosoma de 93 parámetros "
            "entrenado en 40.000 partidas simuladas. "
            "Endpoints: POST /vision/analyze (foto a BoardState), "
            "POST /coach/recommend (recursos a acción óptima), "
            "POST /game/new (sesión compartible CTN-XXXX). "
            "Storage: Redis con fallback a JSON. 29 tests. "
            "Stack: FastAPI, Ollama qwen2.5vl:7b, Redis. "
            "Ubicación: ~/RoadToDevOps/catan-advisor-api/. "
            "Lección clave: modelos de visión extraen estado del tablero de fotos; "
            "93 parámetros genéticos entrenados en 40K juegos dan coaching robusto."
        ),
        "metadata": {
            "case": "Catan Advisor API",
            "domain": "Gaming / Visión IA",
            "pattern": "pipeline",
            "agents": 3,
            "stack": "FastAPI, Ollama qwen2.5vl, Redis, Algoritmo Genético",
            "result": "93 params, 40K juegos, 29 tests",
        },
    },
    {
        "id": "case-gestion-centromat",
        "document": (
            "Gestión Centromat: Sistema Kanban digital para imprenta con arquitectura "
            "hexagonal y PWA. Reemplaza libretas de papel por tablero digital. "
            "4 columnas: Por Hacer, En Proceso, Hecho, Pagado. "
            "Formularios dinámicos por categoría (impresión/fotografía/acabados). "
            "Cmd+K spotlight search, historial de clientes, drag & drop nativo. "
            "Stack: Next.js 16, TypeScript, Tailwind CSS v4, Firebase (Auth+Firestore+Storage). "
            "4 roles: superadmin, admin, operador. "
            "Deploy: export estático en Plesk (gestion.centromat.info). "
            "Ubicación: ~/RoadToDevOps/gestion-centromat/. "
            "Lección clave: Firebase permite colaboración en tiempo real sin backend; "
            "drag & drop nativo HTML5 es más fiable que librerías."
        ),
        "metadata": {
            "case": "Gestión Centromat",
            "domain": "Gestión empresarial / Kanban",
            "pattern": "pipeline",
            "agents": 0,
            "stack": "Next.js 16, Firebase, Tailwind CSS v4, PWA",
            "result": "Sistema Kanban en producción para imprenta real",
        },
    },
    {
        "id": "case-tutor-ohm",
        "document": (
            "Tutor Ohm: Sistema de benchmarking enterprise para evaluar LLMs como "
            "tutores socráticos especializados en circuitos y Ley de Ohm. "
            "Detecta 4 concepciones alternativas automáticamente: "
            "AC1 (circuito abierto), AC6 (cortocircuito), AC9 (razonamiento local), "
            "AC14 (topología serie/paralelo). "
            "7 ejercicios con complejidad creciente. "
            "Soporta 6+ modelos LLM: DeepSeek R1, Llama 3.1, Qwen 2.5, Phi 4, etc. "
            "Dashboard en tiempo real con WebSocket. "
            "Stack: FastAPI, React 18.2+, Ollama, Docker. "
            "Ubicación: ~/RoadToDevOps/tutor_ohm/. "
            "Lección clave: detección automática de concepciones erróneas mejora "
            "la tutoría; el método socrático requiere adherencia estricta."
        ),
        "metadata": {
            "case": "Tutor Ohm",
            "domain": "Educación / Benchmarking LLM",
            "pattern": "pipeline",
            "agents": 3,
            "stack": "FastAPI, React, Ollama, Docker, WebSocket",
            "result": "Benchmark de 6+ LLMs con detección de concepciones erróneas",
        },
    },
    {
        "id": "case-rag-redes",
        "document": (
            "RAG Redes y Sistemas: Sistema educativo RAG para tutoría de redes "
            "informáticas y sistemas. Incluye sistema de exámenes adaptativos "
            "que ajusta la dificultad según rendimiento del alumno. "
            "20 preguntas por examen, escalado: Fácil -> Medio -> Difícil. "
            "Pistas contextuales para respuestas incorrectas. "
            "Stack: Node.js, ChromaDB, Ollama. "
            "Ubicación: ~/RoadToDevOps/RAG-Redes-y-Sistemas/. "
            "Lección clave: dificultad adaptativa mejora engagement; "
            "ChromaDB vector search es efectivo para educación."
        ),
        "metadata": {
            "case": "RAG Redes y Sistemas",
            "domain": "Educación / RAG adaptativo",
            "pattern": "pipeline",
            "agents": 2,
            "stack": "Node.js, ChromaDB, Ollama",
            "result": "Exámenes adaptativos con RAG educativo",
        },
    },
    {
        "id": "case-hyperloop-tc",
        "document": (
            "Hyperloop TC: Simulador de banco de pruebas del booster de Hyperloop UPV. "
            "Motor de física en Go con streaming WebSocket en tiempo real. "
            "Máquina de estados: IDLE -> PRECHARGE -> READY -> RUNNING -> BOOSTING -> "
            "BRAKING -> STOPPED. Velocidad simulación 5x más lento que real. "
            "Calculadora: masa/distancia -> posición óptima de frenado. "
            "Stack: Go 1.22+ (backend), React + TypeScript + Vite + Three.js (frontend). "
            "WebSocket en ws://localhost:5001/backend/stream. "
            "Ubicación: ~/RoadToDevOps/hyperloop-tc/. "
            "Lección clave: simulación basada en física requiere gestión cuidadosa "
            "del timing; WebSocket es excelente para telemetría real-time."
        ),
        "metadata": {
            "case": "Hyperloop TC",
            "domain": "Ingeniería / Simulación",
            "pattern": "reactor",
            "agents": 0,
            "stack": "Go, React, Three.js, WebSocket",
            "result": "Simulador de física en tiempo real para Hyperloop UPV",
        },
    },
    {
        "id": "case-generador-forms",
        "document": (
            "Generador Forms IA: Automatizador de Google Forms usando LLMs locales. "
            "Pipeline: extraer forms existentes -> base de conocimiento -> "
            "lenguaje natural -> especificación -> auto-crear en Google Forms. "
            "Stack: Node.js, Ollama (deepseek-r1:14b, qwen2.5:14b, llama3.3:70b), "
            "Google Forms API + Drive API, OAuth 2.0. "
            "Ubicación: ~/RoadToDevOps/generador-forms-ia/. "
            "Lección clave: LLMs locales proporcionan privacidad y ahorro; "
            "RAG asegura consistencia con formularios existentes."
        ),
        "metadata": {
            "case": "Generador Forms IA",
            "domain": "Automatización / Google Workspace",
            "pattern": "pipeline",
            "agents": 2,
            "stack": "Node.js, Ollama, Google Forms API, OAuth 2.0",
            "result": "Generación automática de formularios con LLM local",
        },
    },
    {
        "id": "case-strambotica",
        "document": (
            "Strambotica: Plataforma e-commerce artesanal con filosofía KISS. "
            "Astro 4.x con islands architecture (mínimo JS client-side). "
            "Supabase para PostgreSQL + Auth + Storage. "
            "Integración BBVA TPV para pagos. Multi-idioma (ES/EN/FR/PT/NL). "
            "31 productos, 658 variantes, inventario dinámico. "
            "10 agentes especializados para desarrollo. "
            "Stack: Astro 4.x, React Islands, Tailwind CSS, Supabase, BBVA TPV. "
            "Ubicación: ~/RoadToDevOps/strambotica/. "
            "Lección clave: principio KISS — simplicidad por defecto, "
            "zero JS innecesario, static > API."
        ),
        "metadata": {
            "case": "Strambotica",
            "domain": "E-commerce / Artesanía",
            "pattern": "pipeline",
            "agents": 10,
            "stack": "Astro 4.x, Supabase, Tailwind CSS, BBVA TPV",
            "result": "E-commerce real con 658 variantes y pagos BBVA",
        },
    },
    {
        "id": "case-react-fastapi-boilerplate",
        "document": (
            "React-FastAPI Boilerplate: Template full-stack con arquitectura hexagonal "
            "en el backend y feature-based en el frontend. "
            "Backend: FastAPI + MongoDB + Motor async + OAuth2 + JWT. "
            "Frontend: React 19 + TypeScript + Vite. "
            "8 agentes especializados de Claude para desarrollo. "
            "Ubicación: ~/RoadToDevOps/react-fastapi-boilerplate/. "
            "Lección clave: la combinación hexagonal (backend) + feature-based "
            "(frontend) proporciona la mejor separación de concerns."
        ),
        "metadata": {
            "case": "React-FastAPI Boilerplate",
            "domain": "Template / Boilerplate",
            "pattern": "orchestrator-worker",
            "agents": 8,
            "stack": "FastAPI, React 19, MongoDB, Motor async, OAuth2",
            "result": "Template reutilizable con arquitectura hexagonal",
        },
    },
    {
        "id": "case-visitech-portfolio",
        "document": (
            "Visitech Portfolio: Portfolio de alto rendimiento con integración "
            "automática de GitHub e ISR (Incremental Static Regeneration). "
            "Datos de proyectos en tiempo real desde GitHub API v3. "
            "ISR: páginas se regeneran cada hora. Webhook para actualizaciones instantáneas. "
            "Lighthouse 90+ en todas las métricas. "
            "Stack: Next.js 14 (App Router), Tailwind CSS, shadcn/ui, Framer Motion, "
            "Vercel (deploy + analytics). "
            "Ubicación: ~/RoadToDevOps/visitech_portfolio/. "
            "Lección clave: ISR elimina el trade-off entre rendimiento y frescura; "
            "GitHub API como fuente de datos reduce mantenimiento manual."
        ),
        "metadata": {
            "case": "Visitech Portfolio",
            "domain": "Portfolio / Personal Branding",
            "pattern": "pipeline",
            "agents": 0,
            "stack": "Next.js 14, Vercel, GitHub API, Framer Motion",
            "result": "Lighthouse 90+, ISR, datos live de GitHub",
        },
    },
    {
        "id": "case-waitlist-hero",
        "document": (
            "Waitlist Hero: Micro-SaaS para pre-lanzamientos de productos. "
            "Sistema de referidos, magic link auth, CSV export, "
            "widget embebible por script. "
            "Stack: Next.js 14, Supabase, Resend (emails). "
            "Ubicación: ~/RoadToDevOps/waitlist-hero/. "
            "Lección clave: un micro-SaaS bien enfocado se construye rápido; "
            "Supabase + Resend cubren auth + emails sin backend custom."
        ),
        "metadata": {
            "case": "Waitlist Hero",
            "domain": "SaaS / Pre-lanzamiento",
            "pattern": "pipeline",
            "agents": 0,
            "stack": "Next.js 14, Supabase, Resend",
            "result": "Micro-SaaS funcional con referidos y widget embebible",
        },
    },
]


# ---------------------------------------------------------------------------
# Ingestion logic
# ---------------------------------------------------------------------------


async def ingest_all() -> None:
    """Populate both ``sma_patterns`` and ``real_cases`` collections."""
    adapter = ChromaAdapter()

    # Ingest patterns
    logger.info("Ingesting %d SMA patterns...", len(SMA_PATTERNS))
    await adapter.add_documents(
        collection="sma_patterns",
        documents=[p["document"] for p in SMA_PATTERNS],
        metadatas=[p["metadata"] for p in SMA_PATTERNS],
        ids=[p["id"] for p in SMA_PATTERNS],
    )
    count = await adapter.get_collection_count("sma_patterns")
    logger.info("sma_patterns collection now has %d documents", count)

    # Ingest real cases
    logger.info("Ingesting %d real cases...", len(REAL_CASES))
    await adapter.add_documents(
        collection="real_cases",
        documents=[c["document"] for c in REAL_CASES],
        metadatas=[c["metadata"] for c in REAL_CASES],
        ids=[c["id"] for c in REAL_CASES],
    )
    count = await adapter.get_collection_count("real_cases")
    logger.info("real_cases collection now has %d documents", count)

    logger.info("Ingestion complete.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    asyncio.run(ingest_all())
