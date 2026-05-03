"""DESIGN.md — estándar abierto Google Labs (Sprint 10.1).

Genera y valida un `DESIGN.md` que cualquier agente IA puede leer para
respetar el sistema de diseño del proyecto. Cinco secciones obligatorias:

1. Brand — voice, avoid lines (negative constraints son más fuertes)
2. Color — semantic tokens + reglas
3. Typography — escala + reglas (max 3 sizes/screen, no italic)
4. Components — anatomía + estados + variantes
5. Accessibility / Dark — WCAG AA + cómo invertir tokens

Política: el archivo no debe pasar de 2 páginas (~200 líneas). Si crece
más, se parte en design.md + brand.md + components.md.

API:
- `default_template(brand_name)` — devuelve markdown plantilla
- `init_design_md(project_root, brand_name)` — escribe DESIGN.md si no existe
- `parse_design_md(text)` — extrae tokens y secciones
- `validate(text)` — devuelve lista de violations (estructura + WCAG)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

REQUIRED_SECTIONS = ("Brand", "Color", "Type", "Components", "Accessibility")

_HEX_RE = re.compile(r"#[0-9A-Fa-f]{6}\b")
_TOKEN_LINE_RE = re.compile(r"^\s*-\s*(\w[\w-]*)\s*:\s*(#[0-9A-Fa-f]{6})", re.M)


@dataclass
class Violation:
    severity: str  # critical | warning | info
    section: str
    message: str

    def __str__(self) -> str:
        return f"[{self.severity}] {self.section}: {self.message}"


@dataclass
class ParsedDesign:
    sections_present: set[str] = field(default_factory=set)
    color_tokens: dict[str, str] = field(default_factory=dict)
    has_avoid_line: bool = False
    has_dark_mode: bool = False
    raw: str = ""


# ── Plantilla ────────────────────────────────────────────────────────────

def default_template(brand_name: str = "Acme") -> str:
    """Plantilla mínima viable de las 5 secciones. Diseñada para que un
    agente la pueda leer y respetar sin ambigüedad."""
    return f"""# DESIGN.md — {brand_name}

