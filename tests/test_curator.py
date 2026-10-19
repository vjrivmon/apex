"""Tests del curador local (Sprint 18).

Reglas que esta suite tiene que defender:

1. Con `APEX_CURATOR_MODEL` sin definir, el curador no hace NI UNA llamada de
   red: el camino por defecto de handoff, token_filter y búsqueda es idéntico
   al de siempre.
2. Cualquier fallo del modelo (timeout, HTTP 500, respuesta malformada, sin
   red) cae a la heurística sin propagar la excepción.
3. La telemetría (`curator_calls`) se escribe y marca el fallback.

Ningún test necesita red: todo el HTTP va por `httpx.MockTransport`. El único
test que habla con un Ollama real está marcado con skip y solo corre si se
define `APEX_TEST_OLLAMA=1`.
"""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
from pathlib import Path

import httpx
import pytest

import curator as _curator

# Cliente real, capturado ANTES de parchearlo en los tests.
_CLIENT_REAL = httpx.Client


# ── Utilidades ────────────────────────────────────────────────────────────

def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _parchear_transporte(monkeypatch, handler) -> None:
    """Inyecta un MockTransport en el cliente HTTP que abre lib/curator.py."""
    transport = httpx.MockTransport(handler)

    def _factory(*args, **kwargs):
        kwargs["transport"] = transport
        return _CLIENT_REAL(*args, **kwargs)

    monkeypatch.setattr(_curator.httpx, "Client", _factory)


def _handler_generate(respuesta: str = "Resumen del curador."):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "response": respuesta,
            "prompt_eval_count": 42,
            "eval_count": 7,
        })
    return handler


def _handler_embed(vectores: dict[str, list[float]]):
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        entradas = payload["input"]
        if isinstance(entradas, str):
            entradas = [entradas]
        return httpx.Response(200, json={
            "embeddings": [vectores.get(t, [0.0, 0.0]) for t in entradas],
            "prompt_eval_count": 11,
        })
    return handler


def _handler_excepcion(exc: Exception):
    def handler(request: httpx.Request) -> httpx.Response:
        raise exc
    return handler


def _db_con_schema(tmp_path: Path):
    """BD real con el schema de APEX (incluye curator_calls)."""
    from context_db import ApexContextDB

    apex = tmp_path / ".apex"
    apex.mkdir(exist_ok=True)
    db = ApexContextDB(str(apex / "context.db"))
    _run(db.initialize())
    return db


def _filas_curator(db_path: Path) -> list[tuple]:
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute(
            "SELECT kind, model, latency_ms, fallback_used, input_tokens, "
            "output_tokens FROM curator_calls ORDER BY id"
        ).fetchall()
    finally:
        conn.close()


# ── Opt-in / opt-out ──────────────────────────────────────────────────────

def test_sin_env_no_hay_curador(monkeypatch):
    monkeypatch.delenv(_curator.ENV_MODEL, raising=False)
    c = _curator.get_curator()
    assert isinstance(c, _curator.NoCurator)
    assert c.enabled is False
    assert c.summarize("hola") is None
    assert c.embed("hola") is None
    assert c.rerank("q", ["a"]) is None


def test_env_vacia_es_equivalente_a_ausente(monkeypatch):
    monkeypatch.setenv(_curator.ENV_MODEL, "   ")
    assert isinstance(_curator.get_curator(), _curator.NoCurator)


def test_opt_in_devuelve_ollama(monkeypatch):
    monkeypatch.setenv(_curator.ENV_MODEL, "granite4:tiny")
    monkeypatch.setenv(_curator.ENV_HOST, "http://ollama.local:1234/")
    monkeypatch.setenv(_curator.ENV_TIMEOUT, "7")
    c = _curator.get_curator()
    assert isinstance(c, _curator.OllamaCurator)
    assert c.enabled is True
    assert c.model == "granite4:tiny"
    assert c.host == "http://ollama.local:1234"
    assert c.timeout == 7.0


def test_timeout_invalido_cae_al_default(monkeypatch):
    monkeypatch.setenv(_curator.ENV_TIMEOUT, "no-es-un-numero")
    assert _curator.timeout_env() == _curator.DEFAULT_TIMEOUT_S
    monkeypatch.setenv(_curator.ENV_TIMEOUT, "-1")
    assert _curator.timeout_env() == _curator.DEFAULT_TIMEOUT_S


