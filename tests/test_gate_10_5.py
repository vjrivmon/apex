"""El gate 10.5 bloquea de verdad la entrada en la fase 11.

Auditoría del 2026-10-19: el gate de seguridad 10.5 no bloqueaba nada.
- `apex_security_gate` solo redactaba un informe: no escribía veredicto.
- `apex_set_phase` resolvía el bloqueo con un único `blocking_phase`, que
  para la entrada en la fase 11 era la fase 10: la 10.5 nunca se consultaba.
- Las 8 capas de `.apex/security/L1..L8-*.md` llevan `status: partial`, así
  que el informe salía siempre BLOCKED... sin que eso frenara nada.

Estos tests fijan el comportamiento corregido: el gate 10.5 persiste un
veredicto, y entrar en la fase 11 exige que ese veredicto (y el de la fase
10) no bloqueen.
"""
from __future__ import annotations

import asyncio
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

from security_gate import (  # noqa: E402
    GITLEAKS_MARKERS,
    SECURITY_GATE_PHASE,
    _check_gitleaks_configured,
    check_gate,
    verdict_from_report,
)

from test_handlers_not_stubbed import handlers, run  # noqa: F401  (fixture)

GATE = SECURITY_GATE_PHASE   # 10.5
DEPLOY = 11
FASE_10 = 10


@pytest.fixture(autouse=True)
def _handlers(handlers):
    """El paquete `apex_handlers` lo registra la fixture compartida."""
    return handlers


@pytest.fixture
def proyecto(tmp_path, monkeypatch):
    """Proyecto APEX real en tmp_path: el handler resuelve la raíz por cwd."""
    from context_db import ApexContextDB

    raiz = tmp_path / "proyecto"
    (raiz / ".apex").mkdir(parents=True)
    monkeypatch.chdir(raiz)
    db = ApexContextDB(str(raiz / ".apex" / "context.db"))
    asyncio.run(db.initialize())
    return db


def _verdict(db, phase, bloquea, quality=3, issues=None, reasoning="veredicto de prueba"):
    """Escribe un veredicto como lo haría el grader."""
    return run(db.add_verdict(
        phase=phase, quality=quality, reasoning=reasoning, category="test",
        issues=issues or [], should_block=bloquea,
    ))


def _set_phase(db, argumentos):
    from apex_handlers.context import handle_apex_set_phase

    return run(handle_apex_set_phase(db, argumentos))[0].text


def _escribir_capas(raiz: Path, status: str) -> None:
    """Escribe las 8 capas L1..L8 con el status pedido."""
    from security_gate import REQUIRED_LAYERS

    seg = raiz / ".apex" / "security"
    seg.mkdir(parents=True, exist_ok=True)
    for layer_id, nombre in REQUIRED_LAYERS:
        (seg / f"{layer_id}-{nombre}.md").write_text(
            f"---\nlayer: {layer_id}\ntitle: {nombre}\nstatus: {status}\n"
            "asi_coverage:\n  - ASI01\nevidence:\n  - evidencia de prueba\n"
            f"---\n\n# {layer_id}\n",
            encoding="utf-8")


# ── el veredicto del gate 10.5 existe y se persiste ─────────────────────

def test_el_gate_persiste_el_veredicto_105(proyecto):
    """`apex_security_gate` deja veredicto en la BD: sin él no hay gate."""
    from apex_handlers.security import handle_apex_security_gate

    texto = run(handle_apex_security_gate(proyecto, {}))[0].text
    assert "BLOCKED" in texto

    veredictos = run(proyecto.list_verdicts(limit=10))
    assert len(veredictos) == 1, "el gate no persistió ningún veredicto"
    assert veredictos[0]["phase"] == GATE
    assert veredictos[0]["should_block"] is True


