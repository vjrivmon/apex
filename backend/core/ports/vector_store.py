"""Port: Vector Store interface for RAG."""

from __future__ import annotations

from abc import ABC, abstractmethod


class IVectorStore(ABC):
    """Abstract interface for vector database operations."""

    @abstractmethod
    async def query(
        self,
        collection: str,
        query_text: str,
        n_results: int = 3,
    ) -> list[dict]:
        """Query the vector store for similar documents."""

    @abstractmethod
    async def add_documents(
        self,
        collection: str,
        documents: list[str],
        metadatas: list[dict],
        ids: list[str],
    ) -> None:
        """Add documents to a collection."""

    @abstractmethod
    async def get_collection_count(self, collection: str) -> int:
        """Get the number of documents in a collection."""

    @abstractmethod
    async def delete_documents(
        self,
        collection: str,
        ids: list[str],
    ) -> None:
        """Delete documents from a collection."""
