"""RAGAgent -- retrieves and reranks architecture patterns and real cases.

Queries two vector-store collections:
- ``sma_patterns``: The 7 canonical SMA architecture patterns.
- ``real_cases``: Vicente's real projects and known industry examples.

Results are reranked by relevance before being returned to the caller.
"""

from __future__ import annotations

import logging
from typing import Any

from core.ports import ILLMProvider, IVectorStore

logger = logging.getLogger(__name__)

_COLLECTION_PATTERNS = "sma_patterns"
_COLLECTION_CASES = "real_cases"

_RERANK_SYSTEM_PROMPT = (
    "You are a relevance judge.  Given a user query and a list of documents, "
    "score each document from 0.0 (irrelevant) to 1.0 (perfectly relevant).  "
    "Respond ONLY with a JSON array of numbers in the same order as the documents."
)


class RAGAgent:
    """Retrieves and reranks multi-agent architecture patterns and real cases."""

    def __init__(
        self,
        llm: ILLMProvider,
        vector_store: IVectorStore | None = None,
    ) -> None:
        self._llm = llm
        self._vector_store = vector_store

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def retrieve(
        self,
        query: str,
        n_patterns: int = 3,
        n_cases: int = 2,
        vector_store: IVectorStore | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        """Retrieve relevant patterns and real cases for *query*.

        Parameters
        ----------
        query:
            Natural-language description of the user's problem.
        n_patterns:
            Number of pattern documents to return.
        n_cases:
            Number of real-case documents to return.
        vector_store:
            Optional override for the vector store.

        Returns
        -------
        Dict with ``patterns`` (list[dict]) and ``cases`` (list[dict]).
        Each dict has at least ``id``, ``text``, and ``score`` keys.
        """
        active_vs = vector_store or self._vector_store

        if active_vs is None:
            logger.warning("No vector store available; returning empty RAG context.")
            return {"patterns": [], "cases": []}

        patterns = await self._query_and_rerank(
            vs=active_vs,
            collection=_COLLECTION_PATTERNS,
            query=query,
            n_results=n_patterns,
        )

        cases = await self._query_and_rerank(
            vs=active_vs,
            collection=_COLLECTION_CASES,
            query=query,
            n_results=n_cases,
        )

        logger.info(
            "RAG retrieved %d patterns and %d cases for query (%.60s...)",
            len(patterns),
            len(cases),
            query,
        )

        return {"patterns": patterns, "cases": cases}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _query_and_rerank(
        self,
        vs: IVectorStore,
        collection: str,
        query: str,
        n_results: int,
    ) -> list[dict[str, Any]]:
        """Query the vector store and rerank results with the LLM.

        We over-fetch (2x) from the vector store, then use the LLM as a
        cross-encoder reranker to return only the top *n_results*.
        """
        fetch_count = min(n_results * 2, 10)

        try:
            raw_results = await vs.query(
                collection=collection,
                query_text=query,
                n_results=fetch_count,
            )
        except Exception:
            logger.exception("Vector store query failed for collection '%s'", collection)
            return []

        if not raw_results:
            return []

        # Normalise results: ensure each has id, text, metadata.
        documents = self._normalise_results(raw_results)

        # Skip reranking if we already have n_results or fewer.
        if len(documents) <= n_results:
            return documents

        # Rerank with the LLM.
        reranked = await self._rerank(query=query, documents=documents)
        return reranked[:n_results]

    async def _rerank(
        self,
        query: str,
        documents: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Use the LLM as a cross-encoder to rerank *documents* by relevance.

        Falls back to the original order if the LLM response is unparseable.
        """
        doc_texts = "\n".join(
            f"[{i}] {doc.get('text', '')[:300]}" for i, doc in enumerate(documents)
        )

        prompt = (
            f"Query: {query}\n\n"
            f"Documents:\n{doc_texts}\n\n"
            f"Score each document (0.0-1.0) for relevance to the query.  "
            f"Respond with a JSON array of {len(documents)} floats."
        )

        try:
            raw = await self._llm.generate(
                prompt=prompt,
                model="default",
                system_prompt=_RERANK_SYSTEM_PROMPT,
                temperature=0.1,
            )

            scores = self._parse_scores(raw, expected_count=len(documents))

            # Attach scores and sort descending.
            for doc, score in zip(documents, scores, strict=False):
                doc["score"] = score

            documents.sort(key=lambda d: d.get("score", 0.0), reverse=True)

        except Exception:
            logger.warning("Reranking failed; returning documents in original order.")
            for doc in documents:
                doc.setdefault("score", 0.5)

        return documents

    @staticmethod
    def _normalise_results(raw_results: list[dict]) -> list[dict[str, Any]]:
        """Ensure each result dict has ``id``, ``text``, and ``metadata`` keys."""
        normalised: list[dict[str, Any]] = []
        for i, item in enumerate(raw_results):
            normalised.append({
                "id": item.get("id", f"doc_{i}"),
                "text": item.get("text", item.get("content", item.get("document", ""))),
                "metadata": item.get("metadata", {}),
                "name": item.get("name", item.get("metadata", {}).get("name", "")),
                "description": item.get("text", item.get("content", "")),
                "score": item.get("score", item.get("distance", 0.5)),
            })
        return normalised

    @staticmethod
    def _parse_scores(raw: str, expected_count: int) -> list[float]:
        """Parse a JSON array of floats from the LLM response."""
        import json

        cleaned = raw.strip()
        if cleaned.startswith("```"):
            first_newline = cleaned.index("\n")
            cleaned = cleaned[first_newline + 1 :]
            if "```" in cleaned:
                cleaned = cleaned[: cleaned.rindex("```")]
            cleaned = cleaned.strip()

        scores = json.loads(cleaned)
        if not isinstance(scores, list):
            raise ValueError("Expected a JSON array of scores")

        # Pad or truncate to expected length.
        parsed = [float(s) for s in scores[:expected_count]]
        while len(parsed) < expected_count:
            parsed.append(0.5)

        return parsed
