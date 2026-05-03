"""Tests del detector de frases de cierre de día (Sprint 13)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

import wrapup_phrases as w  # noqa: E402


# ── Positivos ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "he acabado por hoy",
    "He acabado por hoy",
    "HE ACABADO POR HOY",
    "he acabado por hoy, sigo otro día",
    "lo dejo aquí",
    "Lo dejo aquí, hasta mañana",
    "termino por hoy con el doctor",
    "continúo en otro momento",
    "continuo en otro momento",  # sin acento
    "lo retomo mañana, gracias",
    "hasta mañana",
    "hasta luego",
    "fin del día",
    "me desconecto",
    "me voy a desconectar",
    "buenas noches",
    "ya está por hoy",
    "lo dejamos por hoy",
])
def test_matches_wrapup_positives(text: str) -> None:
    assert w.matches_wrapup(text) is True, f"No matcheó: {text!r}"


# ── Negativos ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "",
    "vamos a seguir trabajando",
    "tengo una pregunta sobre apex",
    "apex doctor está bien",
    "qué tal va el día",
    "noches frías últimamente",  # "noches" sin "buenas"
    "termino la implementación",  # sin "por hoy"
    "lo dejo en el cajón",  # "lo dejo" sin "aquí" / "por hoy"
])
def test_matches_wrapup_negatives(text: str) -> None:
    assert w.matches_wrapup(text) is False, f"Falso positivo: {text!r}"


# ── matched_phrase devuelve la frase exacta ──────────────────────────────

def test_matched_phrase_returns_string() -> None:
    out = w.matched_phrase("Lo dejo aquí")
    assert out == "lo dejo aqui"


def test_matched_phrase_returns_none_when_no_match() -> None:
    assert w.matched_phrase("hola") is None


def test_matched_phrase_empty() -> None:
    assert w.matched_phrase("") is None


# ── Acentos / case ──────────────────────────────────────────────────────

def test_normalize_strips_accents() -> None:
    assert w._normalize("Continúo Mañana") == "continuo manana"


def test_normalize_collapses_whitespace() -> None:
    assert w._normalize("  he   acabado    por  hoy  ") == "he acabado por hoy"


def test_normalize_empty() -> None:
    assert w._normalize("") == ""
    assert w._normalize(None) == ""  # type: ignore[arg-type]


# ── Lista cerrada estable ────────────────────────────────────────────────

def test_phrase_list_is_non_empty() -> None:
    assert len(w.WRAPUP_PHRASES) >= 15


def test_phrase_list_normalized() -> None:
    """Cada entrada de la lista debe estar ya normalizada (lowercase, sin
    acentos) — si añadimos una sin normalizar, falla este test."""
    for phrase in w.WRAPUP_PHRASES:
        assert phrase == w._normalize(phrase), (
            f"Frase no normalizada en lista: {phrase!r}"
        )
