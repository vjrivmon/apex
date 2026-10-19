"""LLM-Wiki Scaffold — Crea la estructura de knowledge base por proyecto.

Combina dos patrones:

**Karpathy LLM-Wiki** (en `.apex/wiki/`):
- SCHEMA.md: convenciones y estructura
- index.md: catálogo de contenido (navegación)
- log.md: registro cronológico de acciones (append-only)
- entities/, concepts/, comparisons/, queries/, raw/, synthesis/

**Segundo cerebro Thomas Frank** (en `.apex/`):
- brand/: identity, design-system, strategy, performance (lo que Thomas escribe
  manualmente y el agente lee como fuente autoritativa)
- raw/: research, socratic, papers, decisions-log (fuentes brutas inmutables
  que el pipeline ingest.py convierte en páginas wiki)
- releases/: drafts, staging, published (pipeline de entrega del proyecto)

La separación es deliberada:
- `.apex/wiki/raw/` = referencias inmutables de la KB Karpathy (papers ya
  compilados como fuente)
- `.apex/raw/` = material bruto del proyecto antes de sintetizar (lo que
  Thomas mete "a la cinta" y el ingest pipeline procesa)
"""
from __future__ import annotations

import re
from pathlib import Path
from datetime import datetime, timezone


# --- Contención de rutas (capa L1) ---
#
# Un slug de wiki NO es una ruta: es el identificador de una página. Antes de
# tocar disco se valida contra una regex cerrada y se comprueba que la ruta
# RESUELTA (symlinks incluidos) sigue dentro de `.apex/wiki/`. Sin esto, un
# slug con `..` escribía fuera del proyecto (F1-03).

# Secciones canónicas del wiki, según SCHEMA.md.
WIKI_SECTIONS = ("entities", "concepts", "comparisons", "queries", "raw", "synthesis")

MAX_SLUG_LEN = 128
MAX_SLUG_SEGMENT_LEN = 64

# Caracteres de control (incluye el NUL) y barra invertida: nunca validos.
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_SEGMENT_RE = re.compile(r"^[\w.-]+$", re.UNICODE)


class WikiPathError(ValueError):
    """Slug o ruta de wiki que se sale del proyecto.

    El mensaje dice siempre QUÉ se esperaba, para que el caller pueda
    corregir la llamada sin leer el código.
    """


def _normalize_segment(segment: str) -> str:
    """Normaliza un segmento de slug: lo no permitido pasa a '-'.

    Se conservan letras, dígitos, '_', '-' y '.'. Los espacios y el resto de
    signos pasan a '-', y las repeticiones se colapsan.
    """
    limpio = "".join(ch if (ch.isalnum() or ch in "_-.") else "-" for ch in segment)
    limpio = re.sub(r"-{2,}", "-", limpio)
    return limpio.strip("-")


def _allowed_sections(wiki_dir: str | Path | None) -> list[str]:
    """Secciones por las que se puede colgar una página.

    Las canónicas de SCHEMA.md, más los directorios que ya existen en el wiki
    (algunos proyectos usan `brand/` o `design/`, y el hook de design-inspiration
    pide `brand/<slug>`).
    """
    secciones = list(WIKI_SECTIONS)
    if wiki_dir is not None:
        wiki = Path(wiki_dir)
        if wiki.is_dir():
            for hijo in sorted(wiki.iterdir()):
                if hijo.is_dir() and hijo.name not in secciones:
                    secciones.append(hijo.name)
    return secciones


