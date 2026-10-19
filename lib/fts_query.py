"""Construcción de consultas FTS5 para el retrieval cross-project.

Por qué existe esto
-------------------
FTS5 hace AND implícito: `MATCH "a b c"` exige las TRES palabras en la MISMA
fila. El retrieval cross-project pasaba la consulta cruda al `MATCH`, así que
una consulta natural como "memoria global errores graves" devolvía 0 hits
aunque la BD tuviera las tres palabras repartidas en 365 filas distintas.

Medido contra el `hub.db` real (2026-10-19):

    consulta                                 AND implícito    con OR
    'datos mock hardcodeados'                       3             434
    'gitleaks secretos filtrados'                   0              37
    'apex context db'                               61             599
    'memoria global errores graves'                 0             365
    'gradientes ui'                                  7             261

La feature "consultar los otros proyectos antes de decidir" era
prácticamente inútil: la forma de escribir una consulta con sentido es
exactamente la que FTS5 AND-and.

La solución es tokenizar, quitar stopwords y unir con OR. El `ORDER BY rank`
(BM25) sigue ordenando por relevancia: la consulta se ensancha, no se
degrada. Es el mismo criterio que usa la búsqueda de la biblioteca de libros
(70% FTS5/BM25 + 30% keyword), aplicado al lado cross-project.

La lógica venía del commit `bce5bf6` de la rama
`origin/fix/cross-project-tone-2026-07-06`, que nunca se fusionó.
"""
from __future__ import annotations

import re

# Stopwords de FTS5: palabras que no distinguen un error de otro. Sin
# filtrarlas, "el error de ayer" convierte la consulta en un OR tan ancho
# que el top-K devuelve ruido.
FTS_STOPWORDS = frozenset({
    "errores", "error", "de", "la", "el", "los", "las", "un", "una", "uno",
    "y", "o", "en", "con", "para", "por", "del", "al", "que", "the", "a",
    "an", "of", "and", "or", "in", "on", "to", "is", "was", "be",
})

# Longitud mínima de un token para entrar en la consulta. Por debajo, es
# ruido ("el", "de", "si").
MIN_TOKEN_LEN = 3

# FTS5 no acepta estos caracteres sueltos: se eliminan al tokenizar.
_TOKEN_RE = re.compile(r"[0-9A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+")


def tokenize(query: str) -> list[str]:
    """Trocea la consulta en tokens alfanuméricos, en orden y sin repetir."""
    crudos = _TOKEN_RE.findall((query or "").lower())
    vistos: set[str] = set()
    unicos: list[str] = []
    for token in crudos:
        if token in vistos:
            continue
        vistos.add(token)
        unicos.append(token)
    return unicos


def build_fts_or_query(query: str) -> str:
    """Convierte una consulta multi-palabra en una disyunción FTS5 (OR).

    Tokeniza, quita stopwords y caracteres especiales de FTS5, y une con OR
    para que cualquier término relevante haga match. `rank` sigue
    ordenando por relevancia.

    Best-effort: si tras filtrar no queda nada (consulta de puro
    stopwords), cae al token más largo del original. Si no hay tokens
    siquiera, devuelve "" y quien llama decide.
    """
    crudos = _TOKEN_RE.findall((query or "").lower())
    tokens = [
        t for t in crudos
        if len(t) >= MIN_TOKEN_LEN and t not in FTS_STOPWORDS
    ]
    if not tokens:
        # Nada útil tras filtrar: el token más largo del original.
        tokens = sorted(crudos, key=len, reverse=True)[:1]
    if not tokens:
        return ""
    vistos: set[str] = set()
    unicos = [t for t in tokens if not (t in vistos or vistos.add(t))]
    return " OR ".join(unicos)
