"""La postura (reglas 21-22) se inyecta en TODOS los roles.

Ceder el criterio verificado ante presión es lo que hace que "cada sesión
sea distinta": un rol que se deja llevar en la sesión de hoy y se mantiene
firme en la de mañana no es un rol, es un Neo sin guion. Para que no
dependa del rol, la postura va en el `agent.md` de todos, no en el prompt
de uno.

La lógica venía del commit `bce5bf6` de la rama sin fusionar.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import roles as r  # noqa: E402


class TestPosturaCompartida:
    def test_esta_definida(self):
        assert hasattr(r, "_POSTURA_COMPARTIDA")
        assert len(r._POSTURA_COMPARTIDA) > 100

    def test_todos_los_roles_la_incluyen(self):
        for nombre, spec in r.ROLES.items():
            md = r.render_agent_md(spec)
            assert "## Postura (reglas absolutas 21-22" in md, (
                f"el rol {nombre} no lleva la postura compartida"
            )

    def test_la_postura_no_depende_del_rol(self):
        """Todos los roles llevan EXACTAMENTE la misma postura."""
        bloques = set()
        for spec in r.ROLES.values():
            md = r.render_agent_md(spec)
            inicio = md.index("## Postura (reglas absolutas 21-22")
            bloques.add(md[inicio:])
        assert len(bloques) == 1, "cada rol lleva una postura distinta"

    def test_el_prompt_del_rol_se_conserva(self):
        """La postura se AÑADE, no sustituye al prompt propio del rol."""
        for nombre, spec in r.ROLES.items():
            md = r.render_agent_md(spec)
            assert spec.system_prompt.rstrip() in md, (
                f"el rol {nombre} perdio su prompt propio"
            )

    def test_el_frontmatter_sigue_siendo_valido(self):
        md = r.render_agent_md(next(iter(r.ROLES.values())))
        assert md.startswith("---\n")
        assert "\n---\n\n" in md
        # El cuerpo empieza despues del frontmatter, no dentro.
        front, _, cuerpo = md.partition("\n---\n\n")
        assert "## Postura" in cuerpo
        assert "## Postura" not in front


class TestReglasAbsolutas:
    """Las reglas 21-22 tienen que existir donde el agente las lee."""

    @pytest.fixture
    def reglas(self):
        return (_REPO / "commands" / "rules" / "absolute-rules.md").read_text(
            encoding="utf-8"
        )

    def test_existen_la_21_y_la_22(self, reglas):
        assert "21. **Mantén tu criterio verificado bajo presión.**" in reglas
        assert '22. **Distingue "el usuario cambia el objetivo"' in reglas

    def test_hay_vocabulario_vinculante(self, reglas):
        """Que un gate sea un gate: no es un consejo, es un hook que rechaza."""
        assert "Vocabulario vinculante" in reglas
        assert "hay un gate o un registro auditable" in reglas

    def test_las_reglas_no_rompen_el_resto(self, reglas):
        import re

        numeros = re.findall(r"^(\d+)\. ", reglas, flags=re.M)
        assert numeros[:20] == [str(i) for i in range(1, 21)]
        assert numeros[20:22] == ["21", "22"]
