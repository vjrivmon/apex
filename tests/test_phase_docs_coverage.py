"""Las fases prescriben evaluar antes de cerrarse.

El gate de fase (`phase-gate.py` + el handler de `apex_set_phase`) solo puede
frenar si existe un verdict del grader. Pero quien llama al grader es el
modelo, siguiendo `commands/phases/*.md`. Hasta el 2026-09-21 solo 5 de 16
fases lo prescribían, así que el freno funcionaba en unas y en otras se
pasaba sin evaluar — un comportamiento que se vivía como "los checks de fase
fallan de forma impredecible".

Estos tests fijan la cobertura y el orden. No prueban código: prueban que las
instrucciones que gobiernan el flujo siguen completas.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_FASES = Path(__file__).resolve().parent.parent / "commands" / "phases"

# Excepciones justificadas, no olvidos:
#   10.5 tiene su propio evaluador (apex_security_gate); duplicar no aporta.
#   12   es iteración permanente: se queda en in_progress, nunca cierra.
_SIN_GRADER = {"10.5-agentarmor-gate", "12-iteration"}


def _ficheros_de_fase() -> list[Path]:
    return sorted(p for p in _FASES.glob("*.md") if p.stem != "README")


def test_hay_16_ficheros_de_fase():
    """Red de aviso: si alguien añade o quita una fase, este test lo dice."""
    assert len(_ficheros_de_fase()) == 16


@pytest.mark.parametrize("fichero", _ficheros_de_fase(), ids=lambda p: p.stem)
def test_cada_fase_prescribe_el_grader(fichero):
    """Toda fase que cierra debe evaluar antes."""
    if fichero.stem in _SIN_GRADER:
        pytest.skip(f"{fichero.stem}: excepción documentada")
    texto = fichero.read_text(encoding="utf-8")
    assert "apex_grader_evaluate" in texto, (
        f"{fichero.stem} cierra sin evaluar: el gate no tendrá verdict que "
        f"leer y la transición pasará sin control")


@pytest.mark.parametrize("fichero", _ficheros_de_fase(), ids=lambda p: p.stem)
def test_el_grader_va_antes_del_cierre(fichero):
    """Evaluar después de cerrar no sirve de nada: el gate ya dejó pasar."""
    if fichero.stem in _SIN_GRADER:
        pytest.skip(f"{fichero.stem}: excepción documentada")
    texto = fichero.read_text(encoding="utf-8")
    cierre = re.search(r'apex_set_phase\([^)]*status="completed"', texto)
    if not cierre:
        pytest.skip(f"{fichero.stem}: no cierra con status=completed")
    grader = texto.index("apex_grader_evaluate")
    assert grader < cierre.start(), (
        f"{fichero.stem}: el grader aparece después del apex_set_phase")


@pytest.mark.parametrize("fichero", _ficheros_de_fase(), ids=lambda p: p.stem)
def test_sub_pasos_sin_letras_duplicadas(fichero):
    """La inserción del grader renumera el cierre; esto lo vigila."""
    letras = [l for _, l in re.findall(
        r"^- \*\*\[(\d+(?:\.\d+)?)([a-z])\]\*\*",
        fichero.read_text(encoding="utf-8"), re.MULTILINE)]
    duplicadas = {l for l in letras if letras.count(l) > 1}
    assert not duplicadas, f"{fichero.stem}: sub-pasos repetidos {sorted(duplicadas)}"


@pytest.mark.parametrize("fichero", _ficheros_de_fase(), ids=lambda p: p.stem)
def test_sub_pasos_en_secuencia_contigua(fichero):
    """a, b, c... sin saltos: un hueco sugiere una edición a medias."""
    letras = [l for _, l in re.findall(
        r"^- \*\*\[(\d+(?:\.\d+)?)([a-z])\]\*\*",
        fichero.read_text(encoding="utf-8"), re.MULTILINE)]
    esperado = [chr(ord("a") + i) for i in range(len(letras))]
    assert letras == esperado, (
        f"{fichero.stem}: secuencia {''.join(letras)}, esperada {''.join(esperado)}")
