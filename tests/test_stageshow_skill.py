"""Stageshow entra en APEX como skill descubrible y en el router visual.

La skill es la de Benji Taylor (MIT), vendida en `skills/stageshow/`. El
router la elige para ilustración de producto y la deja fuera de un C4.
La tool `apex_recommend_skills` expone esa elección sin proyecto APEX.
"""
from __future__ import annotations

from pathlib import Path

import skill_router
from init_claude_md import SKILLS_BY_SOLUTION_TYPE
from test_handlers_not_stubbed import handlers, run  # noqa: F401

REPO = Path(__file__).resolve().parent.parent
SKILL = REPO / "skills" / "stageshow"


def test_la_skill_se_descubre_y_carga():
    assert "stageshow" in skill_router.list_skill_names(REPO)
    cargada = skill_router.load_skill("stageshow", REPO)
    assert cargada.name == "stageshow"
    assert "bento" in cargada.description
    assert "fase 2" in cargada.description
    folded = cargada.text.casefold()
    for es, en, _ in skill_router.PROCESS:
        assert es.casefold() in folded
        assert en.casefold() in folded


def test_la_licencia_mit_esta_en_la_copia():
    licencia = (SKILL / "LICENSE").read_text(encoding="utf-8")
    assert "MIT License" in licencia
    assert "Benji Taylor" in licencia
    aviso = (SKILL / "APEX-VENDOR.md").read_text(encoding="utf-8")
    assert "802057409787133703c56001080169e347305572" in aviso
    assert "MIT" in aviso


def test_no_redistribuye_iconos_de_apps_ni_marcas_oficiales():
    iconos = (SKILL / "assets" / "app-icons.ts").read_text(encoding="utf-8")
    assert "iVBORw0KGgo" not in iconos
    assert len(iconos) < 2500
    assert "NOTICE.md" in iconos
    marcas = SKILL / "kit" / "brands"
    for nombre in (
        "linear.svg", "linear-dark.svg", "amex.svg", "amex-tile.svg", "usdc.svg",
    ):
        assert not (marcas / nombre).exists()
    registro = (marcas / "index.ts").read_text(encoding="utf-8")
    assert "'linear'" not in registro
    assert "'amex'" not in registro
    assert "'usdc'" not in registro


def test_el_router_elige_stageshow_para_trabajo_visual():
    bentos = skill_router.recommend_skills(2, "bento de la landing del producto")
    assert bentos[0] == "stageshow"
    assert "design-system" in bentos

    ui = skill_router.recommend_skills(2, "wireframes de las pantallas principales")
    assert ui[0] == "stageshow"

    fuera = skill_router.recommend_skills(
        11, "still de marketing del hero con cursor")
    assert fuera == ["stageshow"]


def test_el_router_no_elige_stageshow_para_arquitectura():
    c4 = skill_router.recommend_skills(2, "diagrama C4 de contenedores")
    assert "stageshow" not in c4
    assert "design-system" in c4

    codigo = skill_router.recommend_skills(6, "implementa el parser del endpoint")
    assert codigo == []


def test_la_fase_2_y_el_comando_nombran_la_skill():
    fase = (REPO / "commands" / "phases" / "02-design.md").read_text(encoding="utf-8")
    assert "stageshow" in fase
    assert "mirar" in fase
    assert "correcciones" in fase
    router = (REPO / "commands" / "apex.md").read_text(encoding="utf-8")
    assert "stageshow" in router


def test_una_app_recomienda_stageshow_en_el_claude_md():
    assert "stageshow" in SKILLS_BY_SOLUTION_TYPE["app"]


def test_el_handler_expone_el_proceso(handlers):
    from apex_handlers.skills import handle_apex_recommend_skills

    assert "apex_recommend_skills" in handlers.HANDLERS
    texto = run(handle_apex_recommend_skills(None, {
        "phase": 2,
        "brief": "bento de la landing",
    }))[0].text
    assert "stageshow" in texto
    assert "mirar (look)" in texto
    assert "filmar (film)" in texto
    assert "skills/stageshow/SKILL.md" in texto

    arquitectura = run(handle_apex_recommend_skills(None, {
        "phase": 2,
        "brief": "diagrama C4 de contenedores",
    }))[0].text
    assert "stageshow" not in arquitectura


def test_la_tool_no_exige_proyecto_apex():
    import importlib.util
    import sys

    raiz = str(REPO)
    original = list(sys.path)
    for p in ("", ".", raiz):
        while p in sys.path:
            sys.path.remove(p)
    sys.path.insert(0, str(REPO / "lib"))
    sys.path.append(raiz)
    try:
        spec = importlib.util.spec_from_file_location(
            "apex_server_stageshow", REPO / "mcp" / "apex_server.py",
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules["apex_server_stageshow"] = mod
        spec.loader.exec_module(mod)
        assert "apex_recommend_skills" in mod.NO_PROJECT_DB_TOOLS
        nombres = {t.name for t in run(mod.list_tools())}
        assert "apex_recommend_skills" in nombres
    finally:
        sys.path[:] = original


def test_la_muestra_sigue_el_proceso_y_tiene_captura():
    proceso = (SKILL / "samples" / "PROCESO.md").read_text(encoding="utf-8")
    for paso in ("Mirar", "Historia", "Ejemplo", "Filmar", "Correcciones"):
        assert paso in proceso
    html = (SKILL / "samples" / "apex-bento.html").read_text(encoding="utf-8")
    assert "Diseño" in html
    assert "Filmar" in html
    assert "mirar, historia, ejemplo, filmar, correcciones" in html
    png = SKILL / "samples" / "apex-bento.png"
    assert png.is_file()
    assert png.stat().st_size > 10_000
