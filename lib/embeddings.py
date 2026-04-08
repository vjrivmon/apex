"""APEX Embeddings — Búsqueda semántica local con nomic-embed-text via Ollama.

Permite buscar en la wiki y el contexto por significado, no solo por keywords.
Usa el modelo nomic-embed-text que ya está instalado en el Slimbook.

Uso:
    emb = ApexEmbeddings(ollama_url="http://100.88.164.20:11434")
    vector = await emb.embed("motor de priorización de tareas")
    results = await emb.search(query="cómo priorizar", collection=wiki_texts)
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import httpx


class ApexEmbeddings:
    """Genera embeddings con nomic-embed-text via Ollama y busca por similaridad."""

    MODEL = "nomic-embed-text"

    def __init__(self, ollama_url: str = "http://localhost:11434") -> None:
        self.ollama_url = ollama_url.rstrip("/")
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def embed(self, text: str) -> list[float]:
        """Genera un vector de embedding para un texto."""
        client = await self._get_client()
        try:
            r = await client.post(
                f"{self.ollama_url}/api/embed",
                json={"model": self.MODEL, "input": text},
            )
            r.raise_for_status()
            data = r.json()
            # Ollama /api/embed devuelve {"embeddings": [[...vector...]]}
            embeddings = data.get("embeddings", [])
            if embeddings and len(embeddings) > 0:
                return embeddings[0]
            return []
        except Exception:
            return []

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Genera embeddings para múltiples textos."""
        results = []
        for text in texts:
            vec = await self.embed(text)
            results.append(vec)
        return results

    async def search(
        self,
        query: str,
        documents: list[dict],
        top_k: int = 5,
        text_key: str = "content",
    ) -> list[dict]:
        """Busca los documentos más similares al query por cosine similarity.

        Args:
            query: Texto a buscar
            documents: Lista de dicts con al menos un campo de texto
            top_k: Número de resultados a devolver
            text_key: Key del dict que contiene el texto

        Returns:
            Lista de dicts ordenados por similaridad, con 'score' añadido
        """
        if not documents:
            return []

        query_vec = await self.embed(query)
        if not query_vec:
            return documents[:top_k]  # Fallback sin embeddings

        # Embeddings de los documentos
        doc_texts = [d.get(text_key, "") for d in documents]
        doc_vecs = await self.embed_batch(doc_texts)

        # Calcular similaridad coseno
        scored = []
        for doc, vec in zip(documents, doc_vecs):
            if vec:
                score = _cosine_similarity(query_vec, vec)
                scored.append({**doc, "score": score})
            else:
                scored.append({**doc, "score": 0.0})

        # Ordenar por score descendente
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k]

    async def health_check(self) -> bool:
        """Verifica que Ollama responde y nomic-embed-text está disponible."""
        try:
            client = await self._get_client()
            r = await client.get(f"{self.ollama_url}/api/tags")
            r.raise_for_status()
            models = [m["name"] for m in r.json().get("models", [])]
            return any(self.MODEL in m for m in models)
        except Exception:
            return False

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Calcula la similaridad coseno entre dos vectores."""
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