def test_el_veredicto_105_se_guarda_como_10_5_y_se_recupera(proyecto):
    """La fase 10.5 no es un entero: SQLite la guarda como REAL.

    Con afinidad INTEGER pero tipado dinámico, 10.5 se conserva (no se
    trunca a 10, que es lo que haría un cast). Se comprueba sobre el
    fichero real, no sobre el dict que devuelve la API.
    """
    from apex_handlers.security import handle_apex_security_gate

    run(handle_apex_security_gate(proyecto, {}))

    ruta = Path(proyecto.db_path)
    conn = sqlite3.connect(str(ruta))
    fila = conn.execute(
        "SELECT phase, typeof(phase) FROM grader_verdicts").fetchone()
    conn.close()
    assert fila is not None, "no se escribió ningún veredicto"
    assert fila[0] == 10.5, f"la fase guardada no es 10.5: {fila[0]!r}"
    assert fila[1] == "real", f"SQLite no conservó el 10.5: {fila[1]!r}"

    # Y se recupera por la vía normal del gate.
    ultimo = run(proyecto.get_latest_verdict(GATE))
    assert ultimo is not None
    assert ultimo["phase"] == 10.5
    assert ultimo["should_block"] is True


def test_el_veredicto_105_no_contamina_el_de_la_fase_10(proyecto):
    """10.5 y 10 son fases distintas: un veredicto no sustituye al otro."""
    from apex_handlers.security import handle_apex_security_gate

    run(handle_apex_security_gate(proyecto, {}))

    assert run(proyecto.get_latest_verdict(FASE_10)) is None
    assert run(proyecto.get_latest_verdict(GATE)) is not None


def test_el_gate_aprueba_y_no_bloquea_si_las_ocho_capas_pasan(proyecto):
    """Con las 8 capas en passed el veredicto es verde."""
    from apex_handlers.security import handle_apex_security_gate

    _escribir_capas(Path.cwd(), "passed")
    texto = run(handle_apex_security_gate(proyecto, {}))[0].text
    assert "PASSED" in texto

    ultimo = run(proyecto.get_latest_verdict(GATE))
    assert ultimo is not None
    assert ultimo["should_block"] is False
    assert ultimo["quality"] == 4
    assert ultimo["issues"] == []


def test_la_calidad_105_depende_de_las_capas_superadas(tmp_path):
    """quality va de 0 a 4 según cuántas capas estén en passed."""
    report = check_gate(tmp_path)
    assert verdict_from_report(report)["quality"] == 0

    _escribir_capas(tmp_path, "passed")
    assert verdict_from_report(check_gate(tmp_path))["quality"] == 4


def test_las_capas_que_fallan_aparecen_en_issues_y_reasoning(tmp_path):
    """El veredicto dice QUÉ falla, no solo que falla."""
    _escribir_capas(tmp_path, "partial")
    v = verdict_from_report(check_gate(tmp_path))
    assert v["should_block"] is True
    assert len(v["issues"]) == 8
    assert all(isinstance(i, str) for i in v["issues"])
    assert "L1" in v["reasoning"]


# ── la transición 10.5 → 11 ──────────────────────────────────────────────

def test_entrar_en_fase_11_sin_veredicto_105_bloquea(proyecto):
    """Sin veredicto del gate no se entra: es fail-closed."""
    texto = _set_phase(proyecto, {"phase_number": DEPLOY, "status": "in_progress"})
    assert "BLOQUEADO" in texto
    assert "10.5" in texto
    assert "apex_security_gate" in texto


def test_entrar_en_fase_11_con_los_dos_verdicts_en_verde_pasa(proyecto):
    """Veredicto de la 10 y de la 10.5 en verde: la transición pasa."""
    _verdict(proyecto, FASE_10, False, quality=4)
    _verdict(proyecto, GATE, False, quality=4)

    texto = _set_phase(proyecto, {"phase_number": DEPLOY, "status": "in_progress"})
    assert "BLOQUEADO" not in texto
    assert "Fase 11 → in_progress" in texto


