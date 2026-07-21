#!/usr/bin/env python3
"""Regenera el bloque de HECHOS del CLAUDE.md contando el repo real.

Motivación (auditoría 2026-07-21): el CLAUDE.md escrito a mano acumulaba ~42
afirmaciones falsas — decía 695 tests cuando había 722, marcaba sprints
cerrados como pendientes, listaba 17 tablas de 27, y describía un directorio
`frontend/` que ya no existe. Una sesión que lo leyera arrancaba con datos
falsos.

Los hechos son consultables, así que no deben escribirse a mano. Este script
cuenta lo que hay y reescribe SOLO lo que va entre los marcadores:

    <!-- APEX:STATE:BEGIN -->
    ...generado, no editar a mano...
    <!-- APEX:STATE:END -->

Todo lo demás del CLAUDE.md (la narrativa de decisiones, que es lo único que
no envejece mal) se respeta intacto.

Uso:
    python scripts/refresh_state.py            # reescribe CLAUDE.md
    python scripts/refresh_state.py --check    # solo dice si está desfasado
    python scripts/refresh_state.py --print    # imprime el bloque y sale
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BEGIN = "<!-- APEX:STATE:BEGIN -->"
END = "<!-- APEX:STATE:END -->"

# Un sprint se considera implementado si TODOS sus artefactos existen. Es una
# señal mecánica, no un juicio: por eso el bloque generado dice "artefactos
# presentes", y la valoración de si está "cerrado" se queda en la narrativa.
SPRINT_ARTIFACTS: dict[str, list[str]] = {
    "S12 roles": ["lib/roles.py"],
    "S13 doctor": ["lib/apex_doctor.py", "lib/wrapup_phrases.py"],
    "S14 skills Pocock": ["skills/tdd/SKILL.md", "skills/diagnose/SKILL.md"],
    "S15 advisor + traces": ["lib/advisor.py", "lib/reasoning_traces.py",
                             "lib/prototype.py"],
    "S16 advisor feedback": ["lib/advisor_outcomes.py", "lib/advisor_health.py",
                             "lib/advisor_tuning.py",
                             ".claude/hooks/advisor-outcome-watch.py"],
    "S17 VirtualFS": ["lib/vfs.py", "lib/vfs_grep.py"],
    "S18 Granite curator": ["lib/curator.py"],
    "S19 Advent integration": ["templates/.github/workflows/gitleaks.yml"],
    "Biblioteca de libros": ["lib/book_chunker.py", "lib/book_corpus.py"],
}


def _run(cmd: list[str], cwd: Path = REPO) -> str:
    try:
        return subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=600
        ).stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return ""


def count_test_functions() -> int:
    """Cuenta funciones `def test_` en tests/. Estático: no ejecuta la suite.

    Correr pytest desde aquí haría imposible invocar este script DESDE un test
    (pytest anidado, minutos de espera). El recuento estático basta para
    detectar deriva; `count_tests_by_running()` da el número autoritativo
    cuando se pide explícitamente.
    """
    total = 0
    for f in (REPO / "tests").glob("test_*.py"):
        total += len(re.findall(r"^\s*(?:async )?def (test_\w+)",
                                f.read_text(encoding="utf-8"), re.M))
    return total


def count_tests_by_running() -> str:
    """Ejecuta la suite para obtener el recuento real. Lento (segundos)."""
    out = _run([str(REPO / ".venv/bin/pytest"), "tests/", "-q", "--no-header"])
    m = re.search(r"(\d+) passed", out)
    fallos = re.search(r"(\d+) failed", out)
    if not m:
        return ""
    txt = f"{m.group(1)} pasando"
    if fallos:
        txt += f", **{fallos.group(1)} FALLANDO**"
    return txt


def count_tools() -> int:
    src = (REPO / "mcp/apex_server.py").read_text(encoding="utf-8")
    return len(set(re.findall(r'name="(apex_[a-z_]+)"', src)))


def count_skills() -> int:
    return len(list((REPO / "skills").glob("*/SKILL.md")))


def count_hooks() -> tuple[int, int]:
    """(ficheros en disco, registrados en settings.json del proyecto)."""
    ficheros = len(list((REPO / ".claude/hooks").glob("*.py")))
    settings = REPO / ".claude/settings.json"
    registrados = 0
    if settings.exists():
        import json
        try:
            data = json.loads(settings.read_text(encoding="utf-8"))
            vistos = set()
            for entradas in (data.get("hooks") or {}).values():
                for entrada in entradas:
                    for h in entrada.get("hooks", []):
                        cmd = h.get("command", "")
                        m = re.search(r"([\w.-]+\.py)", cmd)
                        if m:
                            vistos.add(m.group(1))
            registrados = len(vistos)
        except (json.JSONDecodeError, OSError):
            registrados = 0
    return ficheros, registrados


def count_tables() -> int:
    src = (REPO / "lib/context_db.py").read_text(encoding="utf-8")
    return len(set(re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", src)))


def sprint_rows() -> list[tuple[str, str, str]]:
    filas = []
    for nombre, artefactos in SPRINT_ARTIFACTS.items():
        faltan = [a for a in artefactos if not (REPO / a).exists()]
        if not faltan:
            estado, detalle = "presente", ", ".join(artefactos[:2])
        elif len(faltan) == len(artefactos):
            estado, detalle = "ausente", "ningún artefacto"
        else:
            estado, detalle = "parcial", f"falta {', '.join(faltan)}"
        filas.append((nombre, estado, detalle))
    return filas


def orphan_modules() -> list[str]:
    """Módulos de lib/ que nadie importa: código escrito y no cableado."""
    huerfanos = []
    fuentes = (
        list((REPO / "lib").glob("*.py"))
        + list((REPO / "mcp").glob("*.py"))
        + list((REPO / "mcp" / "handlers").glob("*.py"))  # refactor 2026-07
        + list((REPO / ".claude" / "hooks").glob("*.py"))  # los hooks importan lib/
        + list((REPO / "scripts").glob("*.py"))
    )
    textos = {f: f.read_text(encoding="utf-8") for f in fuentes}
    for mod in sorted((REPO / "lib").glob("*.py")):
        nombre = mod.stem
        if nombre.startswith("_"):
            continue
        usado = any(
            re.search(rf"\b(import|from)\s+{re.escape(nombre)}\b", txt)
            for f, txt in textos.items() if f != mod
        )
        if not usado:
            huerfanos.append(nombre)
    return huerfanos


def _tests_ya_escritos() -> str:
    """El recuento que ya figura en el CLAUDE.md, si lo hay.

    Permite regenerar el resto del bloque (rama, HEAD, artefactos) sin
    degradar un recuento autoritativo previo a uno estático.
    """
    destino = REPO / "CLAUDE.md"
    if not destino.exists():
        return ""
    m = re.search(r"\| Tests \| ([^|]+?) \|", destino.read_text(encoding="utf-8"))
    valor = m.group(1).strip() if m else ""
    # Un recuento con fallos NO se preserva: quedaría congelado como "20
    # FALLANDO" aunque ya estén arreglados, que es peor que no decir nada.
    if "FALLANDO" in valor:
        return ""
    return valor if "pasando" in valor else ""


def build_block(*, run_tests: bool = False) -> str:
    tests = ""
    if run_tests:
        tests = count_tests_by_running()
    tests = tests or _tests_ya_escritos() or (
        f"{count_test_functions()} definidos "
        f"(estático; `refresh_state.py --run-tests` da el real)"
    )
    tools = count_tools()
    skills = count_skills()
    hooks_disco, hooks_reg = count_hooks()
    tablas = count_tables()
    head = _run(["git", "log", "-1", "--format=%h %s"])
    rama = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    sucio = bool(_run(["git", "status", "--porcelain"]))
    hoy = datetime.now().strftime("%Y-%m-%d %H:%M")

    lineas = [
        BEGIN,
        "",
        "## Estado verificado",
        "",
        f"> Generado por `scripts/refresh_state.py` el {hoy}. "
        "NO editar a mano: se sobreescribe. La narrativa va fuera de este bloque.",
        "",
        "| Métrica | Valor |",
        "|---|---|",
        f"| Tests | {tests} |",
        f"| Tools MCP | {tools} |",
        f"| Skills (`skills/`) | {skills} |",
        f"| Hooks | {hooks_disco} en disco, {hooks_reg} registrados en el proyecto |",
        f"| Tablas en `context.db` | {tablas} |",
        f"| Rama | `{rama}`{' (árbol sucio)' if sucio else ''} |",
        f"| HEAD | `{head}` |",
        "",
        "### Artefactos por sprint",
        "",
        "Señal mecánica: si el fichero existe, el trabajo se escribió. No dice",
        "si el sprint está *cerrado* — eso es juicio y vive en la narrativa.",
        "",
        "| Sprint | Artefactos | Detalle |",
        "|---|---|---|",
    ]
    for nombre, estado, detalle in sprint_rows():
        lineas.append(f"| {nombre} | {estado} | {detalle} |")

    huerfanos = orphan_modules()
    if huerfanos:
        lineas += [
            "",
            "### Módulos sin importadores",
            "",
            "Código escrito que nadie usa. Suele ser trabajo a medias, no",
            "necesariamente muerto: verificar antes de borrar o cablear.",
            "",
            "".join(f"- `lib/{m}.py`\n" for m in huerfanos).rstrip(),
        ]

    lineas += ["", END]
    return "\n".join(lineas)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="salir con código 1 si el bloque está desfasado")
    ap.add_argument("--print", dest="solo_imprimir", action="store_true",
                    help="imprimir el bloque generado y salir")
    ap.add_argument("--run-tests", action="store_true",
                    help="ejecutar la suite para el recuento autoritativo "
                         "(lento; no usar desde un test)")
    args = ap.parse_args()

    # --check compara contra lo escrito, que lleva el recuento real:
    # sin correr la suite siempre diría 'desfasado'.
    bloque = build_block(run_tests=args.run_tests or args.check)
    if args.solo_imprimir:
        print(bloque)
        return 0

    destino = REPO / "CLAUDE.md"
    texto = destino.read_text(encoding="utf-8")

    if BEGIN not in texto or END not in texto:
        print(
            f"ERROR: {destino.name} no tiene los marcadores {BEGIN} / {END}.\n"
            "Añádelos donde deba ir el bloque de estado.",
            file=sys.stderr,
        )
        return 2

    patron = re.compile(
        re.escape(BEGIN) + r".*?" + re.escape(END), re.DOTALL
    )
    nuevo = patron.sub(lambda _: bloque, texto)

    if args.check:
        if nuevo != texto:
            print("CLAUDE.md desfasado: corre scripts/refresh_state.py")
            return 1
        print("CLAUDE.md al día")
        return 0

    if nuevo == texto:
        print("CLAUDE.md ya estaba al día")
        return 0

    destino.write_text(nuevo, encoding="utf-8")
    print(f"CLAUDE.md actualizado ({destino})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