def sanitize_slug(slug: str, wiki_dir: str | Path | None = None) -> str:
    """Valida y normaliza el slug de una página wiki.

    Formato aceptado: `nombre` o `seccion/nombre` (como `concepts/design-system`,
    que es el que usan el schema de la tool y los proyectos reales). Cada
    segmento es un identificador con `[\\w.-]+`.

    Lanza `WikiPathError` (con el motivo y lo que se esperaba) si el slug
    lleva `..`, separadores de ruta fuera de formato, caracteres de control,
    una ruta absoluta o segmentos vacíos.
    """
    if not isinstance(slug, str):
        raise WikiPathError(
            f"El slug de wiki debe ser un texto, no {type(slug).__name__}: se esperaba "
            "un identificador tipo 'arquitectura' o 'concepts/design-system'."
        )
    bruto = slug.strip()
    if not bruto:
        raise WikiPathError(
            "El slug de wiki está vacío: se esperaba un identificador tipo "
            "'arquitectura' o 'concepts/design-system'."
        )
    if len(bruto) > MAX_SLUG_LEN:
        raise WikiPathError(
            f"El slug de wiki mide {len(bruto)} caracteres (máximo {MAX_SLUG_LEN}): "
            "se esperaba un identificador corto, no una ruta."
        )
    if _CONTROL_RE.search(bruto):
        raise WikiPathError(
            "El slug de wiki contiene caracteres de control: se esperaba un "
            "identificador con letras, dígitos, '-', '_' o '.'."
        )
    if "\\" in bruto:
        raise WikiPathError(
            "El slug de wiki contiene '\\': se esperaba un identificador con "
            "separador '/' (seccion/nombre) y nada más."
        )
    if ".." in bruto:
        raise WikiPathError(
            f"El slug de wiki contiene '..' ({bruto!r}): se esperaba un identificador "
            "sin recorrido de directorios, tipo 'arquitectura' o 'concepts/design-system'."
        )
    partes = bruto.split("/")
    if len(partes) > 2:
        raise WikiPathError(
            f"El slug de wiki tiene {len(partes) - 1} separadores '/': se esperaba como "
            "mucho uno (seccion/nombre)."
        )
    if any(not parte for parte in partes):
        raise WikiPathError(
            f"El slug de wiki tiene un segmento vacío ({bruto!r}): se esperaba "
            "'nombre' o 'seccion/nombre', sin '/' inicial ni final."
        )
    normalizados: list[str] = []
    for parte in partes:
        segmento = _normalize_segment(parte)
        if (
            not segmento
            or not _SEGMENT_RE.match(segmento)
            or len(segmento) > MAX_SLUG_SEGMENT_LEN
            or not any(ch.isalnum() or ch == "_" for ch in segmento)
        ):
            raise WikiPathError(
                f"El segmento {parte!r} del slug no es un identificador válido: se "
                "esperaba un nombre con letras, dígitos, '-', '_' o '.'."
            )
        normalizados.append(segmento)
    if len(normalizados) == 2:
        seccion = normalizados[0]
        permitidas = _allowed_sections(wiki_dir)
        if seccion not in permitidas:
            raise WikiPathError(
                f"La sección {seccion!r} no existe en el wiki: se esperaba una de "
                f"{', '.join(permitidas)}."
            )
    return "/".join(normalizados)


def _resolve_wiki_dir(wiki_dir: str | Path) -> Path:
    """Valida que `wiki_dir` sea el wiki de un proyecto (`.apex/wiki`) y lo resuelve.

    Es lo que impide que `append_log`/`update_index` escriban el log o el
    índice de un proyecto en un directorio cualquiera.
    """
    ruta = Path(wiki_dir).expanduser()
    try:
        resuelta = ruta.resolve()
    except OSError as exc:
        raise WikiPathError(
            f"No se pudo resolver el directorio del wiki {ruta}: {exc}. Se esperaba "
            "un directorio '<proyecto>/.apex/wiki'."
        )
    if resuelta.name != "wiki" or resuelta.parent.name != ".apex":
        raise WikiPathError(
            f"{resuelta} no es el wiki de un proyecto: se esperaba un directorio "
            "'<proyecto>/.apex/wiki'."
        )
    return resuelta


def wiki_page_path(wiki_dir: str | Path, slug: str) -> Path:
    """Resuelve la ruta de una página wiki, garantizando que no sale del wiki.

    Es el ÚNICO punto donde el slug se convierte en nombre de fichero: quien
    llama no concatena nunca. La comprobación final es sobre la ruta resuelta,
    así que un symlink tampoco puede sacarla de `.apex/wiki/`.
    """
    wiki = _resolve_wiki_dir(wiki_dir)
    seguro = sanitize_slug(slug, wiki_dir=wiki)
    destino = wiki / f"{seguro}.md"
    if not destino.resolve().is_relative_to(wiki):
        raise WikiPathError(
            f"La página {seguro!r} resolvería a {destino.resolve()}, fuera de {wiki}: "
            "se esperaba un slug que quede dentro del wiki del proyecto."
        )
    return destino


