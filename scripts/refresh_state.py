#!/usr/bin/env python3
"""Regenera el bloque de HECHOS de CLAUDE.md y AGENTS.md contando el repo real.

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

Todo lo demás (la narrativa de decisiones, que es lo único que no envejece mal)
se respeta intacto.

Uso:
    python scripts/refresh_state.py            # reescribe CLAUDE.md y AGENTS.md
    python scripts/refresh_state.py --check    # solo dice si está desfasado
    python scripts/refresh_state.py --print    # imprime el bloque y sale
    python scripts/refresh_state.py --run-tests  # refresca el recuento de suite

Diseño del control de deriva (auditoría 2026-10-19):

El bloque mezcla tres clases de dato y cada una se compara de forma distinta:

  1. HECHOS DEL REPO (tests, tools, skills, hooks en disco y del proyecto,
     tablas del schema, artefactos por sprint, módulos huérfanos). Se comparan
     con exactitud: si cambian y el fichero no se regenera, `--check` falla.
  2. HECHOS DE ENTORNO (hooks registrados en `~/.claude/settings.json`, tablas
     de la BD viva `.apex/context.db`). Dependen de la máquina, no del repo:
     se REPORTAN pero no cuentan como deriva, porque de lo contrario el
     control fallaría en cualquier otra máquina (falso positivo).
  3. CONTEXTO VOLÁTIL (rama, HEAD, árbol sucio, fecha del refresco). Cambia
     en cada commit. No se compara y NO fuerza reescritura: si lo único que
     cambia es la rama, el script no toca el fichero y el árbol no se ensucia.

El recuento de tests es el caso más delicado: la suite real tarda ~20 s y no
se puede ejecutar desde dentro de pytest (pytest anidado). Por eso el bloque
guarda una INSTANTÁNEA con la fecha en que se calculó:

    | Tests (suite ejecutada) | 860 pasando, 4 omitidos (snapshot 2026-10-19) |

El camino normal conserva esa instantánea tal cual; `--run-tests` la recalcula
contra la suite real. `--check` NO compara la instantánea contra la realidad
(comparar real contra congelado es lo que hacía que el control nunca
converjera): solo avisa si la instantánea se quedó vieja respecto al número
estático de funciones de test.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BEGIN = "<!-- APEX:STATE:BEGIN -->"
END = "<!-- APEX:STATE:END -->"

# Los settings globales del usuario: fuente de los hooks de APEX registrados
# fuera del proyecto. Es un global para que los tests puedan sustituirlo.
GLOBAL_SETTINGS = Path.home() / ".claude" / "settings.json"

# Destinos por defecto: los dos ficheros que llevan el bloque de estado.
DESTINOS_POR_DEFECTO = ("CLAUDE.md", "AGENTS.md")

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

# Métricas del bloque. `comparable` indica si el valor cuenta como DERIVA:
#   True  -> se compara con exactitud; un cambio es deriva real del repo.
#   False -> se reporta pero no se compara (hecho de entorno o instantánea
#            que solo cambia cuando se pide explícitamente).
METRICAS: list[tuple[str, bool]] = [
    ("Tests (funciones de test)", True),
    ("Tests (suite ejecutada)", False),
    ("Tools MCP", True),
    ("Skills (`skills/`)", True),
    ("Hooks en disco", True),
    ("Hooks registrados en el proyecto", True),
    ("Hooks registrados globalmente (`~/.claude/settings.json`)", False),
    ("Tablas en el schema (`lib/context_db.py`)", True),
    ("Tablas en la BD viva (`.apex/context.db`)", False),
]

ETIQUETA_SNAPSHOT = "Tests (suite ejecutada)"
SIN_SNAPSHOT = "sin snapshot: corre `scripts/refresh_state.py --run-tests`"

TITULO_METRICAS = "## Estado verificado"
TITULO_VOLATIL = "### Contexto del repo (volátil)"


def _run(cmd: list[str], cwd: Path | None = None) -> str:
    try:
        return subprocess.run(
            cmd, cwd=cwd or REPO, capture_output=True, text=True, timeout=600
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
    """Ejecuta la suite para obtener el recuento real. Lento (~20 s)."""
    out = _run([str(REPO / ".venv/bin/pytest"), "tests/", "-q", "--no-header"])
    m = re.search(r"(\d+) passed", out)
    if not m:
        return ""
    partes = [f"{m.group(1)} pasando"]
    fallos = re.search(r"(\d+) failed", out)
    if fallos:
        partes.append(f"{fallos.group(1)} FALLANDO")
    omitidos = re.search(r"(\d+) skipped", out)
    if omitidos:
        partes.append(f"{omitidos.group(1)} omitidos")
    return ", ".join(partes)


def count_tools() -> int:
    src = (REPO / "mcp/apex_server.py").read_text(encoding="utf-8")
    return len(set(re.findall(r'name="(apex_[a-z_]+)"', src)))


def count_skills() -> int:
    return len(list((REPO / "skills").glob("*/SKILL.md")))


def _scripts_registrados(settings: Path) -> set[str]:
    """Nombres de script referenciados en un settings.json de hooks."""
    if not settings.exists():
        return set()
    try:
        data = json.loads(settings.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return set()
    vistos: set[str] = set()
    for entradas in (data.get("hooks") or {}).values():
        for entrada in entradas:
            for h in entrada.get("hooks", []):
                cmd = h.get("command", "")
                m = re.search(r"([\w.-]+\.py)", cmd)
                if m:
                    vistos.add(m.group(1))
    return vistos


def count_hooks() -> tuple[int, int]:
    """(ficheros en disco, registrados en settings.json del proyecto)."""
    ficheros = len(list((REPO / ".claude/hooks").glob("*.py")))
    registrados = len(_scripts_registrados(REPO / ".claude/settings.json"))
    return ficheros, registrados


def count_global_hooks() -> int:
    """Hooks de APEX registrados en `~/.claude/settings.json`.

    Se cuentan SOLO los que son de este repo: un hook global cuyo script
    existe en `.claude/hooks/` de APEX. Los hooks globales de otras
    herramientas no son de este proyecto y no cuentan.
    """
    disco = {f.name for f in (REPO / ".claude/hooks").glob("*.py")}
    globales = _scripts_registrados(GLOBAL_SETTINGS)
    return len(globales & disco)


def count_tables() -> int:
    """Tablas definidas en el schema de `lib/context_db.py`."""
    src = (REPO / "lib/context_db.py").read_text(encoding="utf-8")
    return len(set(re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", src)))


def _bd_viva() -> Path | None:
    """Ruta de la BD contextual viva de este proyecto, o None si no hay.

    En un checkout normal es `.apex/context.db`. En un worktree ese
    directorio no existe (está en .gitignore): se recurre al checkout
    principal del mismo repo, que es donde vive la BD del proyecto. Así el
    número es el del proyecto y no el del checkout de turno.
    """
    local = REPO / ".apex" / "context.db"
    if local.exists():
        return local
    comun = _run(["git", "rev-parse", "--git-common-dir"])
    if not comun:
        return None
    ruta = Path(comun)
    if not ruta.is_absolute():
        ruta = (REPO / ruta).resolve()
    principal = ruta.parent / ".apex" / "context.db"
    return principal if principal.exists() else None


def count_live_tables() -> int | None:
    """Tablas reales de la BD viva `.apex/context.db`, o None si no existe.

    Incluye las tablas shadow de FTS5 y `sqlite_sequence`, que no aparecen
    en el schema: por eso el bloque reporta los dos recuentos.
    """
    import sqlite3

    bd = _bd_viva()
    if bd is None:
        return None

    # Primero en solo lectura: contar tablas no debe tocar la BD. Si el modo
    # read-only falla (WAL sin -shm, por ejemplo), se reintenta normal.
    errores = []
    for uri in (f"file:{bd}?mode=ro", str(bd)):
        try:
            con = sqlite3.connect(uri, uri=uri.startswith("file:"))
            try:
                n = con.execute(
                    "SELECT count(*) FROM sqlite_master WHERE type='table'"
                ).fetchone()[0]
            finally:
                con.close()
            return int(n)
        except Exception as exc:  # noqa: BLE001 - la BD puede estar corrupta
            errores.append(f"{uri}: {exc}")
    print(f"[refresh-state] no se pudo leer {bd}: {'; '.join(errores)}",
          file=sys.stderr)
    return None


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


# ── Instantánea del recuento de tests ──

_RE_SNAPSHOT = re.compile(
    r"^(?P<resumen>.*?) \(snapshot (?P<fecha>\d{4}-\d{2}-\d{2})"
    r"(?:, (?P<funciones>\d+) funciones de test)?\)$"
)


def parse_snapshot(valor: str) -> dict | None:
    """Interpreta el valor de la fila de la suite ejecutada.

    Devuelve None si el valor no tiene el formato esperado (por ejemplo si
    alguien lo editó a mano): en ese caso se conserva tal cual, pero no hay
    fecha con la que juzgar si la instantánea está vieja.
    """
    valor = (valor or "").strip()
    m = _RE_SNAPSHOT.match(valor)
    if not m:
        return None
    funciones = m.group("funciones")
    return {
        "valor": valor,
        "resumen": m.group("resumen"),
        "fecha": m.group("fecha"),
        "funciones": int(funciones) if funciones is not None else None,
    }


def formatea_snapshot(resumen: str, fecha: str, funciones: int) -> str:
    return f"{resumen} (snapshot {fecha}, {funciones} funciones de test)"


# ── Lectura y comparación de bloques ──

def extract_block(texto: str) -> str | None:
    """Devuelve el bloque generado que hay en un fichero, o None."""
    m = re.search(
        re.escape(BEGIN) + r".*?" + re.escape(END), texto, re.DOTALL
    )
    return m.group(0) if m else None


def parse_facts(bloque: str) -> dict:
    """Descompone un bloque generado en sus hechos comparables."""
    metricas: dict[str, str] = {}
    m = re.search(r"^\| Métrica \| Valor \|[ \t]*\n((?:^\|.*\|[ \t]*$\n?)+)",
                  bloque, re.M)
    if m:
        for linea in m.group(1).splitlines():
            mm = re.match(r"^\| (.+?) \| (.*?) \|$", linea)
            if mm:
                metricas[mm.group(1)] = mm.group(2)

    sprints: list[str] = []
    m = re.search(
        r"\| Sprint \| Artefactos \| Detalle \|[ \t]*\n((?:^\|.*\|[ \t]*$\n?)+)",
        bloque, re.M,
    )
    if m:
        sprints = [ln.strip() for ln in m.group(1).splitlines() if ln.strip()]

    huerfanos: list[str] = []
    m = re.search(r"### Módulos sin importadores\n(.*?)(?:\n### |\n<!--|\Z)",
                  bloque, re.S)
    if m:
        huerfanos = [ln.strip() for ln in m.group(1).splitlines()
                     if ln.strip().startswith("- `lib/")]

    return {"metricas": metricas, "sprints": sprints, "huerfanos": huerfanos}


def compare_facts(nuevo: dict, viejo: dict) -> tuple[list[str], list[str]]:
    """Compara dos bloques ya parseados.

    Devuelve (deriva, entorno):
      - deriva: hechos del repo que han cambiado. Hacen fallar `--check`.
      - entorno: hechos dependientes de la máquina (hooks globales, tablas de
        la BD viva) o la instantánea de la suite. Se reportan, pero no son
        deriva: dependen de la máquina o solo cambian a petición explícita.
    """
    deriva: list[str] = []
    entorno: list[str] = []

    comparables = {etiqueta for etiqueta, comp in METRICAS if comp}
    conocidas = {etiqueta for etiqueta, _ in METRICAS}

    etiquetas = list(dict.fromkeys(
        list(nuevo["metricas"]) + list(viejo["metricas"])
    ))
    for etiqueta in etiquetas:
        v_nuevo = nuevo["metricas"].get(etiqueta)
        v_viejo = viejo["metricas"].get(etiqueta)
        if v_nuevo == v_viejo:
            continue
        if etiqueta not in conocidas:
            # El bloque está en un formato viejo: la métrica existe en el
            # fichero pero no en el catálogo actual. Es deriva: hay que
            # regenerar, no ignorar en silencio.
            deriva.append(f"métrica desconocida en el bloque: {etiqueta}")
        elif etiqueta in comparables:
            deriva.append(f"{etiqueta}: {v_viejo!r} -> {v_nuevo!r}")
        else:
            entorno.append(f"{etiqueta}: {v_viejo!r} -> {v_nuevo!r}")

    for etiqueta, _ in METRICAS:
        if etiqueta not in viejo["metricas"]:
            deriva.append(f"falta la métrica: {etiqueta}")

    if nuevo["sprints"] != viejo["sprints"]:
        deriva.append("artefactos por sprint: la tabla ha cambiado")
    if nuevo["huerfanos"] != viejo["huerfanos"]:
        deriva.append("módulos sin importadores: la lista ha cambiado")

    return deriva, entorno


# ── Construcción del bloque ──

def _snapshot_mas_reciente(candidatos: list[dict | None]) -> dict | None:
    """Elige la instantánea válida más reciente entre varios ficheros."""
    validos = [c for c in candidatos if c]
    if not validos:
        return None
    distintos = {c["valor"] for c in validos}
    if len(distintos) > 1:
        print(
            "[refresh-state] los ficheros destino no comparten la misma "
            f"instantánea de tests ({sorted(distintos)}); se usa la más "
            "reciente y se sincronizan",
            file=sys.stderr,
        )
    return max(validos, key=lambda c: c["fecha"])


def build_block(snapshot: dict | None = None, *, run_tests: bool = False) -> str:
    """Construye el bloque de estado.

    `snapshot` es la instantánea previa del recuento de suite (se conserva
    tal cual). Con `run_tests=True` se recalcula contra la suite real.
    """
    funciones = count_test_functions()

    if run_tests:
        resumen = count_tests_by_running()
        if not resumen:
            raise RuntimeError(
                "no se pudo ejecutar la suite para el recuento autoritativo"
            )
        snapshot = {
            "valor": formatea_snapshot(resumen, _hoy(), funciones),
            "resumen": resumen,
            "fecha": _hoy(),
            "funciones": funciones,
        }

    fila_suite = snapshot["valor"] if snapshot else SIN_SNAPSHOT

    hooks_disco, hooks_proyecto = count_hooks()
    tablas_vivas = count_live_tables()

    metricas = {
        "Tests (funciones de test)": str(funciones),
        ETIQUETA_SNAPSHOT: fila_suite,
        "Tools MCP": str(count_tools()),
        "Skills (`skills/`)": str(count_skills()),
        "Hooks en disco": str(hooks_disco),
        "Hooks registrados en el proyecto": str(hooks_proyecto),
        "Hooks registrados globalmente (`~/.claude/settings.json`)":
            str(count_global_hooks()),
        "Tablas en el schema (`lib/context_db.py`)": str(count_tables()),
        "Tablas en la BD viva (`.apex/context.db`)": (
            str(tablas_vivas) if tablas_vivas is not None
            else "no disponible (sin BD viva en este directorio)"
        ),
    }

    head = _run(["git", "log", "-1", "--format=%h %s"])
    rama = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    sucio = bool(_run(["git", "status", "--porcelain"]))
    contexto = (
        f"Rama `{rama}`{' (árbol sucio)' if sucio else ''} · "
        f"HEAD `{head}` · refrescado el {_hoy()}."
    )

    return render_block(metricas, sprint_rows(), orphan_modules(), contexto)


def _hoy() -> str:
    """Solo la fecha, no la hora: un timestamp al minuto ensuciaba el árbol."""
    return datetime.now().strftime("%Y-%m-%d")


def render_block(metricas: dict[str, str], sprints: list[tuple[str, str, str]],
                 huerfanos: list[str], contexto: str) -> str:
    lineas = [
        BEGIN,
        "",
        TITULO_METRICAS,
        "",
        "> Generado por `scripts/refresh_state.py` contando el repo.",
        "> NO editar a mano: se sobreescribe. La narrativa va fuera de este",
        "> bloque. Las filas de hooks globales y de la BD viva dependen de la",
        "> máquina: se reportan, pero `--check` no las cuenta como deriva. La",
        "> sección de contexto es volátil y tampoco fuerza reescritura.",
        "",
        "| Métrica | Valor |",
        "|---|---|",
    ]
    for etiqueta, _comp in METRICAS:
        lineas.append(f"| {etiqueta} | {metricas[etiqueta]} |")

    lineas += [
        "",
        "### Artefactos por sprint",
        "",
        "Señal mecánica: si el fichero existe, el trabajo se escribió. No dice",
        "si el sprint está *cerrado* — eso es juicio y vive en la narrativa.",
        "",
        "| Sprint | Artefactos | Detalle |",
        "|---|---|---|",
    ]
    for nombre, estado, detalle in sprints:
        lineas.append(f"| {nombre} | {estado} | {detalle} |")

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

    lineas += ["", TITULO_VOLATIL, "", contexto, "", END]
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
    ap.add_argument("--target", default="all",
                    choices=("all",) + DESTINOS_POR_DEFECTO,
                    help="fichero a actualizar; por defecto, todos los que "
                         "llevan el bloque de estado")
    args = ap.parse_args()

    nombres = (list(DESTINOS_POR_DEFECTO) if args.target == "all"
               else [args.target])
    destinos = [REPO / n for n in nombres]

    # 1. Leer los bloques previos: de ahí sale la instantánea de la suite.
    previos: dict[Path, str] = {}
    for destino in destinos:
        if not destino.exists():
            print(f"ERROR: {destino.name} no existe", file=sys.stderr)
            return 2
        texto = destino.read_text(encoding="utf-8")
        bloque = extract_block(texto)
        if bloque is None:
            print(
                f"ERROR: {destino.name} no tiene los marcadores {BEGIN} / "
                f"{END}.\nAñádelos donde deba ir el bloque de estado.",
                file=sys.stderr,
            )
            return 2
        previos[destino] = bloque

    snapshot = _snapshot_mas_reciente([
        parse_snapshot(
            parse_facts(bloque)["metricas"].get(ETIQUETA_SNAPSHOT, "")
        )
        for bloque in previos.values()
    ])

    # 2. Calcular los hechos.
    try:
        bloque_nuevo = build_block(snapshot, run_tests=args.run_tests)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.solo_imprimir:
        print(bloque_nuevo)
        return 0

    hechos_nuevos = parse_facts(bloque_nuevo)

    # 3. Comparar y, si procede, escribir.
    deriva_detectada: list[str] = []
    cambios_entorno: list[str] = []
    por_destino: dict[Path, tuple[list[str], list[str]]] = {}
    for destino, bloque_viejo in previos.items():
        hechos_viejos = parse_facts(bloque_viejo)
        d, e = compare_facts(hechos_nuevos, hechos_viejos)
        por_destino[destino] = (d, e)
        for item in d:
            deriva_detectada.append(f"{destino.name}: {item}")
        for item in e:
            cambios_entorno.append(f"{destino.name}: {item}")

    # La instantánea puede estar vieja: no es deriva (no se puede comparar
    # con la realidad sin correr la suite), pero se avisa.
    if snapshot and snapshot.get("funciones") is not None:
        actuales = count_test_functions()
        if snapshot["funciones"] != actuales:
            print(
                f"[refresh-state] AVISO: el snapshot del recuento de suite es "
                f"del {snapshot['fecha']} ({snapshot['funciones']} funciones de "
                f"test) y ahora hay {actuales}: refresca con "
                "`refresh_state.py --run-tests`",
                file=sys.stderr,
            )

    if args.check:
        if deriva_detectada:
            print("Estado desfasado:", file=sys.stderr)
            for item in deriva_detectada:
                print(f"  - {item}", file=sys.stderr)
            print("Corre: python scripts/refresh_state.py", file=sys.stderr)
            return 1
        for destino in destinos:
            print(f"{destino.name} al día")
        for item in cambios_entorno:
            print(f"[refresh-state] nota de entorno: {item}")
        return 0

    if not deriva_detectada and not cambios_entorno:
        print("Los bloques ya estaban al día")
        return 0

    actualizados = []
    for destino, bloque_viejo in previos.items():
        d, e = por_destino[destino]
        if not d and not e:
            continue
        texto = destino.read_text(encoding="utf-8")
        patron = re.compile(
            re.escape(BEGIN) + r".*?" + re.escape(END), re.DOTALL
        )
        nuevo_texto = patron.sub(lambda _: bloque_nuevo, texto)
        if nuevo_texto == texto:
            continue
        destino.write_text(nuevo_texto, encoding="utf-8")
        actualizados.append(destino.name)

    if not actualizados:
        print("Los bloques ya estaban al día")
    else:
        print(f"actualizados: {', '.join(actualizados)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
