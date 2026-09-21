"""Regresión: los handlers MCP no pueden quedar truncados.

El refactor a `mcp/handlers/` (commit 33a46cd) cortó cuatro cuerpos de handler
a mitad y los dejó devolviendo el literal `'OK'`: apex_grader_evaluate,
apex_search, apex_security_gate y apex_reverse_plan. Como no lanzaban excepción,
ni los tests ni el modelo se enteraban: `apex_grader_evaluate` dejó de
persistir veredictos durante cuatro meses, y con ello `apex_set_phase` quedó
leyendo siempre el mismo verdict viejo — el flujo de fases dejó de avanzar.

Estos tests verifican COMPORTAMIENTO (se escribe en la BD, la búsqueda
devuelve filas, el gate emite un dictamen), no que la función se ejecute sin
error. Un stub que devuelve 'OK' pasa cualquier test de humo; no pasa estos.
"""
from __future__ import annotations

import asyncio
import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def handlers():
    """Carga el paquete bajo el alias `apex_handlers`, como hace el server.

    Importarlo como `mcp.handlers` ensombrecería el SDK `mcp` y rompería
    `from mcp.types import TextContent`.
    """
    pkg = _REPO / "mcp" / "handlers"
    spec = importlib.util.spec_from_file_location(
        "apex_handlers", pkg / "__init__.py",
        submodule_search_locations=[str(pkg)],
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["apex_handlers"] = mod

    # Tensión de sys.path que resuelve igual `mcp/apex_server.py`:
    #   - `from mcp.types import TextContent` exige que el SDK gane al
    #     paquete local `mcp/`, o sea la raíz del repo NO por delante.
    #   - `from lib.db_utils import ...` (lib/advisor.py:18) exige que la
    #     raíz esté presente.
    # Con la raíz al final se cumplen ambas: el SDK resuelve primero desde
    # site-packages y `lib.` sigue encontrándose.
    raiz = str(_REPO)
    original = list(sys.path)
    sys.path[:] = [p for p in sys.path if p != raiz] + [raiz]
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.path[:] = original
    return mod


@pytest.fixture
def db(tmp_path, monkeypatch):
    """BD real en tmp_path. El handler resuelve el proyecto por cwd."""
    from context_db import ApexContextDB

    apex_dir = tmp_path / ".apex"
    apex_dir.mkdir()
    monkeypatch.chdir(tmp_path)
    base = ApexContextDB(str(apex_dir / "context.db"))
    asyncio.run(base.initialize())
    return base


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _texto(salida) -> str:
    return salida[0].text


# ── apex_grader_evaluate ─────────────────────────────────────────────────

def test_grader_persiste_el_verdict(handlers, db, tmp_path):
    """El verdict acaba en grader_verdicts y es legible por el gate."""
    from apex_handlers.grader import handle_apex_grader_evaluate

    db_file = tmp_path / ".apex" / "context.db"
    antes = sqlite3.connect(db_file).execute(
        "SELECT COUNT(*) FROM grader_verdicts").fetchone()[0]

    salida = run(handle_apex_grader_evaluate(
        db, {"phase": 5, "mode": "deterministic", "persist": True}))

    despues = sqlite3.connect(db_file).execute(
        "SELECT COUNT(*) FROM grader_verdicts").fetchone()[0]
    assert despues == antes + 1, "el verdict no se persistió"

    # El gate lee por get_latest_verdict: debe encontrarlo.
    ultimo = run(db.get_latest_verdict(5))
    assert ultimo is not None
    assert ultimo["phase"] == 5

    texto = _texto(salida)
    assert texto != "OK", "handler truncado: devuelve el literal 'OK'"
    assert "Grader fase 5" in texto
    assert "Persistido como verdict #" in texto


def test_grader_respeta_persist_false(handlers, db, tmp_path):
    """persist=False evalúa pero no escribe: el parámetro no es decorativo."""
    from apex_handlers.grader import handle_apex_grader_evaluate

    db_file = tmp_path / ".apex" / "context.db"
    antes = sqlite3.connect(db_file).execute(
        "SELECT COUNT(*) FROM grader_verdicts").fetchone()[0]

    salida = run(handle_apex_grader_evaluate(
        db, {"phase": 5, "mode": "deterministic", "persist": False}))

    despues = sqlite3.connect(db_file).execute(
        "SELECT COUNT(*) FROM grader_verdicts").fetchone()[0]
    assert despues == antes, "persist=False no debe escribir"
    assert "Grader fase 5" in _texto(salida)


def test_grader_modo_deterministic_evalua(handlers, db):
    """El modo por defecto emite dictamen; antes ni siquiera evaluaba."""
    from apex_handlers.grader import handle_apex_grader_evaluate

    texto = _texto(run(handle_apex_grader_evaluate(
        db, {"phase": 5, "mode": "deterministic"})))
    assert "[PASS]" in texto or "[BLOCK]" in texto
    assert "quality" in texto
    # El dictamen se deriva de checks reales, no de una plantilla fija.
    assert "Checks:" in texto
    assert "git_initialized" in texto


def test_grader_persiste_los_campos_del_dictamen(handlers, db, tmp_path):
    """Lo guardado coincide con lo dictaminado.

    Persistir siempre `should_block=False` pasaría un test que solo cuenta
    filas, y dejaría el gate sin poder bloquear nunca.
    """
    from apex_handlers.grader import handle_apex_grader_evaluate

    # Sin git, el check determinista marca no_git_init como bloqueante.
    texto = _texto(run(handle_apex_grader_evaluate(
        db, {"phase": 5, "mode": "deterministic", "persist": True})))
    guardado = run(db.get_latest_verdict(5))

    assert guardado is not None
    bloqueado_en_texto = "[BLOCK]" in texto
    assert guardado["should_block"] == bloqueado_en_texto, (
        "el should_block persistido no coincide con el dictamen emitido")
    assert f"quality {guardado['quality']}/4" in texto
    assert guardado["deterministic_checks"], "checks vacíos: no evaluó nada"
    for issue in guardado["issues"]:
        assert issue in texto, f"issue {issue} persistido pero no reportado"


def test_ciclo_bloquear_reevaluar_desbloquear(handlers, db, tmp_path):
    """El síntoma que motivó esta reparación: con la persistencia muerta, un
    verdict bloqueante quedaba congelado y arreglar el proyecto no lo
    levantaba nunca. Aquí se comprueba el ciclo completo."""
    from apex_handlers.grader import handle_apex_grader_evaluate

    # 1. Verdict bloqueante fabricado para la fase 5.
    run(db.add_verdict(
        phase=5, quality=1, reasoning="Sin git en el proyecto",
        issues=["no_git_init"], should_block=True))
    assert run(db.get_latest_verdict(5))["should_block"] is True

    # 2. Se resuelve la causa: el proyecto pasa a tener git.
    (tmp_path / ".git").mkdir()

    # 3. Reevaluar debe producir un verdict NUEVO que levante el bloqueo.
    run(handle_apex_grader_evaluate(
        db, {"phase": 5, "mode": "deterministic", "persist": True}))

    ahora = run(db.get_latest_verdict(5))
    assert ahora["should_block"] is False, (
        "reevaluar no levantó el bloqueo: el gate seguiría frenando la fase")
    assert "no_git_init" not in ahora["issues"]


# ── apex_search ──────────────────────────────────────────────────────────

def test_search_modo_hybrid_devuelve_resultados(handlers, db):
    """El modo por defecto (hybrid) no puede quedarse sin rama de ejecución.

    Ojo con el falso positivo: el mensaje de vacío es
    `Sin resultados para '<query>' (mode=hybrid)`, así que buscar un término
    de la query dentro de la salida pasa aunque no haya ni un hit. Se afirma
    sobre texto que SOLO puede venir de una fila formateada.
    """
    from apex_handlers.context import handle_apex_search

    run(db.add_decision(
        category="arquitectura",
        decision="Persistir el contexto en un fichero incrustado por proyecto",
        reasoning="Cero dependencias y ficheros portables",
        phase=2))

    texto = _texto(run(handle_apex_search(db, {"query": "contexto proyecto"})))
    assert texto != "OK", "handler truncado: devuelve el literal 'OK'"
    assert "Sin resultados" not in texto, "no hubo hits: el assert sería vacuo"
    assert "Resultados para" in texto
    # Contenido exclusivo de la decisión insertada, ausente de la query:
    assert "incrustado" in texto
    # El formateador hybrid añade el score; el de fts no.
    assert "score=" in texto


def test_search_modo_fts_usa_su_formateador(handlers, db):
    """La rama fts existe y formatea distinto (sin score)."""
    from apex_handlers.context import handle_apex_search

    run(db.add_decision(
        category="arquitectura",
        decision="Indexar los apuntes con un motor textual incrustado",
        reasoning="Búsqueda local sin servicios externos",
        phase=2))

    texto = _texto(run(handle_apex_search(
        db, {"query": "textual", "mode": "fts"})))
    assert "Sin resultados" not in texto
    assert "mode=fts" in texto
    assert "score=" not in texto, "la rama fts no debe formatear con score"


def test_search_respeta_el_limite(handlers, db):
    """`limit` llega al motor: no es un parámetro decorativo."""
    from apex_handlers.context import handle_apex_search

    for i in range(5):
        run(db.add_decision(
            category="arquitectura",
            decision=f"Decisión número {i} sobre despliegue incrustado",
            reasoning="Relleno para ejercitar el límite",
            phase=2))

    texto = _texto(run(handle_apex_search(
        db, {"query": "despliegue incrustado", "limit": 2})))
    filas = [ln for ln in texto.splitlines() if ln.startswith("- [")]
    assert len(filas) <= 2, f"limit=2 ignorado: {len(filas)} filas"


def test_search_sin_resultados_lo_dice(handlers, db):
    """Cero hits se reporta explícitamente, no con un 'OK' mudo."""
    from apex_handlers.context import handle_apex_search

    texto = _texto(run(handle_apex_search(
        db, {"query": "zzzzquenoexistezzzz"})))
    assert "Sin resultados" in texto


# ── apex_security_gate ───────────────────────────────────────────────────

def _escribir_capas(raiz: Path, status: str) -> None:
    """Crea las 8 capas AgentArmor con el status pedido.

    Los nombres se toman de `REQUIRED_LAYERS`, no se copian: el gate busca
    ficheros por nombre exacto, y duplicar la lista aquí haría que el test
    dejara de cubrir el caso si alguna capa se renombra.
    """
    from security_gate import REQUIRED_LAYERS

    seg = raiz / ".apex" / "security"
    seg.mkdir(parents=True, exist_ok=True)
    for layer_id, nombre in REQUIRED_LAYERS:
        (seg / f"{layer_id}-{nombre}.md").write_text(
            f"---\nlayer: {layer_id}\ntitle: {nombre}\nstatus: {status}\n"
            f"asi_coverage:\n  - ASI01\nevidence:\n  - evidencia de prueba\n"
            f"---\n\n# {layer_id}\n",
            encoding="utf-8")


def test_security_gate_bloquea_si_faltan_capas(handlers, db, tmp_path):
    """Sin capas aprobadas el gate BLOQUEA. Aceptar cualquier veredicto
    dejaría pasar un stub que respondiese siempre PASSED."""
    from apex_handlers.security import handle_apex_security_gate

    texto = _texto(run(handle_apex_security_gate(db, {})))
    assert texto != "OK", "handler truncado: el gate aprobaba siempre"
    assert "BLOCKED" in texto, "sin capas el gate no puede aprobar"
    assert "PASSED" not in texto


def test_security_gate_aprueba_con_las_ocho_capas(handlers, db, tmp_path):
    """Con las 8 capas en `passed` el gate aprueba: el dictamen depende de
    la evidencia real, no de una constante."""
    from apex_handlers.security import handle_apex_security_gate

    _escribir_capas(tmp_path, "passed")
    texto = _texto(run(handle_apex_security_gate(db, {})))
    assert "PASSED" in texto
    assert "BLOCKED" not in texto


def test_security_gate_escribe_el_informe(handlers, db, tmp_path):
    """El informe acaba en disco: efecto secundario observable."""
    from apex_handlers.security import handle_apex_security_gate

    texto = _texto(run(handle_apex_security_gate(db, {})))
    assert "(Report:" in texto
    ruta = Path(texto.split("(Report:")[1].split(")")[0].strip())
    assert ruta.exists(), f"el informe no se escribió en {ruta}"
    assert "Security Gate" in ruta.read_text(encoding="utf-8")


# ── apex_reverse_plan ────────────────────────────────────────────────────

def test_reverse_plan_construye_el_plan(handlers, db):
    """Devuelve tareas ordenadas y JSON, no un acuse de recibo."""
    from apex_handlers.reverse import handle_apex_reverse_plan

    # Entrada DESORDENADA a propósito: si se quita el `tasks.sort()`, el
    # orden de salida cambia y el test falla. Con la entrada ya ordenada
    # el assert de orden sería vacuo.
    scan_report = {
        "project_name": "demo",
        "findings": [
            {"id": "F_skip", "phase": 2, "severity": "high", "title": "Ignorable"},
            {"id": "F_back", "phase": 9, "severity": "low", "title": "Sin tests"},
            {"id": "F_now_low", "phase": 7, "severity": "low", "title": "Menor"},
            {"id": "F_verify", "phase": 3, "severity": "medium", "title": "Dudoso"},
            {"id": "F_now_high", "phase": 5, "severity": "high", "title": "Sin git"},
        ],
        "phases": [
            {"phase": 5, "name": "scaffold", "status": "partial", "score": 0.5},
            {"phase": 6, "name": "core", "status": "completed", "score": 1.0},
            {"phase": 9, "name": "testing", "status": "missing", "score": 0.0},
        ],
    }
    answers = {"F_skip": "a", "F_now_high": "b", "F_back": "c",
               "F_verify": "d", "F_now_low": "b"}
    texto = _texto(run(handle_apex_reverse_plan(
        db, {"scan_report": scan_report, "answers": answers})))

    assert texto != "OK", "handler truncado: devuelve el literal 'OK'"
    assert "Plan de acción: demo" in texto

    # Las cuatro acciones se mapean desde las respuestas a/b/c/d.
    assert "[NOW] F_now_high" in texto
    assert "[NOW] F_now_low" in texto
    assert "[BACKLOG] F_back" in texto
    assert "[VERIFY] F_verify" in texto
    assert "[SKIP] F_skip" in texto

    # Orden: now < verify < backlog < skip; dentro de now, high antes que low.
    posiciones = [texto.index(f"[{a}] {i}") for a, i in [
        ("NOW", "F_now_high"), ("NOW", "F_now_low"),
        ("VERIFY", "F_verify"), ("BACKLOG", "F_back"), ("SKIP", "F_skip")]]
    assert posiciones == sorted(posiciones), (
        "el plan no está ordenado por acción y severidad")

    # El JSON es parseable y coherente con el markdown.
    import json as _json
    bloque = texto.split("```json")[1].split("```")[0]
    plan = _json.loads(bloque)
    assert plan["project"] == "demo"
    assert len(plan["tasks"]) == 5
    assert plan["tasks"][0]["finding_id"] == "F_now_high"
    # phases_to_retake excluye las completed.
    retomar = {p["phase"] for p in plan["phases_to_retake"]}
    assert retomar == {5, 9}, f"fases a retomar mal filtradas: {retomar}"


# ── barrido estructural ──────────────────────────────────────────────────

def test_ningun_handler_devuelve_ok_literal():
    """Red de seguridad: detecta el patrón del corte en futuros refactors."""
    culpables = []
    for fichero in sorted((_REPO / "mcp" / "handlers").glob("*.py")):
        texto = fichero.read_text(encoding="utf-8")
        if "text='OK'" in texto or 'text="OK"' in texto:
            culpables.append(fichero.name)
    assert not culpables, (
        f"handlers devolviendo 'OK' literal (cuerpo truncado): {culpables}"
    )


# ── bloqueos vigentes vs. histórico ──────────────────────────────────────

def test_bloqueo_resuelto_no_figura_como_vigente(handlers, db):
    """Un BLOCK seguido de un PASS de la misma fase está resuelto.

    El advisor y el handoff filtraban `should_block=1` sobre el histórico, así
    que un bloqueo ya levantado seguía reportándose como vigente sesión tras
    sesión.
    """
    # Fase 5: bloqueado y luego resuelto.
    run(db.add_verdict(phase=5, quality=1, reasoning="sin git",
                       issues=["no_git_init"], should_block=True))
    run(db.add_verdict(phase=5, quality=3, reasoning="git ok",
                       issues=[], should_block=False))
    # Fase 8: sigue bloqueada.
    run(db.add_verdict(phase=8, quality=1, reasoning="datos mock",
                       issues=["mock_data"], should_block=True))

    vigentes = run(db.list_blocking_verdicts())
    fases = sorted(v["phase"] for v in vigentes)
    assert fases == [8], f"fases bloqueadas {fases}, esperada solo la 8"
    assert all("sin git" not in v["reasoning"] for v in vigentes)


def test_bloqueo_reincidente_vuelve_a_figurar(handlers, db):
    """BLOCK -> PASS -> BLOCK: el último manda, la fase está bloqueada."""
    run(db.add_verdict(phase=9, quality=1, reasoning="v1", issues=["a"],
                       should_block=True))
    run(db.add_verdict(phase=9, quality=3, reasoning="v2", issues=[],
                       should_block=False))
    run(db.add_verdict(phase=9, quality=1, reasoning="v3", issues=["b"],
                       should_block=True))

    vigentes = run(db.list_blocking_verdicts())
    assert [v["phase"] for v in vigentes] == [9]
    assert vigentes[0]["reasoning"] == "v3"


def test_el_historico_se_conserva(handlers, db):
    """Los verdicts resueltos siguen en la tabla: solo cambia qué se muestra."""
    run(db.add_verdict(phase=5, quality=1, reasoning="bloqueante",
                       issues=["x"], should_block=True))
    run(db.add_verdict(phase=5, quality=3, reasoning="resuelto",
                       issues=[], should_block=False))

    assert run(db.list_blocking_verdicts()) == []
    historico = run(db.list_verdicts(limit=20))
    assert len(historico) == 2, "el histórico no debe perder filas"
