"""Detector de frases de cierre de día (Sprint 13).

Lista cerrada y editable de frases en español que indican que Vicente quiere
parar la sesión. El matcher usa límites de palabra unicode-aware y es
case/acento-insensitive (con `unicodedata.normalize`) para no fallar por
"acabe" vs "acabé" o mayúsculas iniciales.

Sólo español: Vicente siempre interactúa en castellano (ver MEMORY:
`feedback_working_style.md`).

El hook `end-of-day-doctor.py` invoca `matches_wrapup(text)` sobre el último
prompt del usuario; si devuelve True (y el throttle del doctor lo permite),
dispara `apex_doctor.run_doctor(...)` + `apex_handoff_write`.
"""
from __future__ import annotations

import re
import unicodedata

# Lista cerrada de frases. Editar aquí si Vicente quiere añadir/quitar
# expresiones. Cada entrada se compila a regex con \b ... \b para evitar
# falsos positivos dentro de otras palabras (ej. "lo dejo aquí" matchea pero
# "dejo aquí mis notas" también — es lo deseado: si dice "dejo aquí" en
# cualquier contexto, asumimos cierre).
WRAPUP_PHRASES: tuple[str, ...] = (
    "he acabado por hoy",
    "termino por hoy",
    "lo dejo aqui",
    "lo dejo por hoy",
    "lo dejamos por hoy",
    "lo dejamos aqui",
    "continuo en otro momento",
    "continuo manana",
    "continuamos manana",
    "sigo manana",
    "seguimos manana",
    "lo retomo luego",
    "lo retomo manana",
    "lo retomamos manana",
    "hasta manana",
    "hasta luego",
    "fin del dia",
    "fin de la sesion",
    "cerramos por hoy",
    "paro por hoy",
    "paramos por hoy",
    "me voy a desconectar",
    "me desconecto",
    "ya esta por hoy",
    "lo dejo y sigo otro dia",
    "buenas noches",
)


def _normalize(text: str) -> str:
    """Lower + strip de acentos para matching robusto."""
    if not text:
        return ""
    s = text.lower().strip()
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    # Colapsa whitespace
    s = re.sub(r"\s+", " ", s)
    return s


# Pre-compilamos regex de cada frase con límites de palabra, sólo una vez.
_PATTERNS = tuple(
    re.compile(rf"(?<!\w){re.escape(p)}(?!\w)", re.UNICODE)
    for p in WRAPUP_PHRASES
)


def matches_wrapup(text: str) -> bool:
    """True si el texto contiene alguna frase de cierre. Case/acento-insensitive,
    busca como subcadena con límites de palabra (no exige que sea el prompt
    completo)."""
    norm = _normalize(text)
    if not norm:
        return False
    return any(p.search(norm) for p in _PATTERNS)


def matched_phrase(text: str) -> str | None:
    """Devuelve la frase concreta que disparó el match (útil para telemetría)."""
    norm = _normalize(text)
    if not norm:
        return None
    for raw, pat in zip(WRAPUP_PHRASES, _PATTERNS):
        if pat.search(norm):
            return raw
    return None