# --- Estructura del segundo cerebro (fuera de wiki/) ---

SECOND_BRAIN_TREE = {
    "brand": [
        "identity",        # logo, paleta, tipografía, voice
        "design-system",   # tokens, componentes base
        "strategy",        # positioning, audience, goals
        "performance",     # métricas éxito por checkpoint
    ],
    "raw": [
        "research",        # market research, competidores
        "socratic",        # transcripts de fase 0
        "papers",          # referencias académicas y técnicas
        "decisions-log",   # snapshots antes de invalidación
    ],
    "releases": [
        "drafts",          # feature branches / WIP
        "staging",         # pre-producción
        "published",       # prod + changelog + rollback
    ],
}


def _write_brand_readmes(brand_dir: Path, project_name: str) -> None:
    """README con pautas mínimas por sub-dir de brand/."""
    readmes = {
        "identity/README.md": f"""# Identidad — {project_name}

Archivos esperados:

- `palette.md` — paleta con roles semánticos y contraste WCAG AA calculado
- `typography.md` — familias, escala, line-height, letter-spacing
- `logo/` — primary, reversed, monochrome, icon, wordmark + escalas
  (favicon 16/32, app-icon 192/512/1024, navbar, hero, grid de construcción)
- `voice.md` — 3 adjetivos rectores + ejemplos de copy
- `shapes.svg` — motivos secundarios / brand patterns

Ver `skills/brand-identity/SKILL.md` del repo apex para protocolo completo.
""",
        "design-system/README.md": """# Design System

Archivos esperados:

- `tokens.css` — variables semánticas (--accent-primary, --bg-*, --text-*, etc.)
- `tokens.json` — mismos tokens para tooling y exportación
- `components.md` — inventario de componentes base con estados

Ver `skills/design-system/SKILL.md` para tokens obligatorios y reglas.
""",
        "strategy/README.md": """# Estrategia

- `positioning.md` — qué somos, qué no somos, para quién
- `audience.md` — personas, jobs to be done, dolores
- `goals.md` — objetivos por trimestre con métricas
""",
        "performance/README.md": """# Performance

- `metrics.md` — KPIs por checkpoint (MVP / v1 / v2)
- `benchmarks.md` — baseline de rendimiento
""",
    }
    for rel, content in readmes.items():
        path = brand_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def _write_raw_readmes(raw_dir: Path) -> None:
    """README con pautas mínimas por sub-dir de raw/."""
    readmes = {
        "research/README.md": """# Raw · Research

Depósito inmutable de investigación bruta:

- Análisis de competidores
- Estudios de mercado
- Reports sectoriales
- Entrevistas con usuarios (transcripts)

El pipeline `lib/ingest.py` procesa estos archivos y genera páginas
`wiki/entities/` o `wiki/comparisons/` según el tipo.
""",
        "socratic/README.md": """# Raw · Socrático

Transcripts de la fase 0 (socrático):

- Preguntas lanzadas al usuario
- Respuestas completas (no resumidas)
- Objeciones propias documentadas

Formato recomendado: `YYYY-MM-DD-ronda-N.md` con frontmatter
`{ fase: 0, ronda: N, cuestionado_a: <usuario> }`.

El ingest promueve respuestas clave a `wiki/concepts/` y `wiki/queries/`.
""",
        "papers/README.md": """# Raw · Papers

Referencias académicas y técnicas inmutables:

- Papers de arquitectura (hexagonal, multi-agent, RAG)
- Specs de protocolos (MCP, A2A, ACP)
- Documentación de librerías clave

El ingest extrae conceptos recurrentes a `wiki/concepts/`.
""",
        "decisions-log/README.md": """# Raw · Decisions Log

Snapshots inmutables de decisiones ANTES de invalidarse:

- Cuando una decisión se invalida en context.db, se copia aquí para
  preservar el razonamiento original.
- Formato: `YYYY-MM-DD-decision-N.md` con el reasoning completo.

Esto permite auditoría histórica ("¿por qué tomamos X hace 3 meses?")
incluso cuando la decisión ya no está vigente.
""",
    }
    for rel, content in readmes.items():
        path = raw_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def _write_releases_readme(releases_dir: Path) -> None:
    (releases_dir / "README.md").write_text("""# Releases

Pipeline de entrega del proyecto:

- `drafts/` — feature branches / WIP, todo lo que aún no ha llegado a
  staging. Cada subdirectorio es una feature: `drafts/<feature-name>/`.
- `staging/` — código en pre-producción, esperando aprobación final.
  `staging/<version>/` con changelog parcial.
- `published/` — releases en producción. Cada release es
  `published/<version>/` con:
  - `CHANGELOG.md`
  - `rollback-plan.md`
  - `deploy-notes.md`

La skill `portfolio-publisher/SKILL.md` puede consumir `published/*` para
generar las entradas del portfolio automáticamente.
""", encoding="utf-8")