def test_cambio_en_caliente_entre_llamadas(monkeypatch):
    """Encender, apagar y cambiar de modelo se nota sin reiniciar nada."""
    monkeypatch.setenv(_curator.ENV_MODEL, "modelo-a")
    assert _curator.get_curator().model == "modelo-a"

    monkeypatch.delenv(_curator.ENV_MODEL, raising=False)
    assert isinstance(_curator.get_curator(), _curator.NoCurator)

    monkeypatch.setenv(_curator.ENV_MODEL, "modelo-b")
    assert _curator.get_curator().model == "modelo-b"


def test_cambio_en_caliente_cambia_el_modelo_en_la_telemetria(tmp_path, monkeypatch):
    """La telemetría registra el modelo que estaba activo en cada llamada."""
    db = _db_con_schema(tmp_path)
    db_path = Path(db.db_path)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(_curator.ENV_MODEL, "modelo-a")
    _parchear_transporte(monkeypatch, _handler_generate("resumen A"))
    _curator.get_curator(db_path=db_path).summarize("hola")

    monkeypatch.delenv(_curator.ENV_MODEL, raising=False)
    monkeypatch.setenv(_curator.ENV_MODEL, "modelo-b")
    _parchear_transporte(monkeypatch, _handler_generate("resumen B"))
    _curator.get_curator(db_path=db_path).summarize("hola")

    modelos = [f[1] for f in _filas_curator(db_path)]
    assert modelos == ["modelo-a", "modelo-b"]


# ── Fallbacks ─────────────────────────────────────────────────────────────

def test_timeout_devuelve_none(monkeypatch):
    monkeypatch.setenv(_curator.ENV_MODEL, "m")
    _parchear_transporte(monkeypatch, _handler_excepcion(httpx.ReadTimeout("t")))
    c = _curator.get_curator()
    assert c.summarize("hola") is None
    assert c.embed("hola") is None
    assert c.rerank("q", ["a"]) is None


def test_http_500_devuelve_none(monkeypatch):
    monkeypatch.setenv(_curator.ENV_MODEL, "m")
    _parchear_transporte(monkeypatch,
                         lambda r: httpx.Response(500, text="boom"))
    assert _curator.get_curator().summarize("hola") is None


def test_respuesta_malformada_devuelve_none(monkeypatch):
    """JSON inválido o respuesta sin el campo esperado → heurística."""
    monkeypatch.setenv(_curator.ENV_MODEL, "m")
    _parchear_transporte(monkeypatch,
                         lambda r: httpx.Response(200, text="esto no es json"))
    assert _curator.get_curator().summarize("hola") is None

    _parchear_transporte(monkeypatch, lambda r: httpx.Response(200, json={}))
    assert _curator.get_curator().summarize("hola") is None


def test_sin_red_devuelve_none(monkeypatch):
    monkeypatch.setenv(_curator.ENV_MODEL, "m")
    _parchear_transporte(
        monkeypatch, _handler_excepcion(httpx.ConnectError("no hay red")))
    assert _curator.get_curator().summarize("hola") is None


def test_fallo_no_propaga_excepcion(monkeypatch):
    """La excepción se come dentro de la llamada, no se propaga."""
    monkeypatch.setenv(_curator.ENV_MODEL, "m")
    _parchear_transporte(monkeypatch,
                         _handler_excepcion(RuntimeError("boom")))
    c = _curator.get_curator()
    assert c.summarize("hola") is None  # no lanza


# ── Cliente Ollama ────────────────────────────────────────────────────────

def test_summarize_devuelve_el_texto_del_modelo(monkeypatch):
    monkeypatch.setenv(_curator.ENV_MODEL, "m")
    _parchear_transporte(monkeypatch, _handler_generate("El resumen real."))
    assert _curator.get_curator().summarize("texto largo") == "El resumen real."


def test_embed_devuelve_el_vector(monkeypatch):
    monkeypatch.setenv(_curator.ENV_MODEL, "m")
    _parchear_transporte(monkeypatch,
                         _handler_embed({"hola": [0.1, 0.2, 0.3]}))
    assert _curator.get_curator().embed("hola") == [0.1, 0.2, 0.3]