def test_entrar_en_fase_11_con_veredicto_105_bloqueante_bloquea(proyecto):
    """Un gate 10.5 en rojo frena la entrada a la fase 11."""
    _verdict(proyecto, FASE_10, False, quality=4)
    _verdict(proyecto, GATE, True, quality=1, issues=["L3: partial"])

    texto = _set_phase(proyecto, {"phase_number": DEPLOY, "status": "in_progress"})
    assert "BLOQUEADO" in texto
    assert "L3: partial" in texto


def test_entrar_en_fase_11_con_veredicto_10_bloqueante_bloquea(proyecto):
    """El control previo no se pierde: la 10 en rojo también frena."""
    _verdict(proyecto, FASE_10, True, quality=1, issues=["no_git_init"])
    _verdict(proyecto, GATE, False, quality=4)

    texto = _set_phase(proyecto, {"phase_number": DEPLOY, "status": "in_progress"})
    assert "BLOQUEADO" in texto
    assert "no_git_init" in texto


def test_force_deja_pasar_y_registra_el_override_como_error(proyecto):
    """El escape hatch sobrevive: force=True pasa y queda anotado."""
    _verdict(proyecto, FASE_10, True, quality=1, issues=["no_git_init"])
    _verdict(proyecto, GATE, False, quality=4)

    texto = _set_phase(proyecto, {
        "phase_number": DEPLOY, "status": "in_progress",
        "force": True, "force_reason": "deuda de seguridad aceptada",
    })
    assert "BLOQUEADO" not in texto
    assert "Fase 11 → in_progress" in texto

    errores = run(proyecto.get_errors(source="claude"))
    assert len(errores) == 1, "el override no quedó registrado como error"
    assert errores[0]["severity"] == "high"
    assert "deuda de seguridad aceptada" in errores[0]["lesson"]


def test_force_sin_veredicto_105_tambien_registra_el_override(proyecto):
    """Forzar la entrada sin veredicto del gate también queda anotado."""
    texto = _set_phase(proyecto, {
        "phase_number": DEPLOY, "status": "in_progress",
        "force": True, "force_reason": "gate pendiente",
    })
    assert "BLOQUEADO" not in texto

    errores = run(proyecto.get_errors(source="claude"))
    assert len(errores) == 1
    assert "gate de seguridad" in errores[0]["description"]


def test_gate_rojo_real_impide_entrar_en_fase_11(proyecto):
    """Extremo a extremo: el gate 10.5 en rojo frena la entrada a la 11."""
    from apex_handlers.security import handle_apex_security_gate

    _escribir_capas(Path.cwd(), "partial")
    run(handle_apex_security_gate(proyecto, {}))

    texto = _set_phase(proyecto, {"phase_number": DEPLOY, "status": "in_progress"})
    assert "BLOQUEADO" in texto
    assert "10.5" in texto


def test_gate_verde_real_permite_entrar_en_fase_11(proyecto):
    """Extremo a extremo: con las 8 capas en passed, la 11 se abre."""
    from apex_handlers.security import handle_apex_security_gate

    _escribir_capas(Path.cwd(), "passed")
    run(handle_apex_security_gate(proyecto, {}))
    _verdict(proyecto, FASE_10, False, quality=4)

    texto = _set_phase(proyecto, {"phase_number": DEPLOY, "status": "in_progress"})
    assert "BLOQUEADO" not in texto
    assert "Fase 11 → in_progress" in texto


def test_verde_105_sin_veredicto_de_la_10_pasa(proyecto):
    """La fase 10 mantiene la semántica del grader: sin veredicto, deja pasar.

    El gate 10.5 es el único fail-closed: es el que exige evidencia de que
    la seguridad se ha revisado de verdad.
    """
    _verdict(proyecto, GATE, False, quality=4)

    texto = _set_phase(proyecto, {"phase_number": DEPLOY, "status": "in_progress"})
    assert "BLOQUEADO" not in texto
    assert "Fase 11 → in_progress" in texto


# ── el resto de fases no cambia ─────────────────────────────────────────