def create_wiki(project_path: str | Path, project_name: str, domain: str = "") -> Path:
    """Crea la estructura completa del segundo cerebro en proyecto/.apex/.

    Genera:
    - `.apex/wiki/` — Karpathy LLM-Wiki (SCHEMA, index, log, entities/...)
    - `.apex/wiki/synthesis/` — output de synthesis.py (NUEVO)
    - `.apex/brand/` — identity, design-system, strategy, performance (NUEVO)
    - `.apex/raw/` — research, socratic, papers, decisions-log (NUEVO)
    - `.apex/releases/` — drafts, staging, published (NUEVO)

    Devuelve el path del wiki/ (para compatibilidad con código existente).
    """
    apex_dir = Path(project_path) / ".apex"
    wiki_dir = apex_dir / "wiki"
    wiki_dir.mkdir(parents=True, exist_ok=True)

    # --- Karpathy wiki subdirs (con synthesis/ nuevo) ---
    for subdir in ("entities", "concepts", "comparisons", "queries", "raw", "synthesis"):
        (wiki_dir / subdir).mkdir(exist_ok=True)

    # --- Segundo cerebro (brand, raw, releases fuera de wiki) ---
    for top, subs in SECOND_BRAIN_TREE.items():
        top_dir = apex_dir / top
        top_dir.mkdir(exist_ok=True)
        for sub in subs:
            (top_dir / sub).mkdir(exist_ok=True)

    _write_brand_readmes(apex_dir / "brand", project_name)
    _write_raw_readmes(apex_dir / "raw")
    _write_releases_readme(apex_dir / "releases")

    # --- SCHEMA.md del wiki (Karpathy + referencia al segundo cerebro) ---
    (wiki_dir / "SCHEMA.md").write_text(f"""# Wiki Schema — {project_name}

## Convenciones

### Páginas
- Cada página es un archivo `.md` en su directorio correspondiente.
- Frontmatter YAML obligatorio: `title`, `created`, `updated`, `type`, `tags`.
- Mínimo 2 outbound `[[wikilinks]]` por página (excepto raw/).
- Tags deben pertenecer a la taxonomía definida abajo.

### Taxonomía de tags
- `domain`: Conceptos del dominio del proyecto
- `architecture`: Decisiones arquitectónicas
- `error`: Errores conocidos y lecciones
- `pattern`: Patrones reutilizables
- `decision`: Decisiones tomadas
- `data`: Fuentes de datos y esquemas
- `security`: Consideraciones de seguridad
- `performance`: Métricas y optimizaciones
- `design-inspiration`: Referencias visuales (de `skills/design-research`)
- `synthesis`: Páginas generadas por `lib/synthesis.py`
{f'- `{domain}`: Específico del dominio' if domain else ''}

### Tipos de página
| Tipo | Directorio | Descripción |
|------|-----------|-------------|
| entity | entities/ | Producto, servicio, componente concreto |
| concept | concepts/ | Idea abstracta, patrón, principio |
| comparison | comparisons/ | Análisis comparativo (A vs B) |
| query | queries/ | Pregunta frecuente con respuesta compilada |
| raw | raw/ | Fuente inmutable (no editar) |
| synthesis | synthesis/ | Resumen auto-generado por dreaming |

### Relación con el segundo cerebro

Fuera de `wiki/` hay tres árboles complementarios:

- `.apex/brand/` — identidad visual y estrategia (Thomas escribe, agente lee)
- `.apex/raw/` — fuentes brutas pre-síntesis (research, socratic, papers)
- `.apex/releases/` — pipeline de entrega (drafts → staging → published)

El pipeline `lib/ingest.py` lee `.apex/raw/` y promueve señales a
`wiki/entities/` o `wiki/concepts/`. El synthesizer `lib/synthesis.py`
escribe en `wiki/synthesis/` cuando la densidad crece.

### Contradicciones
Si dos páginas se contradicen, documentar en frontmatter:
```yaml
contradicts: [[otra-página]]
resolution: "Pendiente" | "Resuelto: se eligió X porque Y"
```

### Tamaño
- Mínimo: 100 palabras
- Máximo: 2000 palabras (si excede, dividir en sub-páginas)
""", encoding="utf-8")

    # index.md
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    (wiki_dir / "index.md").write_text(f"""# {project_name} — Knowledge Base

> Última actualización: {now}

## Entidades
_Aún no hay entidades documentadas._

## Conceptos
_Aún no hay conceptos documentados._

## Comparaciones
_Aún no hay comparaciones documentadas._

## Preguntas Frecuentes
_Aún no hay queries documentadas._

## Fuentes
_Aún no hay fuentes raw ingresadas._

## Síntesis
_Aún no hay síntesis generadas._
""", encoding="utf-8")

    # log.md
    (wiki_dir / "log.md").write_text(f"""# Wiki Log — {project_name}

> Registro cronológico de acciones en la knowledge base.

---

- **{now}** — Wiki inicializada para proyecto "{project_name}"
- **{now}** — Scaffold de segundo cerebro creado (brand/, raw/, releases/)
""", encoding="utf-8")

    return wiki_dir


