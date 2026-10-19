"""Curador local opcional (Sprint 18) — destila contexto con un modelo de Ollama.

Sustituye, SOLO cuando está activo, las heurísticas ciegas de mantenimiento de
contexto (corte por caracteres, plantillas fijas, ranking por BM25) por un modelo
local. Es opt-in puro: sin `APEX_CURATOR_MODEL` no se hace NI UNA llamada de red
y el repo se comporta exactamente igual que antes.

Reglas duras (blueprint S18, secciones 2 y 4):

- Default OFF. `APEX_CURATOR_MODEL` vacía o ausente → `NoCurator`.
- La env se lee EN CADA llamada (`get_curator()`), así que encender o apagar el
  curador en caliente no obliga a reiniciar el servidor MCP.
- Cualquier excepción —timeout, HTTP 500, respuesta malformada, sin red—
  devuelve `None`: el llamador sigue con su heurística. El fallo NUNCA propaga.
- Timeout estricto vía httpx (3 s por defecto, `APEX_CURATOR_TIMEOUT_S`).

El curador DESTILA, no decide: su salida es un resumen. El original siempre
sigue archivado en `tool_output_archive`, así que un resumen pobre no pierde
información.
"""
from __future__ import annotations

import os
import sqlite3
import sys
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Sequence

import httpx

# La resolucion de la raiz del proyecto es de lib/project_root.py (unica).
from project_root import project_db_path as _project_db_path

# ── Configuración ─────────────────────────────────────────────────────────

ENV_MODEL = "APEX_CURATOR_MODEL"
ENV_HOST = "APEX_CURATOR_OLLAMA_HOST"
ENV_TIMEOUT = "APEX_CURATOR_TIMEOUT_S"

DEFAULT_OLLAMA_HOST = "http://localhost:11434"
DEFAULT_TIMEOUT_S = 3.0

KIND_SUMMARIZE = "summarize"
KIND_EMBED = "embed"
KIND_RERANK = "rerank"

# Telemetría: una fila por llamada al modelo, también cuando cae.
# El DDL vive en lib/context_db.py (fuente única del schema).
_aviso_tabla = False


# ── Interfaz ──────────────────────────────────────────────────────────────

class CuratorBackend(ABC):
    """Interfaz del curador.

    `None` significa "no hay salida del curador": el llamador debe seguir con
    su heurística. Nunca se lanza una excepción desde aquí.
    """

    enabled: bool = False
    model: str = ""

    @abstractmethod
    def summarize(self, text: str, max_tokens: int = 512) -> str | None:
        """Resumen semántico del texto, o None si no se pudo."""

    @abstractmethod
    def embed(self, text: str) -> list[float] | None:
        """Vector del texto, o None si no se pudo."""

    @abstractmethod
    def rerank(self, query: str, docs: Sequence[str]) -> list[int] | None:
        """Índices de `docs` ordenados por relevancia, o None si no se pudo.

        El re-rank usa embeddings: exige un modelo con capacidad de
        embedding. Con un modelo de solo completions (Granite 4.1, por
        ejemplo) la llamada falla y el llamador se queda con el orden BM25.
        """


class NoCurator(CuratorBackend):
    """Curador apagado: no hace nada y devuelve siempre la heurística."""

    enabled = False
    model = ""

    def summarize(self, text: str, max_tokens: int = 512) -> str | None:
        return None

    def embed(self, text: str) -> list[float] | None:
        return None

    def rerank(self, query: str, docs: Sequence[str]) -> list[int] | None:
        return None


# ── Cliente Ollama ────────────────────────────────────────────────────────

