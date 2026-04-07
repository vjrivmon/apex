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
            "Best for high-stakes decisions where reliability matters more than speed "
            "(e.g. code review, medical diagnosis triage).  "
            "Pros: fault tolerance, diverse perspectives, reduces hallucination.  "
            "Cons: expensive (N x computation), needs a good aggregation strategy.  "
            "Ref: 'LLM-Debate: Improving Factuality' (Du et al., 2023)."
        ),
        "metadata": {
            "pattern": "consensus",
            "when_to_use": "High-stakes decisions, reliability over speed",
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
    {
        "id": "case-feedbackia",
        "document": (
            "FeedbackIA: Multi-agent system for automated student feedback in "
            "university courses.  Uses an orchestrator-worker pattern with 3 agents: "
            "Analyzer (reads student submissions), Evaluator (rubric-based scoring), "
            "and Narrator (generates personalised narrative feedback).  "
            "Stack: Python, FastAPI, Ollama (mistral:7b), ChromaDB for rubric RAG.  "
            "Result: 85% student satisfaction, 60% reduction in professor grading time.  "
            "Domain: Education / EdTech.  Lessons learned: rubric RAG dramatically "
            "improved consistency; smaller models (7B) were sufficient for evaluation."
        ),
        "metadata": {
            "case": "FeedbackIA",
            "domain": "Education",
            "pattern": "orchestrator-worker",
            "agents": 3,
            "stack": "Python, FastAPI, Ollama, ChromaDB",
            "result": "85% satisfaction, 60% grading time reduction",
        },
    },
    {
        "id": "case-catan-coach",
        "document": (
            "Catan Coach: AI-powered coaching assistant for the board game Settlers "
            "of Catan.  Uses a reflection pattern: a Strategy agent proposes moves, "
            "a Critic agent evaluates them against game theory heuristics, and iteration "
            "continues until quality threshold is met.  Stack: TypeScript, Next.js, "
            "Ollama (deepseek-r1:14b for reasoning).  "
            "Result: Beat average human players 70% of the time in simulated games.  "
            "Domain: Gaming / Strategy.  Lessons learned: deepseek-r1's chain-of-thought "
            "was essential for strategic reasoning; 3-iteration cap prevented infinite loops."
        ),
        "metadata": {
            "case": "Catan Coach",
            "domain": "Gaming",
            "pattern": "reflection",
            "agents": 2,
            "stack": "TypeScript, Next.js, Ollama",
            "result": "70% win rate vs average humans",
        },
    },
    {
        "id": "case-neurospot",
        "document": (
            "NeuroSpot: IoT + AI system for parking spot detection using ESP32 cameras "
            "and edge inference.  Uses a pipeline pattern: Image Capture agent → Object "
            "Detection agent (YOLOv8-nano on edge) → Aggregator agent (consolidates "
            "multiple camera feeds) → API Publisher agent.  "
            "Stack: MicroPython (ESP32), Python FastAPI, MQTT, TimescaleDB.  "
            "Result: 95% detection accuracy, <2s end-to-end latency.  "
            "Domain: IoT / Smart City.  Lessons learned: edge inference critical for "
            "latency; MQTT provided reliable async communication between agents."
        ),
        "metadata": {
            "case": "NeuroSpot",
            "domain": "IoT / Smart City",
            "pattern": "pipeline",
            "agents": 4,
            "stack": "MicroPython, FastAPI, MQTT, TimescaleDB",
            "result": "95% accuracy, <2s latency",
        },
    },
    {
        "id": "case-strata",
        "document": (
            "Strata: Multi-agent content generation platform for marketing teams.  "
            "Uses an expert-network pattern: a Router agent classifies content type "
            "(blog, social, email, ad copy) and delegates to specialised Writer agents.  "
            "A Brand Voice agent applies tone-of-voice guidelines post-generation.  "
            "Stack: Python, FastAPI, Ollama (qwen3:32b via VRAIN), Supabase.  "
            "Result: 3x content output vs manual writing, 90% brand consistency score.  "
            "Domain: Marketing / Content.  Lessons learned: larger models (32B) "
            "significantly outperformed 7B for creative writing; brand voice as a "
            "separate agent was more flexible than system prompts."
        ),
        "metadata": {
            "case": "Strata",
            "domain": "Marketing",
            "pattern": "expert-network",
            "agents": 5,
            "stack": "Python, FastAPI, Ollama, Supabase",
            "result": "3x content output, 90% brand consistency",
        },
    },
    {
        "id": "case-tfg-dni",
        "document": (
            "TFG DNI Validator: Bachelor thesis project for automated Spanish DNI "
            "(national ID) document verification.  Uses a consensus pattern: three "
            "independent OCR+Validation agents process the document image, and a "
            "Judge agent compares results to determine authenticity.  "
            "Stack: Python, OpenCV, Tesseract OCR, FastAPI, SQLite.  "
            "Result: 98.5% validation accuracy, 0.3% false positive rate.  "
            "Domain: Document Processing / Identity.  Lessons learned: consensus "
            "of 3 agents reduced false positives by 5x compared to single agent; "
            "image preprocessing quality was the biggest factor in accuracy."
        ),
        "metadata": {
            "case": "TFG DNI Validator",
            "domain": "Document Processing",
            "pattern": "consensus",
            "agents": 4,
            "stack": "Python, OpenCV, Tesseract, FastAPI, SQLite",
            "result": "98.5% accuracy, 0.3% false positive rate",
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
