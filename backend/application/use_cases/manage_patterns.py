"""Use case: Manage SMA patterns in the knowledge base."""

from __future__ import annotations

import logging

from core.ports import IVectorStore

logger = logging.getLogger(__name__)


class ManagePatternsUseCase:
    """CRUD operations for SMA patterns in the RAG knowledge base."""

    def __init__(self, vector_store: IVectorStore):
        self._vector_store = vector_store

    async def list_patterns(self) -> list[dict]:
        """List all patterns in the knowledge base."""
        # Query with broad term to get all
        results = await self._vector_store.query("sma_patterns", "multi-agent system pattern", n_results=20)
        return results

    async def search_patterns(self, query: str) -> list[dict]:
        """Search patterns by relevance to a query."""
        return await self._vector_store.query("sma_patterns", query, n_results=5)

    async def add_pattern(
        self,
        pattern_id: str,
        name: str,
        description: str,
        when_to_use: str,
        paper_ref: str = "",
    ) -> None:
        """Add a new pattern to the knowledge base."""
        document = f"Pattern: {name}\n\n{description}\n\nWhen to use: {when_to_use}\n\nReference: {paper_ref}"
        metadata = {
            "name": name,
            "type": "pattern",
            "paper_ref": paper_ref,
        }
        await self._vector_store.add_documents(
            collection="sma_patterns",
            documents=[document],
            metadatas=[metadata],
            ids=[pattern_id],
        )
        logger.info("Pattern added: %s", name)

    async def get_pattern_count(self) -> int:
        """Get total number of patterns."""
        return await self._vector_store.get_collection_count("sma_patterns")

    async def get_case_count(self) -> int:
        """Get total number of real cases."""
        return await self._vector_store.get_collection_count("real_cases")
