"""Infrastructure adapter: ChromaDB vector store for RAG."""

from __future__ import annotations

import logging
from typing import Any

import chromadb
from chromadb.config import Settings as ChromaSettings

from core.ports.vector_store import IVectorStore
from shared.config import settings

logger = logging.getLogger(__name__)


class ChromaAdapter(IVectorStore):
    """Connects to a ChromaDB v2 HTTP server.

    The adapter lazily creates / retrieves collections on first access.
    Two main collections are expected:

    * ``sma_patterns``  -- Multi-agent architecture patterns (Pipeline, etc.)
    * ``real_cases``    -- Real-world case studies (FeedbackIA, Catan Coach, ...)

    Embedding is handled by ChromaDB's default embedding function (all-MiniLM-L6-v2)
    unless overridden at server level.
    """

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
    ) -> None:
        self._host = host or settings.chroma_host
        self._port = port or settings.chroma_port
        self._client: chromadb.HttpClient | None = None

    # -- Lazy init ------------------------------------------------------------

    def _get_client(self) -> chromadb.HttpClient:
        """Return (and cache) an ``HttpClient`` connected to ChromaDB."""
        if self._client is None:
            logger.info(
                "Connecting to ChromaDB at %s:%s", self._host, self._port,
            )
            self._client = chromadb.HttpClient(
                host=self._host,
                port=self._port,
                settings=ChromaSettings(
                    anonymized_telemetry=False,
                ),
            )
        return self._client

    def _get_collection(self, name: str) -> chromadb.Collection:
        """Get or create a collection by name."""
        client = self._get_client()
        return client.get_or_create_collection(name=name)

    # -- IVectorStore ---------------------------------------------------------

    async def query(
        self,
        collection: str,
        query_text: str,
        n_results: int = 3,
    ) -> list[dict]:
        """Query ``collection`` for documents similar to ``query_text``.

        Returns a list of dicts with keys: ``document``, ``metadata``, ``distance``.
        """
        try:
            col = self._get_collection(collection)
            results = col.query(
                query_texts=[query_text],
                n_results=n_results,
            )
            return self._format_results(results)
        except Exception:
            logger.exception(
                "ChromaDB query failed for collection=%s", collection,
            )
            return []

    async def add_documents(
        self,
        collection: str,
        documents: list[str],
        metadatas: list[dict],
        ids: list[str],
    ) -> None:
        """Upsert documents into ``collection``."""
        try:
            col = self._get_collection(collection)
            col.upsert(
                documents=documents,
                metadatas=metadatas,
                ids=ids,
            )
            logger.info(
                "Upserted %d documents into collection '%s'",
                len(documents),
                collection,
            )
        except Exception:
            logger.exception(
                "ChromaDB add_documents failed for collection=%s", collection,
            )
            raise

    async def get_collection_count(self, collection: str) -> int:
        """Return the number of documents stored in ``collection``."""
        try:
            col = self._get_collection(collection)
            return col.count()
        except Exception:
            logger.exception(
                "ChromaDB get_collection_count failed for collection=%s",
                collection,
            )
            return 0

    async def delete_documents(
        self,
        collection: str,
        ids: list[str],
    ) -> None:
        """Delete documents by ID from ``collection``."""
        try:
            col = self._get_collection(collection)
            col.delete(ids=ids)
            logger.info(
                "Deleted %d documents from collection '%s'",
                len(ids),
                collection,
            )
        except Exception:
            logger.exception(
                "ChromaDB delete_documents failed for collection=%s",
                collection,
            )
            raise

    # -- Helpers --------------------------------------------------------------

    @staticmethod
    def _format_results(raw: dict[str, Any]) -> list[dict]:
        """Transform ChromaDB query output into a flat list of dicts."""
        documents = (raw.get("documents") or [[]])[0]
        metadatas = (raw.get("metadatas") or [[]])[0]
        distances = (raw.get("distances") or [[]])[0]

        results: list[dict] = []
        for doc, meta, dist in zip(documents, metadatas, distances):
            results.append({
                "document": doc,
                "metadata": meta or {},
                "distance": dist,
            })
        return results
