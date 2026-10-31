"""Router de skills visuales.

Stageshow (Benji Taylor, MIT) cubre stills de producto, animaciones, bentos
y demos con cursor. En la fase 2 convive con design-research, brand-identity
y design-system: esas tres deciden inspiración, marca y tokens. Stageshow
entra cuando hay que mostrar la interfaz como ilustración.

El proceso, en el orden que fija la skill:

    mirar → historia → ejemplo → filmar → correcciones

Equivalen a look, story, example, film y corrections del SKILL.md upstream.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

PROCESS: tuple[tuple[str, str, str], ...] = (
    ("mirar", "look",
     "El producto real o el tema, los tokens y la fidelidad, antes de dibujar."),
    ("historia", "story",
     "Tres a cinco beats y un payoff. Entre más historia y un marco más calmo, el marco."),
    ("ejemplo", "example",
     "Copiar el ejemplo gold más cercano y sustituir el producto del brief."),
    ("filmar", "film",
     "Capturar un still al tamaño real y mirarlo al lado del gold."),
    ("correcciones", "corrections",
     "Corregir lo que la captura enseña: margen parejo, barras donde cae el ojo, texto que salta."),
)

_PHASE2_DESIGN = ("design-research", "brand-identity", "design-system")

# Ilustración de producto. Palabras sueltas de código ("parser", "endpoint")
# no entran: el brief tiene que nombrar el tipo de pieza visual.
_VISUAL = re.compile(
    r"("
    r"faux(?:\s+ui)?|"
    r"\bstills?\b|"
    r"\bbento\b|"
    r"\blanding\b|"
    r"feature[- ]cards?|"
    r"\bmockups?\b|"
    r"product (?:shot|ui|demo)|"
    r"\bwalkthrough\b|"
    r"cursor (?:demo|animation|animaci[oó]n)|"
    r"\banimaci[oó]n(?:es)?\b|"
    r"\banimation\b|"
    r"ilustraci[oó]n(?:es)?|"
    r"\bhero\b|"
    r"grid de (?:producto|features)|"
    r"captura falsa|"
    r"ui falsa|"
    r"interfaz (?:falsa|de marketing)|"
    r"demo (?:visual|animad[oa]|de producto|con cursor)|"
    r"material de marketing"
    r")",
    re.IGNORECASE,
)

_PHASE2_UI = re.compile(
    r"(pantallas?|wireframes?|identidad visual|diseño visual|"
    r"diseño de (?:la )?ui|\bui\b|\bmocks?\b)",
    re.IGNORECASE,
)

_ARCH = re.compile(
    r"\b(c4|arquitectura|diagrama de contenedores|modelo de datos)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SkillFile:
    """SKILL.md cargado desde el árbol de APEX."""

    name: str
    description: str
    path: Path
    text: str


def repo_root() -> Path:
    """Raíz del repo APEX: el padre de `lib/`."""
    return Path(__file__).resolve().parent.parent


def parse_frontmatter(text: str) -> dict[str, str]:
    """Lee el bloque YAML inicial de una skill. Una clave por línea."""
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    data: dict[str, str] = {}
    for line in text[3:end].splitlines():
        if ":" not in line or line.startswith(" "):
            continue
        key, value = line.split(":", 1)
        data[key.strip()] = value.strip().strip("'\"")
    return data


def list_skill_names(root: Path | None = None) -> list[str]:
    """Nombres de las skills con `skills/<nombre>/SKILL.md`, en orden."""
    base = (root or repo_root()) / "skills"
    return sorted(p.parent.name for p in base.glob("*/SKILL.md"))


def load_skill(name: str, root: Path | None = None) -> SkillFile:
    """Carga una skill. Falla si no hay fichero o el frontmatter no coincide."""
    path = (root or repo_root()) / "skills" / name / "SKILL.md"
    text = path.read_text(encoding="utf-8")
    meta = parse_frontmatter(text)
    declared = meta.get("name", "")
    if declared != name:
        raise ValueError(
            f"skills/{name}/SKILL.md declara name={declared!r}"
        )
    return SkillFile(
        name=name,
        description=meta.get("description", ""),
        path=path,
        text=text,
    )


def is_product_visual(brief: str) -> bool:
    """El brief pide una ilustración de producto, no un diagrama ni código."""
    return bool(_VISUAL.search(brief or ""))


def is_architecture_only(brief: str) -> bool:
    """C4, arquitectura o modelo de datos, y ninguna pieza visual."""
    text = brief or ""
    return bool(_ARCH.search(text)) and not is_product_visual(text)


def recommend_skills(phase: int | None, brief: str = "") -> list[str]:
    """Skills para una fase y un brief.

    Stageshow va la primera cuando el trabajo es visual (en cualquier fase)
    o cuando la fase 2 habla de pantallas, wireframes o UI. Un brief que solo
    pide arquitectura se queda en las skills de diseño de la fase 2, sin
    Stageshow.
    """
    text = (brief or "").strip()
    visual = is_product_visual(text)
    architecture_only = is_architecture_only(text)
    picks: list[str] = []

    if visual and not architecture_only:
        picks.append("stageshow")

    if phase == 2:
        if (not architecture_only and _PHASE2_UI.search(text)
                and "stageshow" not in picks):
            picks.insert(0, "stageshow")
        for name in _PHASE2_DESIGN:
            if name not in picks:
                picks.append(name)

    return picks


def format_recommendation(phase: int | None, brief: str = "") -> str:
    """Texto que devuelve `apex_recommend_skills`."""
    picks = recommend_skills(phase, brief)
    if not picks:
        return (
            "Ninguna skill de diseño encaja con este brief.\n"
            "Pasa la fase y una frase del entregable. "
            "Un still, un bento, una landing o una demo con cursor "
            "devuelve stageshow."
        )

    lines = ["Skills para este trabajo:"]
    for name in picks:
        lines.append(f"- {name}")

    if "stageshow" in picks:
        lines.append("")
        lines.append("stageshow sigue este orden:")
        for es, en, hint in PROCESS:
            lines.append(f"- {es} ({en}): {hint}")
        lines.append("")
        lines.append("Léela en skills/stageshow/SKILL.md.")
        lines.append("Atribución y licencias: skills/stageshow/APEX-VENDOR.md.")

    return "\n".join(lines)
