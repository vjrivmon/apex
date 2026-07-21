"""Configuración común de la suite.

Pone en `sys.path` tanto `lib/` (para `import context_db`) como la raíz del
repo (para `from lib.db_utils import ...`, que usan advisor y compañía desde
la refactorización de 2026-07). Sin esto, la colección falla según desde dónde
se invoque pytest.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent

for ruta in (str(_REPO / "lib"), str(_REPO)):
    if ruta not in sys.path:
        sys.path.insert(0, ruta)
