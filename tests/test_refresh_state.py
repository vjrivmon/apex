"""Tests del generador de estado de CLAUDE.md y AGENTS.md.

Lo que se verifica es que los números salgan del repo real y que el script
respete la narrativa escrita a mano: si sobreescribiera texto fuera de los
marcadores, destruiría lo único del documento que no caduca.

Y, desde la auditoría del 2026-10-19, que el control de deriva CONVERGE: tras
generar, `--check` tiene que decir "al día" y salir con 0. Antes comparaba el
recuento real contra el número congelado en el fichero y por eso siempre
decía "desfasado".
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "refresh_state.py"
HOOK = REPO / ".claude" / "hooks" / "refresh-state.py"


def _load():
    spec = importlib.util.spec_from_file_location("refresh_state", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rs = _load()


# ── Utilidades para los tests de flujo ──

def _mini_repo(tmp_path: Path) -> Path:
    """Repo mínimo en un directorio temporal.

    Permite probar el ciclo generar -> `--check` sin tocar los ficheros
    reales del repo ni ejecutar la suite de pytest desde dentro de pytest.
    """
    repo = tmp_path / "repo"
    for d in ("lib", "mcp", "tests", "skills/demo", ".claude/hooks"):
        (repo / d).mkdir(parents=True, exist_ok=True)
    (repo / "lib" / "context_db.py").write_text(
        "CREATE TABLE IF NOT EXISTS uno (x INT);\n"
        "CREATE TABLE IF NOT EXISTS dos (x INT);\n",
        encoding="utf-8",
    )
    (repo / "mcp" / "apex_server.py").write_text(
        'Tool(name="apex_uno")\nTool(name="apex_dos")\n', encoding="utf-8"
    )
    (repo / "skills" / "demo" / "SKILL.md").write_text("demo\n", encoding="utf-8")
    (repo / "tests" / "test_algo.py").write_text(
        "def test_uno():\n    pass\n", encoding="utf-8"
    )
    (repo / ".claude" / "hooks" / "h1.py").write_text("# hook\n", encoding="utf-8")
    (repo / ".claude" / "settings.json").write_text(
        json.dumps({"hooks": {"Stop": [{"matcher": "", "hooks": [
            {"type": "command", "command": "python h1.py"}]}]}}),
        encoding="utf-8",
    )
    for nombre in ("CLAUDE.md", "AGENTS.md"):
        (repo / nombre).write_text(
            f"# Doc\n\n{rs.BEGIN}\nviejo y falso\n{rs.END}\n\n"
            "Narrativa que NO debe tocarse.\n",
            encoding="utf-8",
        )
    return repo


def _main(args: list[str], monkeypatch) -> int:
    monkeypatch.setattr(sys, "argv", ["refresh_state.py"] + args)
    return rs.main()


def _sin_suite():
    """Sustituto de `count_tests_by_running` que falla si se la llama."""
    def _boom():
        raise AssertionError("no se debe ejecutar la suite desde aquí")
    return _boom


# ── Conteos ──

def test_cuenta_tools_reales():
    """Debe coincidir con las Tool(name="apex_...") del servidor."""
    esperado = len(set(
        __import__("re").findall(
            r'name="(apex_[a-z_]+)"',
            (REPO / "mcp/apex_server.py").read_text(encoding="utf-8"),
        )
    ))
    assert rs.count_tools() == esperado
    assert rs.count_tools() > 50, "el servidor debería tener decenas de tools"


def test_cuenta_skills_reales():
    assert rs.count_skills() == len(list((REPO / "skills").glob("*/SKILL.md")))


def test_cuenta_tablas_reales():
    assert rs.count_tables() == len(set(
        __import__("re").findall(
            r"CREATE TABLE IF NOT EXISTS (\w+)",
            (REPO / "lib/context_db.py").read_text(encoding="utf-8"),
        )
    ))


def test_cuenta_hooks_en_disco_y_registrados():
    disco, registrados = rs.count_hooks()
    assert disco == len(list((REPO / ".claude/hooks").glob("*.py")))
    assert registrados > 0, "settings.json debería registrar hooks"
    assert registrados <= disco + 5  # los de ~/.claude también cuentan


def test_cuenta_hooks_globales_solo_los_de_apex(tmp_path, monkeypatch):
    """Los hooks globales que cuentan son los de ESTE repo.

    Un hook global de otra herramienta no es de APEX y no debe entrar en la
    cifra: si contara, el control de deriva fallaría en otra máquina.
    """
    repo = _mini_repo(tmp_path)
    global_json = tmp_path / "global.json"
    global_json.write_text(json.dumps({"hooks": {"Stop": [{"matcher": "", "hooks": [
        {"type": "command", "command": "python h1.py"},
        {"type": "command", "command": "python otro_que_no_es_de_apex.py"}]}]}}),
        encoding="utf-8")
    monkeypatch.setattr(rs, "REPO", repo)
    monkeypatch.setattr(rs, "GLOBAL_SETTINGS", global_json)
    assert rs.count_global_hooks() == 1


def test_tablas_de_la_bd_viva_son_distintas_del_schema(tmp_path, monkeypatch):
    """La BD viva incluye las tablas shadow de FTS5: no es el mismo número."""
    import sqlite3

    repo = _mini_repo(tmp_path)
    (repo / ".apex").mkdir(parents=True, exist_ok=True)
    bd = repo / ".apex" / "context.db"
    con = sqlite3.connect(bd)
    con.execute("CREATE TABLE real (x INT)")
    con.execute("CREATE TABLE auto (x INTEGER PRIMARY KEY AUTOINCREMENT)")
    con.commit()
    con.close()
    monkeypatch.setattr(rs, "REPO", repo)
    assert rs.count_tables() == 2          # schema
    assert rs.count_live_tables() == 3     # BD viva (incluye sqlite_sequence)


def test_sin_bd_viva_el_recuento_es_none(tmp_path, monkeypatch):
    repo = _mini_repo(tmp_path)
    monkeypatch.setattr(rs, "REPO", repo)
    assert rs.count_live_tables() is None


def test_detecta_biblioteca_como_presente():
    """Los sprints se marcan por presencia de artefactos, no por texto."""
    filas = dict((n, e) for n, e, _ in rs.sprint_rows())
    assert filas["Biblioteca de libros"] == "presente"
    assert filas["S17 VirtualFS"] == "presente"


def test_detecta_sprint_ausente():
    filas = dict((n, e) for n, e, _ in rs.sprint_rows())
    assert filas["S18 Granite curator"] == "ausente"


def test_modulos_huerfanos_no_incluye_los_cableados():
    """book_corpus se importa desde el servidor: no puede salir como huérfano."""
    huerfanos = rs.orphan_modules()
    assert "book_corpus" not in huerfanos
    assert "book_chunker" not in huerfanos  # lo importa book_corpus
    assert "embeddings" not in huerfanos    # lo importa book_corpus


def test_vfs_grep_sale_como_huerfano():
    """Deuda real conocida: escrito, con tests, y sin cablear."""
    assert "vfs_grep" in rs.orphan_modules()


# ── Bloque generado ──

def test_bloque_lleva_marcadores_y_datos():
    bloque = rs.build_block()
    assert bloque.startswith(rs.BEGIN)
    assert bloque.rstrip().endswith(rs.END)
    assert "Tools MCP" in bloque and "Tests" in bloque
    assert "NO editar a mano" in bloque


def test_bloque_sin_emojis():
    bloque = rs.build_block()
    assert not any(ord(c) > 0x2500 for c in bloque), "el proyecto prohíbe emojis"


def test_bloque_reporta_los_tres_recuentos_de_hooks():
    """El bloque tenía 8 fijos; ahora dice los tres números reales."""
    bloque = rs.build_block()
    disco, proyecto = rs.count_hooks()
    assert f"| Hooks en disco | {disco} |" in bloque
    assert f"| Hooks registrados en el proyecto | {proyecto} |" in bloque
    assert ("| Hooks registrados globalmente "
            f"(`~/.claude/settings.json`) | {rs.count_global_hooks()} |") in bloque


def test_bloque_distingue_schema_de_bd_viva():
    """La etiqueta anterior ('Tablas en context.db') no correspondía a lo
    que se medía: ahora se dice qué se cuenta en cada fila."""
    bloque = rs.build_block()
    assert f"| Tablas en el schema (`lib/context_db.py`) | {rs.count_tables()} |" in bloque
    assert "| Tablas en la BD viva (`.apex/context.db`) |" in bloque


# ── Escritura ──

def test_no_toca_la_narrativa(tmp_path, monkeypatch):
    """El texto fuera de los marcadores debe sobrevivir intacto."""
    fake = tmp_path / "CLAUDE.md"
    fake.write_text(
        "# Encabezado propio\n\nNarrativa que NO debe tocarse.\n\n"
        f"{rs.BEGIN}\nviejo y falso\n{rs.END}\n\n"
        "## Decisiones\n\nMás narrativa al final.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(rs, "REPO", REPO)
    monkeypatch.setattr(rs, "__file__", str(SCRIPT))

    texto = fake.read_text(encoding="utf-8")
    import re
    nuevo = re.sub(
        re.escape(rs.BEGIN) + r".*?" + re.escape(rs.END),
        lambda _: rs.build_block(),
        texto,
        flags=re.DOTALL,
    )
    fake.write_text(nuevo, encoding="utf-8")

    final = fake.read_text(encoding="utf-8")
    assert "# Encabezado propio" in final
    assert "Narrativa que NO debe tocarse." in final
    assert "Más narrativa al final." in final
    assert "viejo y falso" not in final
    assert "Tools MCP" in final


def test_el_script_actualiza_tanto_claude_como_agents(tmp_path, monkeypatch):
    """AGENTS.md dice 'Generado por refresh_state.py': ahora es verdad."""
    repo = _mini_repo(tmp_path)
    monkeypatch.setattr(rs, "REPO", repo)
    assert _main([], monkeypatch) == 0
    for nombre in ("CLAUDE.md", "AGENTS.md"):
        texto = (repo / nombre).read_text(encoding="utf-8")
        assert rs.BEGIN in texto and rs.END in texto
        assert "Tools MCP" in texto
        # la narrativa de fuera sigue intacta
        assert "Narrativa que NO debe tocarse." in texto


def test_target_limita_los_ficheros_a_actualizar(tmp_path, monkeypatch):
    repo = _mini_repo(tmp_path)
    monkeypatch.setattr(rs, "REPO", repo)
    assert _main(["--target", "CLAUDE.md"], monkeypatch) == 0
    assert "Tools MCP" in (repo / "CLAUDE.md").read_text(encoding="utf-8")
    assert "Tools MCP" not in (repo / "AGENTS.md").read_text(encoding="utf-8")


# ── Convergencia del control de deriva (regresión del 2026-10-19) ──

def test_check_despues_de_generar_dice_al_dia(tmp_path, monkeypatch, capsys):
    """El invariante: generar y luego comprobar tiene que converger.

    Antes `--check` ejecutaba la suite y comparaba el recuento real contra
    el número congelado en el fichero, así que siempre decía "desfasado".
    """
    repo = _mini_repo(tmp_path)
    monkeypatch.setattr(rs, "REPO", repo)
    monkeypatch.setattr(rs, "count_tests_by_running", _sin_suite())

    assert _main([], monkeypatch) == 0
    capsys.readouterr()

    assert _main(["--check"], monkeypatch) == 0
    salida = capsys.readouterr().out
    assert "al día" in salida
    assert "desfasado" not in salida


def test_check_no_ejecuta_la_suite(tmp_path, monkeypatch, capsys):
    """`--check` no puede lanzar pytest: se usaría desde dentro de pytest."""
    repo = _mini_repo(tmp_path)
    monkeypatch.setattr(rs, "REPO", repo)
    monkeypatch.setattr(rs, "count_tests_by_running", _sin_suite())
    _main([], monkeypatch)
    capsys.readouterr()
    assert _main(["--check"], monkeypatch) == 0


def test_check_detecta_un_cambio_real(tmp_path, monkeypatch, capsys):
    """Si el repo cambia y el documento no, `--check` tiene que fallar."""
    repo = _mini_repo(tmp_path)
    monkeypatch.setattr(rs, "REPO", repo)
    monkeypatch.setattr(rs, "count_tests_by_running", _sin_suite())
    _main([], monkeypatch)
    capsys.readouterr()

    (repo / "tests" / "test_algo.py").write_text(
        "def test_uno():\n    pass\n\ndef test_dos():\n    pass\n",
        encoding="utf-8",
    )
    assert _main(["--check"], monkeypatch) == 1
    err = capsys.readouterr().err
    assert "desfasado" in err.lower()
    assert "Tests (funciones de test)" in err


def test_el_camino_normal_no_reescribe_por_un_cambio_de_rama(
    tmp_path, monkeypatch, capsys
):
    """La rama y el HEAD cambian en cada commit: no deben ensuciar el árbol.

    Si lo único que cambia es el contexto volátil, el script no toca el
    fichero.
    """
    repo = _mini_repo(tmp_path)
    monkeypatch.setattr(rs, "REPO", repo)
    monkeypatch.setattr(rs, "count_tests_by_running", _sin_suite())
    _main([], monkeypatch)
    capsys.readouterr()

    destino = repo / "CLAUDE.md"
    antes = destino.read_text(encoding="utf-8")
    destino.write_text(
        antes.replace("HEAD `", "HEAD `rama-que-no-existe "), encoding="utf-8"
    )
    despues = destino.read_text(encoding="utf-8")

    assert _main([], monkeypatch) == 0
    assert destino.read_text(encoding="utf-8") == despues, (
        "el cambio de HEAD no debe reescribir el fichero"
    )


def test_la_instantanea_de_tests_se_conserva_y_se_refresca_a_peticion(
    tmp_path, monkeypatch
):
    """El camino normal conserva la instantánea; `--run-tests` la recalcula."""
    repo = _mini_repo(tmp_path)
    monkeypatch.setattr(rs, "REPO", repo)
    monkeypatch.setattr(rs, "count_tests_by_running", lambda: "42 pasando, 1 omitidos")

    bloque = rs.build_block(run_tests=True)
    fila = rs.parse_facts(bloque)["metricas"][rs.ETIQUETA_SNAPSHOT]
    assert "42 pasando, 1 omitidos (snapshot " in fila
    instantanea = rs.parse_snapshot(fila)
    assert instantanea is not None
    assert instantanea["fecha"]
    assert instantanea["funciones"] == rs.count_test_functions()

    # El camino normal la conserva tal cual, sin tocar el número.
    conservado = rs.build_block(instantanea)
    assert rs.parse_facts(conservado)["metricas"][rs.ETIQUETA_SNAPSHOT] == fila


def test_una_instantanea_vieja_avisa_pero_no_hace_fallar_el_check(
    tmp_path, monkeypatch, capsys
):
    """Si los tests cambiaron desde la instantánea, se avisa; el check pasa.

    El aviso va a stderr y no cambia el código de salida: comparar el
    recuento real contra el congelado era lo que rompía el control.
    """
    repo = _mini_repo(tmp_path)
    monkeypatch.setattr(rs, "REPO", repo)
    monkeypatch.setattr(rs, "count_tests_by_running", lambda: "42 pasando")

    _main(["--run-tests"], monkeypatch)
    capsys.readouterr()

    # Cambian los tests: el recuento estático se desfasó.
    (repo / "tests" / "test_algo.py").write_text(
        "def test_uno():\n    pass\n\ndef test_dos():\n    pass\n",
        encoding="utf-8",
    )
    assert _main(["--check"], monkeypatch) == 1
    capsys.readouterr()

    # El camino normal actualiza el estático y conserva la instantánea vieja.
    assert _main([], monkeypatch) == 0
    capsys.readouterr()

    assert _main(["--check"], monkeypatch) == 0
    err = capsys.readouterr().err
    assert "AVISO" in err
    assert "snapshot" in err


# ── Los ficheros reales ──

def test_claude_md_refleja_los_conteos_actuales():
    """Si esto falla, el CLAUDE.md se quedó desfasado.

    Compara los números escritos contra los reales SIN invocar `--check`, que
    ejecutaría la suite entera dentro de este test (pytest anidado).
    """
    texto = (REPO / "CLAUDE.md").read_text(encoding="utf-8")
    bloque = texto.split(rs.BEGIN)[1].split(rs.END)[0]

    assert f"| Tools MCP | {rs.count_tools()} |" in bloque, (
        "recuento de tools desfasado; corre scripts/refresh_state.py"
    )
    assert f"| Skills (`skills/`) | {rs.count_skills()} |" in bloque
    assert (f"| Tablas en el schema (`lib/context_db.py`) | "
            f"{rs.count_tables()} |") in bloque
    assert f"| Tests (funciones de test) | {rs.count_test_functions()} |" in bloque


def test_agents_md_refleja_los_conteos_actuales():
    """AGENTS.md llevaba una copia a mano: 721 tests, 27 tablas, 12 hooks."""
    texto = (REPO / "AGENTS.md").read_text(encoding="utf-8")
    bloque = texto.split(rs.BEGIN)[1].split(rs.END)[0]

    assert f"| Tools MCP | {rs.count_tools()} |" in bloque
    assert f"| Skills (`skills/`) | {rs.count_skills()} |" in bloque
    assert (f"| Tablas en el schema (`lib/context_db.py`) | "
            f"{rs.count_tables()} |") in bloque
    assert f"| Tests (funciones de test) | {rs.count_test_functions()} |" in bloque


def test_claude_y_agents_tienen_el_mismo_bloque():
    """Los dos ficheros se generan en la misma pasada: van en paralelo."""
    def bloque_de(nombre):
        texto = (REPO / nombre).read_text(encoding="utf-8")
        return texto.split(rs.BEGIN)[1].split(rs.END)[0]

    a, b = bloque_de("CLAUDE.md"), bloque_de("AGENTS.md")
    # Solo puede diferir el contexto volátil (rama, HEAD, fecha de refresco).
    assert rs.parse_facts(a)["metricas"] == rs.parse_facts(b)["metricas"]
    assert rs.parse_facts(a)["sprints"] == rs.parse_facts(b)["sprints"]
    assert rs.parse_facts(a)["huerfanos"] == rs.parse_facts(b)["huerfanos"]


def test_count_test_functions_no_ejecuta_pytest():
    """El recuento estático debe ser inmediato: lo usan tests y hooks."""
    import time

    t0 = time.monotonic()
    n = rs.count_test_functions()
    assert time.monotonic() - t0 < 5.0, "no debe ejecutar la suite"
    assert n > 600, f"esperaba cientos de tests, conté {n}"


def test_claude_md_tiene_los_marcadores():
    texto = (REPO / "CLAUDE.md").read_text(encoding="utf-8")
    assert rs.BEGIN in texto and rs.END in texto


def test_agents_md_tiene_los_marcadores():
    texto = (REPO / "AGENTS.md").read_text(encoding="utf-8")
    assert rs.BEGIN in texto and rs.END in texto


# ── Hook ──

@pytest.mark.parametrize("payload", [
    '{"hook_event_name":"Stop","cwd":"/tmp"}',
    '{"hook_event_name":"PostToolUse","cwd":"/tmp"}',
    "esto no es json",
    "",
])
def test_hook_nunca_bloquea(payload):
    """Regenerar documentación no puede tumbar el flujo de trabajo."""
    proc = subprocess.run(
        [sys.executable, str(HOOK)],
        input=payload, capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0


def test_hook_registrado_en_settings():
    settings = json.loads(
        (REPO / ".claude/settings.json").read_text(encoding="utf-8")
    )
    eventos = set()
    for evento, entradas in settings["hooks"].items():
        for entrada in entradas:
            for h in entrada.get("hooks", []):
                if "refresh-state.py" in h.get("command", ""):
                    eventos.add(evento)
    assert eventos == {"PostToolUse", "Stop"}


def test_hook_de_fase_usa_matcher_especifico():
    """No debe correr en CADA tool: solo al cambiar de fase."""
    settings = json.loads(
        (REPO / ".claude/settings.json").read_text(encoding="utf-8")
    )
    for entrada in settings["hooks"]["PostToolUse"]:
        if any("refresh-state.py" in h.get("command", "")
               for h in entrada.get("hooks", [])):
            assert entrada.get("matcher") == "mcp__apex__apex_set_phase"
