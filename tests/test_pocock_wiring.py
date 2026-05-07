"""Sprint 15 S15.8 — tests del wiring del flujo Pocock en commands/apex.md.

No prueban código ejecutable; validan que la documentación expone los
anchors necesarios para que el orquestador (Claude Code main) y el
Advisor sepan que existen `apex_handoff_skill`, `apex_prototype_init` y
`apex_resume_skill_handoff` y cómo se relacionan en el flujo Pocock.

Si alguien renombra una tool o reescribe la sección sin esos términos,
estos tests fallan y obligan a actualizar la doc.
"""
from __future__ import annotations

from pathlib import Path

import pytest


_APEX_MD = (
    Path(__file__).resolve().parent.parent / "commands" / "apex.md"
)


@pytest.fixture(scope="module")
def apex_md_text() -> str:
    return _APEX_MD.read_text(encoding="utf-8")


def test_pocock_section_exists(apex_md_text: str) -> None:
    """Hay una sección dedicada al flujo Pocock con esos términos."""
    assert "Flujo Pocock" in apex_md_text
    assert "skill_handoff" in apex_md_text
    assert "/prototype" in apex_md_text


def test_three_tools_documented(apex_md_text: str) -> None:
    """Las 3 tools del flujo aparecen referenciadas con su nombre real."""
    for tool in (
        "apex_handoff_skill",
        "apex_prototype_init",
        "apex_resume_skill_handoff",
    ):
        assert tool in apex_md_text, f"falta referencia a {tool}"


def test_advisor_trigger_documented(apex_md_text: str) -> None:
    """La doc explica cuándo el Advisor dispara `recommend_skill_handoff`."""
    assert "recommend_skill_handoff" in apex_md_text
    # Mención al detector de huérfanos (>30 min sin retorno)
    assert "huérfan" in apex_md_text or "huerfan" in apex_md_text