class OllamaCurator(CuratorBackend):
    """Curador contra la API HTTP de Ollama.

    El cliente HTTP se abre por petición: el objeto no guarda estado, así que
    `get_curator()` puede crear uno nuevo en cada llamada sin cachear nada y
    el cambio de modelo en caliente es trivialmente correcto.
    """

    enabled = True

    def __init__(self, model: str, host: str = DEFAULT_OLLAMA_HOST,
                 timeout: float = DEFAULT_TIMEOUT_S, transport=None,
                 db_path: str | Path | None = None) -> None:
        self.model = model
        self.host = (host or DEFAULT_OLLAMA_HOST).rstrip("/")
        self.timeout = timeout
        self._transport = transport
        self._db_path = Path(db_path) if db_path else None

    # -- HTTP interno ──────────────────────────────────────────────────

    def _post(self, path: str, payload: dict) -> dict:
        with httpx.Client(timeout=self.timeout, transport=self._transport) as client:
            resp = client.post(f"{self.host}{path}", json=payload)
            resp.raise_for_status()
            return resp.json()

    def _call(self, kind: str, fn):
        """Ejecuta la llamada, mide y registra. NUNCA propaga excepciones."""
        inicio = time.monotonic()
        try:
            valor, in_tokens, out_tokens = fn()
            fallo = valor is None
        except Exception:
            valor, in_tokens, out_tokens, fallo = None, 0, 0, True
        latencia = int((time.monotonic() - inicio) * 1000)
        record_call(
            self._db_path, kind=kind, model=self.model, latency_ms=latencia,
            fallback_used=fallo, input_tokens=in_tokens, output_tokens=out_tokens,
        )
        return valor

    # -- Interfaz ───────────────────────────────────────────────────────

    def summarize(self, text: str, max_tokens: int = 512) -> str | None:
        if not text or not text.strip():
            return None

        def _fn():
            data = self._post("/api/generate", {
                "model": self.model,
                "prompt": _prompt_resumen(text, max_tokens),
                "stream": False,
                "options": {"num_predict": max_tokens, "temperature": 0},
            })
            respuesta = data.get("response")
            if not isinstance(respuesta, str) or not respuesta.strip():
                return None, 0, 0
            return (respuesta.strip(),
                    _entero(data.get("prompt_eval_count")),
                    _entero(data.get("eval_count")))

        return self._call(KIND_SUMMARIZE, _fn)

    def embed(self, text: str) -> list[float] | None:
        if not text or not text.strip():
            return None

        def _fn():
            data = self._post("/api/embed", {"model": self.model, "input": text})
            vectores = data.get("embeddings")
            if not isinstance(vectores, list) or not vectores:
                return None, 0, 0
            primero = vectores[0]
            if not isinstance(primero, list) or not primero:
                return None, 0, 0
            return ([float(x) for x in primero],
                    _entero(data.get("prompt_eval_count")), 0)

        return self._call(KIND_EMBED, _fn)

    def rerank(self, query: str, docs: Sequence[str]) -> list[int] | None:
        docs = list(docs or [])
        if not query or not query.strip() or not docs:
            return None

        def _fn():
            entradas = [query] + docs
            data = self._post("/api/embed", {"model": self.model, "input": entradas})
            vectores = data.get("embeddings")
            if not isinstance(vectores, list) or len(vectores) != len(entradas):
                return None, 0, 0
            consulta = [float(x) for x in vectores[0]]
            if not isinstance(vectores[1], list):
                return None, 0, 0
            similitudes = []
            for vec in vectores[1:]:
                similitudes.append(_coseno(consulta, [float(x) for x in vec]))
            orden = sorted(range(len(docs)), key=lambda i: similitudes[i],
                           reverse=True)
            return orden, _entero(data.get("prompt_eval_count")), 0

        return self._call(KIND_RERANK, _fn)


# ── Helpers ───────────────────────────────────────────────────────────────

def _prompt_resumen(texto: str, max_tokens: int) -> str:
    return (
        "Resume el contenido siguiente de forma concisa y factual, en español. "
        "No inventes nada: conserva nombres propios, cifras, rutas y decisiones. "
        f"Devuelve como máximo {max_tokens} tokens y nada más.\n\n"
        f"CONTENIDO:\n{texto}"
    )


def _entero(valor) -> int:
    try:
        return int(valor or 0)
    except (TypeError, ValueError):
        return 0


def _coseno(a: list[float], b: list[float]) -> float:
    num = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if not na or not nb:
        return 0.0
    return num / (na * nb)


# ── Configuración leída del entorno ───────────────────────────────────────

def timeout_env() -> float:
    """Timeout en segundos. Valor inválido → default (nunca 0: sin timeout)."""
    crudo = (os.environ.get(ENV_TIMEOUT) or "").strip()
    if not crudo:
        return DEFAULT_TIMEOUT_S
    try:
        valor = float(crudo)
    except ValueError:
        return DEFAULT_TIMEOUT_S
    return valor if valor > 0 else DEFAULT_TIMEOUT_S


