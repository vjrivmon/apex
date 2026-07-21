#!/usr/bin/env python3
"""Weekly Design Lint — escribe un resumen de inspiración en el wiki del
proyecto cada 7 días (ISO week). No hace WebFetch real (requiere LLM) —
genera un prompt/checklist que el agente debe completar manualmente o
vía tool WebFetch de Claude Code cuando se invoque.

Este hook sólo se dispara al inicio de sesión SI:
- estamos en un proyecto APEX (existe `.apex/context.db`)
- no existe ya un `design-inspiration-<ISO-week>.md` para la semana actual

Deja una nota en el wiki con las 3 URLs rotativas de la semana y pide al
agente que haga el WebFetch + síntesis al abrir el archivo.
"""
from __future__ import annotations

import datetime as dt
import os
from pathlib import Path

import sys as _sys, pathlib as _pl  # bootstrap: raíz del repo en el path
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[2]))
from lib.hook_metrics import start_hook, end_hook

# Biblioteca rotativa (clasificada por categoría para que no se repitan las mismas URLs cada semana)
LIBRARY = [
    # curadurías
    ("curación", "https://curations.supply"),
    ("curación", "https://godly.website"),
    ("curación", "https://minimal.gallery"),
    # landings
    ("landing", "https://landing.love"),
    ("landing", "https://lapa.ninja"),
    # saas
    ("saas", "https://saaspo.com"),
    ("saas", "https://saasframe.io"),
    # componentes
    ("componentes", "https://component.gallery"),
    ("componentes", "https://navbar.gallery"),
    ("componentes", "https://cta.gallery"),
    # mobile
    ("mobile", "https://mobbin.com"),
    ("mobile", "https://sleek.design"),
    # motion
    ("motion", "https://60fps.design"),
    ("motion", "https://appmotion.design"),
    # brand
    ("brand", "https://rebrand.gallery"),
    ("brand", "https://uncut.wtf"),
    # principios
    ("principios", "https://lawsofux.com"),
    ("principios", "https://drapz.design"),
]


def _pick_three_for_week(week: int) -> list[tuple[str, str]]:
    """Determinista: rota por índice de semana para que nadie repita en 6 semanas."""
    n = len(LIBRARY)
    start = (week * 3) % n
    return [LIBRARY[(start + i) % n] for i in range(3)]


def _find_project_apex_dir() -> Path | None:
    cwd = Path(os.getcwd())
    for parent in [cwd, *cwd.parents]:
        if (parent / ".apex").exists():
            return parent / ".apex"
        if parent == parent.parent:
            break
    return None


def main() -> None:
    _hook_start = start_hook("weekly-design-lint")
    apex_dir = _find_project_apex_dir()
    if apex_dir is None:
        return  # No es un proyecto APEX — silencio

    now = dt.datetime.now(dt.timezone.utc)
    year, week, _ = now.isocalendar()
    slug = f"design-inspiration-{year}-W{week:02d}"

    wiki_brand = apex_dir / "wiki" / "brand"
    wiki_brand.mkdir(parents=True, exist_ok=True)

    target = wiki_brand / f"{slug}.md"
    if target.exists():
        return  # Ya hay brief para esta semana — no pisar

    refs = _pick_three_for_week(week)
    body = [
        f"# Inspiración semanal — {year} W{week:02d}",
        "",
        "_Pendiente: el agente debe hacer WebFetch a las 3 URLs de abajo y escribir "
        "un resumen de patrones (3 por URL: tipografía, paleta, layout). Al terminar, "
        "llamar `apex_wiki_add` con slug = "
        f"`brand/{slug}` para indexar en FTS._",
        "",
        "## URLs rotativas de la semana",
        "",
    ]
    for cat, url in refs:
        body.append(f"- **[{cat}]** {url}")
    body.extend([
        "",
        "## Protocolo de síntesis",
        "",
        "Por cada URL, anotar:",
        "",
        "1. **Patrón de tipografía**: familias, pesos, escala. Algo nuevo comparado con la última semana?",
        "2. **Paleta**: 3-5 colores con hex, rol (accent/bg/text).",
        "3. **Layout / gesto visual**: qué diferencia esta página de la genérica (asimetría, motion, grid atípico, etc.).",
        "",
        "## Cross-project",
        "",
        "Antes de aplicar cualquier patrón, ejecutar "
        "`apex_search_cross_project(query=\"<patrón>\")` para ver si ya se usó o "
        "descartó en otro proyecto.",
    ])

    target.write_text("\n".join(body), encoding="utf-8")


if __name__ == "__main__":
    main()