def test_rerank_ordena_por_similitud(monkeypatch):
    monkeypatch.setenv(_curator.ENV_MODEL, "m")
    _parchear_transporte(monkeypatch, _handler_embed({
        "consulta": [1.0, 0.0],
        "lejano": [0.0, 1.0],
        "cercano": [1.0, 0.0],
    }))
    orden = _curator.get_curator().rerank("consulta", ["lejano", "cercano"])
    assert orden == [1, 0]


def test_rerank_con_embeddings_incompletos_devuelve_none(monkeypatch):
    """Respuesta malformada → fallback, no un orden inventado."""
    monkeypatch.setenv(_curator.ENV_MODEL, "m")
    _parchear_transporte(monkeypatch,
                         lambda r: httpx.Response(200, json={"embeddings": []}))
    assert _curator.get_curator().rerank("q", ["a", "b"]) is None


# ── Telemetría ────────────────────────────────────────────────────────────

def test_telemetria_escribe_la_llamada(tmp_path, monkeypatch):
    db = _db_con_schema(tmp_path)
    db_path = Path(db.db_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(_curator.ENV_MODEL, "granite4:tiny")
    _parchear_transporte(monkeypatch, _handler_generate("resumen"))

    _curator.get_curator(db_path=db_path).summarize("texto", max_tokens=100)

    filas = _filas_curator(db_path)
    assert len(filas) == 1
    kind, model, latencia, fallback, in_tok, out_tok = filas[0]
    assert kind == "summarize"
    assert model == "granite4:tiny"
    assert latencia >= 0
    assert fallback == 0, "una llamada correcta no debe marcarse como fallback"
    assert in_tok == 42 and out_tok == 7


def test_telemetria_marca_el_fallback(tmp_path, monkeypatch):
    db = _db_con_schema(tmp_path)
    db_path = Path(db.db_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(_curator.ENV_MODEL, "m")
    _parchear_transporte(monkeypatch,
                         _handler_excepcion(httpx.ReadTimeout("t")))

    assert _curator.get_curator(db_path=db_path).summarize("texto") is None

    filas = _filas_curator(db_path)
    assert len(filas) == 1
    assert filas[0][3] == 1, "el fallback tiene que quedar marcado"


def test_sin_curador_no_hay_telemetria(tmp_path, monkeypatch):
    db = _db_con_schema(tmp_path)
    db_path = Path(db.db_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(_curator.ENV_MODEL, raising=False)

    _curator.get_curator(db_path=db_path).summarize("texto")
    assert _filas_curator(db_path) == []


def test_status_agrega_las_ultimas_24h(tmp_path, monkeypatch):
    db = _db_con_schema(tmp_path)
    db_path = Path(db.db_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(_curator.ENV_MODEL, "m")
    _parchear_transporte(monkeypatch, _handler_generate("resumen"))

    _curator.get_curator(db_path=db_path).summarize("texto")

    estado = _curator.status(db_path)
    assert estado["enabled"] is True
    assert estado["model"] == "m"
    assert estado["ollama_host"] == _curator.DEFAULT_OLLAMA_HOST
    assert estado["last_24h"]["calls"] == 1
    assert estado["last_24h"]["fallback_rate"] == 0.0


def test_status_sin_curador_da_ceros(tmp_path, monkeypatch):
    db = _db_con_schema(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(_curator.ENV_MODEL, raising=False)
    estado = _curator.status(db.db_path)
    assert estado["enabled"] is False
    assert estado["model"] == ""
    assert estado["last_24h"] == {"calls": 0, "avg_latency": 0.0,
                                  "fallback_rate": 0.0}


# ── Integración: token_filter ─────────────────────────────────────────────

def test_token_filter_sin_curador_usa_el_corte_por_chars(monkeypatch):
    from token_filter import summarize_for_context

    monkeypatch.delenv(_curator.ENV_MODEL, raising=False)
    salida = "\n".join(f"línea {i}" for i in range(200))
    resumen = summarize_for_context(salida, head_lines=3, tail_lines=2)

    assert resumen.startswith("línea 0\nlínea 1\nlínea 2")
    assert "líneas omitidas" in resumen
    assert resumen.endswith("línea 198\nlínea 199")


def test_token_filter_con_curador_usa_el_resumen_semantico(monkeypatch):
    from token_filter import summarize_for_context

    monkeypatch.setenv(_curator.ENV_MODEL, "m")
    _parchear_transporte(monkeypatch, _handler_generate("Resumen semántico."))
    salida = "\n".join(f"línea {i}" for i in range(200))
    assert summarize_for_context(salida) == "Resumen semántico."


def test_token_filter_con_curador_caido_vuelve_a_la_heuristica(monkeypatch):
    from token_filter import summarize_for_context

    monkeypatch.setenv(_curator.ENV_MODEL, "m")
    _parchear_transporte(monkeypatch,
                         _handler_excepcion(httpx.ReadTimeout("t")))
    salida = "\n".join(f"línea {i}" for i in range(200))
    resumen = summarize_for_context(salida, head_lines=3, tail_lines=2)
    assert "líneas omitidas" in resumen


# ── Integración: handoff ──────────────────────────────────────────────────

def test_handoff_sin_curador_usa_la_plantilla_fija(tmp_path, monkeypatch):
    from handoff import serialize_handoff

    db = _db_con_schema(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(_curator.ENV_MODEL, raising=False)
    _run(db.set_phase(3, "in_progress", notes="midiendo el context window"))

    ruta = _run(serialize_handoff(tmp_path, "sesion-1", db))
    contenido = ruta.read_text(encoding="utf-8")
    assert "## Resumen de la sesión (curador)" not in contenido
    assert "## Fase actual" in contenido
    assert "- 3 ·" in contenido and "in_progress" in contenido


def test_handoff_con_curador_escribe_resumen_narrativo(tmp_path, monkeypatch):
    from handoff import serialize_handoff

    db = _db_con_schema(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(_curator.ENV_MODEL, "m")
    _parchear_transporte(monkeypatch,
                         _handler_generate("La sesión avanzó el Sprint 18."))
    _run(db.set_phase(3, "in_progress", notes="midiendo el context window"))

    ruta = _run(serialize_handoff(tmp_path, "sesion-1", db))
    contenido = ruta.read_text(encoding="utf-8")
    assert "## Resumen de la sesión (curador)" in contenido
    assert "La sesión avanzó el Sprint 18." in contenido
    # El curador solo AÑADE: el bloque de fases sigue intacto.
    assert "## Fase actual" in contenido
    assert "- 3 ·" in contenido and "in_progress" in contenido


def test_handoff_con_curador_solo_anade_el_bloque(tmp_path, monkeypatch):
    """Con curador y sin él, el handoff difiere SOLO en el bloque nuevo."""
    from handoff import serialize_handoff

    db = _db_con_schema(tmp_path)
    monkeypatch.chdir(tmp_path)
    _run(db.set_phase(3, "in_progress", notes="midiendo el context window"))

    monkeypatch.delenv(_curator.ENV_MODEL, raising=False)
    sin = _run(serialize_handoff(tmp_path, "sesion-1", db)).read_text(
        encoding="utf-8")

    monkeypatch.setenv(_curator.ENV_MODEL, "m")
    _parchear_transporte(monkeypatch,
                         _handler_generate("Narrativa del curador."))
    con = _run(serialize_handoff(tmp_path, "sesion-1", db)).read_text(
        encoding="utf-8")

    bloque = "## Resumen de la sesión (curador)\n\nNarrativa del curador.\n\n"
    assert con.replace(bloque, "", 1) == sin


def test_handoff_con_curador_caido_no_rompe(tmp_path, monkeypatch):
    from handoff import serialize_handoff

    db = _db_con_schema(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(_curator.ENV_MODEL, "m")
    _parchear_transporte(monkeypatch,
                         _handler_excepcion(httpx.ConnectError("sin red")))

    ruta = _run(serialize_handoff(tmp_path, "sesion-1", db))
    contenido = ruta.read_text(encoding="utf-8")
    assert "## Resumen de la sesión (curador)" not in contenido
    assert "## Fase actual" in contenido


# ── Integración: re-rank de búsqueda ──────────────────────────────────────

def test_rerank_sin_curador_conserva_el_orden_bm25(tmp_path, monkeypatch):
    from synthesis import rerank_with_curator

    monkeypatch.delenv(_curator.ENV_MODEL, raising=False)
    resultados = [{"content": "a"}, {"content": "b"}, {"content": "c"}]
    assert rerank_with_curator("q", resultados) == resultados


def test_rerank_con_curador_reordena(tmp_path, monkeypatch):
    from synthesis import rerank_with_curator

    monkeypatch.setenv(_curator.ENV_MODEL, "m")
    _parchear_transporte(monkeypatch, _handler_embed({
        "consulta": [1.0, 0.0],
        "lejano": [0.0, 1.0],
        "cercano": [1.0, 0.0],
    }))
    resultados = [{"content": "lejano"}, {"content": "cercano"}]
    reordenados = rerank_with_curator("consulta", resultados)
    assert [r["content"] for r in reordenados] == ["cercano", "lejano"]


def test_rerank_con_curador_caido_conserva_el_orden(tmp_path, monkeypatch):
    from synthesis import rerank_with_curator

    monkeypatch.setenv(_curator.ENV_MODEL, "m")
    _parchear_transporte(monkeypatch,
                         _handler_excepcion(httpx.ReadTimeout("t")))
    resultados = [{"content": "a"}, {"content": "b"}]
    assert rerank_with_curator("q", resultados) == resultados


def test_search_hybrid_sin_curador_devuelve_el_orden_de_siempre(
        tmp_path, monkeypatch):
    db = _db_con_schema(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(_curator.ENV_MODEL, raising=False)
    _run(db.add_decision(category="arquitectura",
                         decision="Persistir el contexto en un fichero por proyecto",
                         reasoning="Cero dependencias", phase=2))

    resultados = _run(db.search_hybrid("contexto fichero"))
    assert resultados
    assert "Persistir el contexto" in resultados[0]["content"]


def test_search_hybrid_con_curador_no_descarta_resultados(tmp_path, monkeypatch):
    db = _db_con_schema(tmp_path)
    monkeypatch.chdir(tmp_path)
    _run(db.add_decision(category="arquitectura",
                         decision="Persistir el contexto en un fichero por proyecto",
                         reasoning="Cero dependencias", phase=2))
    _run(db.add_decision(category="arquitectura",
                         decision="Persistir el contexto en una base de datos",
                         reasoning="Consultas agregadas", phase=2))

    monkeypatch.delenv(_curator.ENV_MODEL, raising=False)
    sin = _run(db.search_hybrid("contexto persistir"))

    monkeypatch.setenv(_curator.ENV_MODEL, "m")
    _parchear_transporte(monkeypatch, _handler_embed({}))
    con = _run(db.search_hybrid("contexto persistir"))

    assert con, "el re-rank no puede vaciar la búsqueda"
    assert len(con) == len(sin), "el curador reordena, no descarta"
    assert {r["source_id"] for r in con} == {r["source_id"] for r in sin}


# ── Garantía dura ─────────────────────────────────────────────────────────

def test_sin_env_no_se_abre_ninguna_conexion(monkeypatch, tmp_path):
    """Con la env vacía, ningún punto de integración toca Ollama."""
    from handoff import serialize_handoff
    from token_filter import summarize_for_context

    db = _db_con_schema(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(_curator.ENV_MODEL, raising=False)

    def _boom(*args, **kwargs):
        raise AssertionError("se abrió una conexión HTTP con el curador OFF")

    monkeypatch.setattr(_curator.httpx, "Client", _boom)

    salida = "\n".join(f"línea {i}" for i in range(200))
    assert summarize_for_context(salida)
    _run(db.set_phase(1, "in_progress"))
    _run(serialize_handoff(tmp_path, "sesion-1", db))
    _run(db.add_decision(category="arquitectura",
                         decision="Decisión de prueba para la búsqueda",
                         reasoning="Relleno", phase=2))
    _run(db.search_hybrid("decisión prueba"))
    assert _filas_curator(Path(db.db_path)) == []


def test_el_curador_apagado_no_toca_la_tabla_de_telemetria(tmp_path, monkeypatch):
    from token_filter import summarize_for_context

    db = _db_con_schema(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(_curator.ENV_MODEL, raising=False)
    summarize_for_context("\n".join(f"línea {i}" for i in range(200)))
    assert _filas_curator(Path(db.db_path)) == []


def test_schema_contiene_la_tabla_del_curador():
    from context_db import _SCHEMA
    assert "CREATE TABLE IF NOT EXISTS curator_calls" in _SCHEMA
    for columna in ("kind", "model", "latency_ms", "fallback_used",
                    "input_tokens", "output_tokens"):
        assert columna in _SCHEMA


# ── Handlers MCP ──────────────────────────────────────────────────────────

def _cargar_handlers():
    """Carga `mcp/handlers/` como `apex_handlers`, igual que el server.

    Tensión de sys.path: `from mcp.types import TextContent` exige que gane
    el SDK, así que la raíz del repo va AL FINAL del path.
    """
    import importlib.util
    import sys

    repo = Path(__file__).resolve().parent.parent
    pkg = repo / "mcp" / "handlers"
    spec = importlib.util.spec_from_file_location(
        "apex_handlers", pkg / "__init__.py",
        submodule_search_locations=[str(pkg)],
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["apex_handlers"] = mod
    raiz = str(repo)
    original = list(sys.path)
    sys.path[:] = [p for p in sys.path if p != raiz] + [raiz]
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.path[:] = original
    return mod


def _db_falso(db_path: Path):
    class _Db:
        pass

    db = _Db()
    db.db_path = db_path
    return db


def test_handler_status_devuelve_el_estado(tmp_path, monkeypatch):
    _cargar_handlers()
    from apex_handlers.curator import handle_apex_curator_status

    db = _db_con_schema(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(_curator.ENV_MODEL, raising=False)

    salida = _run(handle_apex_curator_status(db, {}))
    payload = json.loads(salida[0].text)
    assert payload["enabled"] is False
    assert payload["model"] == ""
    assert payload["ollama_host"] == _curator.DEFAULT_OLLAMA_HOST
    assert payload["last_24h"]["calls"] == 0


def test_handler_test_con_curador_apagado(tmp_path, monkeypatch):
    _cargar_handlers()
    from apex_handlers.curator import handle_apex_curator_test

    db = _db_con_schema(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(_curator.ENV_MODEL, raising=False)

    salida = _run(handle_apex_curator_test(db, {"text": "hola"}))
    assert "Curador OFF" in salida[0].text


def test_handler_test_hace_un_resumen(tmp_path, monkeypatch):
    _cargar_handlers()
    from apex_handlers.curator import handle_apex_curator_test

    db = _db_con_schema(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(_curator.ENV_MODEL, "m")
    _parchear_transporte(monkeypatch, _handler_generate("Resumen de prueba."))

    salida = _run(handle_apex_curator_test(db, {"text": "contenido"}))
    assert "Curador OK" in salida[0].text
    assert "Resumen de prueba." in salida[0].text


def test_handler_test_con_kind_desconocido(tmp_path, monkeypatch):
    _cargar_handlers()
    from apex_handlers.curator import handle_apex_curator_test

    db = _db_con_schema(tmp_path)
    salida = _run(handle_apex_curator_test(db, {"text": "x", "kind": "inventado"}))
    assert "kind desconocido" in salida[0].text


def test_handler_test_caido_avisa_del_fallback(tmp_path, monkeypatch):
    _cargar_handlers()
    from apex_handlers.curator import handle_apex_curator_test

    db = _db_con_schema(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(_curator.ENV_MODEL, "m")
    _parchear_transporte(monkeypatch,
                         _handler_excepcion(httpx.ReadTimeout("t")))

    salida = _run(handle_apex_curator_test(db, {"text": "contenido"}))
    assert "caído a la heurística" in salida[0].text


# ── Test real (skip por defecto) ──────────────────────────────────────────

@pytest.mark.skipif(not os.environ.get("APEX_TEST_OLLAMA"),
                    reason="requiere Ollama real (APEX_TEST_OLLAMA=1)")
def test_ollama_real_responde():
    c = _curator.get_curator()
    if not c.enabled:
        pytest.skip("APEX_CURATOR_MODEL sin definir")
    assert c.summarize("el curador de APEX está vivo", max_tokens=50)