def curator_config() -> dict:
    """Configuración vigente. Se lee en cada llamada (cambio en caliente)."""
    modelo = (os.environ.get(ENV_MODEL) or "").strip()
    host = (os.environ.get(ENV_HOST) or DEFAULT_OLLAMA_HOST).strip().rstrip("/")
    return {"model": modelo, "host": host, "timeout": timeout_env()}


def get_curator(db_path: str | Path | None = None) -> CuratorBackend:
    """Factory: devuelve el curador según el entorno ACTUAL.

    Sin `APEX_CURATOR_MODEL` → `NoCurator` (ni una llamada de red). Con ella →
    `OllamaCurator`. Si el modelo no responde, el fallback ocurre DENTRO de
    la llamada, no al construir el curador: un Ollama caído no rompe nada.
    """
    cfg = curator_config()
    if not cfg["model"]:
        return NoCurator()
    return OllamaCurator(model=cfg["model"], host=cfg["host"],
                         timeout=cfg["timeout"], db_path=db_path)


# ── Telemetría ────────────────────────────────────────────────────────────

def project_db_path() -> Path | None:
    """`.apex/context.db` del proyecto actual, subiendo desde el cwd.

    Delega en `lib/project_root.py`, que es la implementación ÚNICA de esta
    búsqueda. `~/.apex/` es memoria global de errores graves, no el contexto
    del proyecto: no se busca.
    """
    return _project_db_path()


def record_call(db_path: str | Path | None, kind: str, model: str,
                latency_ms: int, fallback_used: bool,
                input_tokens: int = 0, output_tokens: int = 0) -> None:
    """Escribe una fila en `curator_calls`. Nunca propaga errores.

    La tabla la crea `lib/context_db.py` (fuente única del schema). Si la BD
    del proyecto es anterior a esta migración, se avisa por stderr una vez y
    se sigue: la telemetría no puede romper al llamador.
    """
    global _aviso_tabla
    ruta = Path(db_path) if db_path else project_db_path()
    if ruta is None:
        return
    try:
        conn = sqlite3.connect(str(ruta), timeout=2)
        try:
            conn.execute(
                "INSERT INTO curator_calls "
                "(kind, model, latency_ms, fallback_used, input_tokens, output_tokens) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (kind, model, int(latency_ms), 1 if fallback_used else 0,
                 int(input_tokens), int(output_tokens)),
            )
            conn.commit()
        finally:
            conn.close()
    except sqlite3.OperationalError as exc:
        if not _aviso_tabla:
            _aviso_tabla = True
            print(f"[apex] telemetría del curador no escrita ({exc}); "
                  "la tabla curator_calls se creará al reinicializar la BD "
                  "del proyecto.", file=sys.stderr)
    except Exception:
        pass


def status(db_path: str | Path | None = None) -> dict:
    """Estado del curador para `apex_curator_status`."""
    cfg = curator_config()
    ruta = Path(db_path) if db_path else project_db_path()
    ultimo_24h = {"calls": 0, "avg_latency": 0.0, "fallback_rate": 0.0}
    if ruta is not None and ruta.exists():
        try:
            conn = sqlite3.connect(str(ruta), timeout=2)
            try:
                fila = conn.execute(
                    "SELECT COUNT(*), COALESCE(AVG(latency_ms), 0), "
                    "COALESCE(SUM(fallback_used), 0) FROM curator_calls "
                    "WHERE ts >= datetime('now', '-1 day')"
                ).fetchone()
            finally:
                conn.close()
            llamadas = int(fila[0] or 0)
            ultimo_24h = {
                "calls": llamadas,
                "avg_latency": round(float(fila[1] or 0), 1),
                "fallback_rate": (round(int(fila[2] or 0) / llamadas, 3)
                                  if llamadas else 0.0),
            }
        except sqlite3.Error:
            pass
    return {
        "enabled": bool(cfg["model"]),
        "model": cfg["model"],
        "ollama_host": cfg["host"],
        "last_24h": ultimo_24h,
    }