> Sistema de diseño del proyecto. Cualquier agente que toque la UI lee
> este archivo antes de generar componentes. Estándar Google Labs
> (https://github.com/google-labs-code/design.md).

## Brand

Name: {brand_name}
Voice: calm, generous, practical
Avoid: gradients, glassmorphism, generic SaaS purple, neon, drop shadows

## Color

Semantic
- bg: #FAFAF7
- surface: #FFFFFF
- text: #111111
- text-muted: #555555
- border: #E5E1DA
- accent: #C45A3D
- success: #2E7D5A
- error: #B43E3E

Rules
- Nunca usar negro puro. Usar #111111.
- Nunca usar blanco puro como fondo de página. Usar `bg`.
- Accent es para un elemento por pantalla, máximo dos.
- Dark mode invierte sólo `bg` y `text`. Accent se mantiene.

## Type

- Display: Inter 600, 48px, line-height 1.1
- H1: Inter 600, 32px, line-height 1.2
- H2: Inter 600, 24px, line-height 1.3
- H3: Inter 600, 18px, line-height 1.4
- Body: Inter 400, 16px, line-height 1.6
- Caption: Inter 400, 14px, line-height 1.5
- Mono: Berkeley Mono 400 (sólo código y datos)

Rules
- No más de tres tamaños por pantalla.
- Nunca itálica. Usar peso o color para énfasis.

## Components

Button
- Radius: 8px
- Padding vertical: 14px / horizontal: 20px
- Estados: default, hover (oscurecer 8%), focus (ring 2px accent), disabled (50% opacity)
- Variantes: primary (accent bg, text blanco), secondary (sólo borde), ghost (sólo texto)

Card
- Radius: 12px
- Padding: 24px
- Border: 1px solid `border`
- Sin sombra por defecto. Sombra sólo en hover si es clicable.

Input
- Mismo radius y border que cards
- Focus ring: 2px accent, sin sombra
- Error: borde `error`, texto de ayuda debajo

## Accessibility / Dark

- Todos los elementos interactivos tienen focus ring visible.
- Contraste: WCAG 2.1 AA mínimo, AAA en body text.
- Touch targets: 44px mínimo en mobile.
- Color nunca es la única señal — añadir icono, texto o forma.

Dark mode
- `bg` ↔ `text` invertidos.
- `surface` pasa de #FFFFFF a #1A1A1A.
- `border` pasa de #E5E1DA a #2A2A2A.
- Resto de tokens se mantienen.
"""


def design_md_path(project_root: Path | str) -> Path:
    return Path(project_root) / "DESIGN.md"


def init_design_md(project_root: Path | str, brand_name: str = "Acme",
                   overwrite: bool = False) -> Path:
    """Escribe DESIGN.md en la raíz del proyecto. No sobreescribe salvo
    overwrite=True."""
    path = design_md_path(project_root)
    if path.exists() and not overwrite:
        return path
    path.write_text(default_template(brand_name), encoding="utf-8")
    return path


# ── Parser ──────────────────────────────────────────────────────────────

def parse_design_md(text: str) -> ParsedDesign:
    """Extrae estructura básica del DESIGN.md."""
    parsed = ParsedDesign(raw=text)
    if not text:
        return parsed

    # Secciones presentes (heading H2)
    for line in text.splitlines():
        if line.startswith("## "):
            heading = line[3:].strip()
            for required in REQUIRED_SECTIONS:
                if heading.lower().startswith(required.lower()):
                    parsed.sections_present.add(required)

    # Color tokens
    in_color = False
    for line in text.splitlines():
        if line.startswith("## "):
            in_color = "color" in line.lower()
            continue
        if not in_color:
            continue
        m = _TOKEN_LINE_RE.match(line)
        if m:
            parsed.color_tokens[m.group(1)] = m.group(2).upper()

    parsed.has_avoid_line = any(
        line.lower().startswith("avoid:") or line.lower().startswith("- avoid:")
        for line in text.splitlines()
    )
    parsed.has_dark_mode = "dark mode" in text.lower() or "## accessibility / dark" in text.lower()

    return parsed


# ── Validación WCAG ──────────────────────────────────────────────────────

def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _relative_luminance(rgb: tuple[int, int, int]) -> float:
    """WCAG 2.1 relative luminance."""
    def channel(c: int) -> float:
        v = c / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = rgb
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast_ratio(hex_a: str, hex_b: str) -> float:
    """WCAG contrast ratio entre dos colores hex."""
    la = _relative_luminance(_hex_to_rgb(hex_a))
    lb = _relative_luminance(_hex_to_rgb(hex_b))
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


# Pares estándar a verificar (si existen los tokens)
_CONTRAST_PAIRS = (
    ("text", "bg", 4.5, "AA body text"),
    ("text", "surface", 4.5, "AA body en surface"),
    ("text-muted", "bg", 3.0, "AA UI grande"),
    ("accent", "bg", 3.0, "AA UI grande accent"),
)


def validate(text: str) -> list[Violation]:
    """Lista de violations de estructura y contraste."""
    violations: list[Violation] = []
    parsed = parse_design_md(text)

    # 1. Estructura
    for required in REQUIRED_SECTIONS:
        if required not in parsed.sections_present:
            violations.append(Violation(
                severity="critical",
                section="structure",
                message=f"Falta la sección '## {required}'",
            ))

    if not parsed.has_avoid_line:
        violations.append(Violation(
            severity="warning",
            section="brand",
            message="Falta línea 'Avoid:' (negative constraints)",
        ))

    if not parsed.has_dark_mode:
        violations.append(Violation(
            severity="warning",
            section="accessibility",
            message="No se detecta sección 'Dark mode'",
        ))

    # 2. Contraste WCAG (si hay tokens declarados)
    tokens = parsed.color_tokens
    for fg, bg, threshold, label in _CONTRAST_PAIRS:
        if fg not in tokens or bg not in tokens:
            continue
        try:
            ratio = contrast_ratio(tokens[fg], tokens[bg])
        except Exception:
            continue
        if ratio < threshold:
            violations.append(Violation(
                severity="critical",
                section="color",
                message=(
                    f"Contraste {tokens[fg]}/{tokens[bg]} = {ratio:.2f} "
                    f"< {threshold} ({label})"
                ),
            ))

    # 3. Tamaño máximo (regla del manual: <2 páginas)
    line_count = len(text.splitlines())
    if line_count > 220:
        violations.append(Violation(
            severity="warning",
            section="size",
            message=(
                f"DESIGN.md tiene {line_count} líneas (>220). "
                "Considera dividir en design.md + brand.md + components.md."
            ),
        ))

    return violations


def format_violations(violations: Iterable[Violation]) -> str:
    items = list(violations)
    if not items:
        return "DESIGN.md PASS — sin violaciones."
    lines = [f"DESIGN.md FAIL — {len(items)} violación(es):"]
    for v in items:
        lines.append(f"  {v}")
    return "\n".join(lines)
