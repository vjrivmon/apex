"""Tests del cliente de embeddings.

El punto crítico es el batch: el cliente anterior hacía una petición HTTP por
texto. Estos tests cuentan las peticiones reales para que una regresión a
N round-trips falle en vez de pasar desapercibida como "solo más lento".
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

import embeddings  # noqa: E402
from embeddings import (  # noqa: E402
    EMBED_DIM,
    EMBED_MODEL,
    EmbeddingsUnavailable,
    embed_batch,
    embed_query,
    health_check,
    ollama_url,
)

_OLLAMA_OK, _OLLAMA_WHY = health_check()
requires_ollama = pytest.mark.skipif(
    not _OLLAMA_OK, reason=f"Ollama no disponible: {_OLLAMA_WHY}"
)


@pytest.fixture
def espia(monkeypatch):
    """Sustituye el POST a Ollama y registra cada petición."""
    peticiones = []

    def fake_post(payload):
        peticiones.append(payload)
        n = len(payload["input"])
        return {"embeddings": [[0.1] * EMBED_DIM for _ in range(n)]}

    monkeypatch.setattr(embeddings, "_post", fake_post)
    return peticiones


# ── Batch ──

def test_batch_hace_una_sola_peticion(espia):
    """Tres textos, una petición. La regresión a N round-trips falla aquí."""
    vecs = embed_batch(["uno", "dos", "tres"])
    assert len(vecs) == 3
    assert len(espia) == 1, f"esperaba 1 petición, hubo {len(espia)}"
    assert len(espia[0]["input"]) == 3


def test_batch_trocea_lotes_grandes(espia):
    embed_batch([f"texto {i}" for i in range(70)])
    assert len(espia) == 3  # 32 + 32 + 6
    assert [len(p["input"]) for p in espia] == [32, 32, 6]


def test_batch_vacio_no_llama(espia):
    assert embed_batch([]) == []
    assert espia == []


def test_usa_el_modelo_correcto(espia):
    embed_batch(["hola"])
    assert espia[0]["model"] == EMBED_MODEL


# ── Prefijos de tarea ──

def test_documentos_llevan_prefijo_de_documento(espia):
    embed_batch(["un pasaje del libro"], is_query=False)
    assert espia[0]["input"] == ["search_document: un pasaje del libro"]


def test_consultas_llevan_prefijo_de_consulta(espia):
    embed_query("una pregunta")
    assert espia[0]["input"] == ["search_query: una pregunta"]


# ── Errores ──

def test_respuesta_incompleta_falla_ruidosamente(monkeypatch):
    """Menos vectores que textos desalinearía el índice en silencio."""
    def incompleto(payload):
        return {"embeddings": [[0.1] * EMBED_DIM]}  # 1 para 3 textos

    monkeypatch.setattr(embeddings, "_post", incompleto)
    with pytest.raises(EmbeddingsUnavailable, match="1 vectores para 3"):
        embed_batch(["a", "b", "c"])


def test_respuesta_vacia_en_query_falla(monkeypatch):
    monkeypatch.setattr(embeddings, "_post", lambda p: {"embeddings": []})
    with pytest.raises(EmbeddingsUnavailable):
        embed_query("algo")


def test_ollama_caido_lanza_excepcion_tipada(monkeypatch):
    import urllib.error

    def caido(req, timeout=None):
        raise urllib.error.URLError("conexión rechazada")

    monkeypatch.setattr(embeddings.urllib.request, "urlopen", caido)
    with pytest.raises(EmbeddingsUnavailable, match="no responde"):
        embed_query("algo")


def test_health_check_no_lanza_con_ollama_caido(monkeypatch):
    import urllib.error

    def caido(req, timeout=None):
        raise urllib.error.URLError("sin ruta al host")

    monkeypatch.setattr(embeddings.urllib.request, "urlopen", caido)
    ok, motivo = health_check()
    assert ok is False
    assert "no responde" in motivo


# ── Configuración ──

def test_url_por_defecto_es_local(monkeypatch):
    monkeypatch.delenv("APEX_OLLAMA_URL", raising=False)
    assert ollama_url() == "http://localhost:11434"


def test_url_se_puede_sobreescribir(monkeypatch):
    monkeypatch.setenv("APEX_OLLAMA_URL", "http://otro-host:11434/")
    assert ollama_url() == "http://otro-host:11434"


def test_sin_ip_privada_hardcodeada():
    """El fichero se excluía del repo público por llevar una IP de Tailscale."""
    fuente = (Path(__file__).resolve().parents[1] / "lib" / "embeddings.py")
    texto = fuente.read_text(encoding="utf-8")
    assert "100.88.164.20" not in texto


# ── Con Ollama real ──

@requires_ollama
def test_ollama_real_devuelve_768_dimensiones():
    vec = embed_query("context window budget management")
    assert len(vec) == EMBED_DIM
    assert any(v != 0.0 for v in vec)


@requires_ollama
def test_ollama_real_batch_devuelve_uno_por_texto():
    vecs = embed_batch(["primer pasaje", "segundo pasaje", "tercero"])
    assert len(vecs) == 3
    assert all(len(v) == EMBED_DIM for v in vecs)


@requires_ollama
def test_ollama_real_textos_similares_puntuan_mas_alto():
    """Sanidad semántica: el modelo distingue significado, no solo caracteres."""
    from book_corpus import _cosine

    a = embed_query("how do agents use tools")
    cerca = embed_batch(["Agents invoke external tools to act."])[0]
    lejos = embed_batch(["Sourdough bread needs high hydration."])[0]

    assert _cosine(a, cerca) > _cosine(a, lejos)