def append_log(wiki_dir: str | Path, action: str) -> None:
    """Añade una entrada al log.md del wiki del proyecto.

    El `wiki_dir` tiene que ser el wiki de un proyecto (`.apex/wiki`): con eso
    el log nunca se escribe fuera del proyecto.
    """
    wiki = _resolve_wiki_dir(wiki_dir)
    log_path = wiki / "log.md"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"- **{now}** — {action}\n")


def update_index(wiki_dir: str | Path) -> None:
    """Reconstruye index.md a partir de los archivos existentes.

    El `wiki_dir` tiene que ser el wiki de un proyecto (`.apex/wiki`): con eso
    el índice nunca se escribe fuera del proyecto.
    """
    wiki = _resolve_wiki_dir(wiki_dir)
    sections = {
        "Entidades": "entities",
        "Conceptos": "concepts",
        "Comparaciones": "comparisons",
        "Preguntas Frecuentes": "queries",
        "Fuentes": "raw",
        "Síntesis": "synthesis",
    }

    lines = [f"# Knowledge Base\n"]
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines.append(f"> Última actualización: {now}\n")

    for section_name, subdir in sections.items():
        lines.append(f"\n## {section_name}")
        dir_path = wiki / subdir
        if not dir_path.exists():
            lines.append(f"_Aún no hay {section_name.lower()} documentados._")
            continue
        md_files = sorted(dir_path.glob("*.md"))
        # filter out READMEs
        md_files = [f for f in md_files if f.stem.lower() != "readme"]
        if md_files:
            for f in md_files:
                slug = f"{subdir}/{f.stem}"
                title = f.stem.replace("-", " ").title()
                first_line = f.read_text(encoding="utf-8").split("\n")[0]
                if first_line.startswith("# "):
                    title = first_line[2:].strip()
                lines.append(f"- [[{slug}]] — {title}")
        else:
            lines.append(f"_Aún no hay {section_name.lower()} documentados._")

    (wiki / "index.md").write_text("\n".join(lines), encoding="utf-8")