def test_otra_fase_no_exige_veredicto_del_gate(proyecto):
    """Entrar en la fase 9 no pide el veredicto de la 10.5."""
    texto = _set_phase(proyecto, {"phase_number": 9, "status": "in_progress"})
    assert "BLOQUEADO" not in texto
    assert "Fase 9 → in_progress" in texto


def test_otra_fase_sigue_respetando_su_veredicto(proyecto):
    """Entrar en la fase 9 con la fase 8 en rojo: bloquea, como siempre."""
    _verdict(proyecto, 8, True, quality=1, issues=["sin tests"])

    texto = _set_phase(proyecto, {"phase_number": 9, "status": "in_progress"})
    assert "BLOQUEADO" in texto
    assert "sin tests" in texto


def test_otra_fase_pasa_con_su_veredicto_en_verde(proyecto):
    """Comportamiento previo intacto: veredicto en verde, transición pasa."""
    _verdict(proyecto, 8, False, quality=3)

    texto = _set_phase(proyecto, {"phase_number": 9, "status": "in_progress"})
    assert "BLOQUEADO" not in texto
    assert "Fase 9 → in_progress" in texto


def test_cerrar_una_otra_fase_no_exige_el_gate(proyecto):
    """El gate 10.5 solo se exige al entrar en la fase 11."""
    texto = _set_phase(proyecto, {"phase_number": 8, "status": "completed"})
    assert "BLOQUEADO" not in texto
    assert "Fase 8 → completed" in texto


# ── gitleaks en la fase 10 (Gap F, S19.1c) ──────────────────────────────

def test_gitleaks_no_configurado_devuelve_false(tmp_path):
    assert _check_gitleaks_configured(tmp_path) is False


def test_gitleaks_detectado_con_husky_pre_commit(tmp_path):
    hook = tmp_path / ".husky" / "pre-commit"
    hook.parent.mkdir(parents=True)
    hook.write_text("#!/bin/sh\ngitleaks protect --staged --redact\n")
    assert _check_gitleaks_configured(tmp_path) is True


def test_gitleaks_detectado_con_gitleaks_toml(tmp_path):
    (tmp_path / ".gitleaks.toml").write_text("[extend]\nuseDefault = true\n")
    assert _check_gitleaks_configured(tmp_path) is True


def test_los_marcadores_de_gitleaks_son_los_dos_esperados():
    assert GITLEAKS_MARKERS == (Path(".husky") / "pre-commit", Path(".gitleaks.toml"))


def test_entrar_en_fase_10_sin_gitleaks_bloquea(proyecto):
    """La fase 10 (seguridad) exige gitleaks configurado."""
    texto = _set_phase(proyecto, {"phase_number": FASE_10, "status": "in_progress"})
    assert "BLOQUEADO" in texto
    assert "gitleaks" in texto
    assert "apex_scaffold_devops" in texto


def test_entrar_en_fase_10_con_gitleaks_pasa(proyecto):
    """Con el hook instalado la entrada a la fase 10 no se frena."""
    hook = Path.cwd() / ".husky" / "pre-commit"
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text("#!/bin/sh\ngitleaks protect --staged --redact\n")

    texto = _set_phase(proyecto, {"phase_number": FASE_10, "status": "in_progress"})
    assert "BLOQUEADO" not in texto
    assert "Fase 10 → in_progress" in texto


def test_force_permite_entrar_en_fase_10_sin_gitleaks_y_lo_registra(proyecto):
    """El override del gate de gitleaks también queda como error."""
    texto = _set_phase(proyecto, {
        "phase_number": FASE_10, "status": "in_progress",
        "force": True, "force_reason": "gitleaks en el CI, no en local",
    })
    assert "BLOQUEADO" not in texto

    errores = run(proyecto.get_errors(source="claude"))
    assert len(errores) == 1
    assert "gitleaks" in errores[0]["description"]
    assert "gitleaks en el CI, no en local" in errores[0]["lesson"]
