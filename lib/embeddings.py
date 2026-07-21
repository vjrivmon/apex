"""APEX Embeddings — cliente único de nomic-embed-text vía Ollama.

Es el ÚNICO cliente de embeddings de APEX. Cualquier módulo que necesite
vectores (biblioteca de libros, memoria de errores, futuros consumidores)
pasa por aquí en vez de hablar con Ollama por su cuenta.

nomic-embed-text espera prefijos de tarea distintos para documentos y para
consultas; usarlos mal degrada la similitud. `embed_batch` los pone por ti.

Nota medida sobre el idioma (2026-07-21, corpus real de 228 fragmentos): el
modelo es mayoritariamente inglés. Una pregunta en español contra un corpus
inglés acierta 2 de 6; la misma pregunta traducida, 6 de 6. Quien llame debe
enviar la consulta en el idioma del corpus.

Uso:
    vec = embed_query("context window budget management")
    vecs = embed_batch([chunk1, chunk2], is_query=False)
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

EMBED_MODEL = "nomic-embed-text"
EMBED_DIM = 768

# Prefijos de tarea que nomic espera. Sin ellos el modelo no distingue una
# pregunta de un pasaje y la similitud se resiente.
_DOC_PREFIX = "search_document: "
_QUERY_PREFIX = "search_query: "

# Lote por petición. 32 mantiene el cuerpo HTTP manejable y aprovecha el
# batch de Ollama: 228 fragmentos se embeben en ~2.3s.
_BATCH_SIZE = 32
_TIMEOUT = 180


class EmbeddingsUnavailable(RuntimeError):
    """Ollama no responde o el modelo no está. Se propaga: no se traga."""


def ollama_url() -> str:
    """URL de Ollama. `APEX_OLLAMA_URL` la sobreescribe."""
    return os.environ.get("APEX_OLLAMA_URL", "http://localhost:11434").rstrip("/")


def _post(payload: dict) -> dict:
    req = urllib.request.Request(
        f"{ollama_url()}/api/embed",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            return json.loads(r.read())
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        raise EmbeddingsUnavailable(
            f"Ollama no responde en {ollama_url()}: {exc}"
        ) from exc


def embed_batch(texts: list[str], *, is_query: bool = False) -> list[list[float]]:
    """Embebe una lista de textos en lotes.

    Una petición HTTP por lote, no una por texto: el cliente anterior hacía N
    round-trips secuenciales (14 ms/doc contra 3,5 ms/doc en batch).
    """
    if not texts:
        return []

    prefix = _QUERY_PREFIX if is_query else _DOC_PREFIX
    out: list[list[float]] = []
    for i in range(0, len(texts), _BATCH_SIZE):
        lote = [prefix + t for t in texts[i:i + _BATCH_SIZE]]
        data = _post({"model": EMBED_MODEL, "input": lote})
        vectores = data.get("embeddings") or []
        if len(vectores) != len(lote):
            raise EmbeddingsUnavailable(
                f"Ollama devolvió {len(vectores)} vectores para {len(lote)} textos"
            )
        out.extend(vectores)
    return out


def embed_query(text: str) -> list[float]:
    """Embebe una consulta. Debe ir en el idioma del corpus."""
    vecs = embed_batch([text], is_query=True)
    if not vecs:
        raise EmbeddingsUnavailable("Ollama devolvió una respuesta vacía")
    return vecs[0]


def health_check() -> tuple[bool, str]:
    """`(disponible, motivo)`. No lanza: es para diagnóstico."""
    try:
        req = urllib.request.Request(f"{ollama_url()}/api/tags")
        with urllib.request.urlopen(req, timeout=10) as r:
            modelos = [m.get("name", "") for m in json.loads(r.read()).get("models", [])]
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        return False, f"Ollama no responde en {ollama_url()}: {exc}"

    if not any(EMBED_MODEL in m for m in modelos):
        return False, f"falta el modelo {EMBED_MODEL} (ollama pull {EMBED_MODEL})"
    return True, ""
