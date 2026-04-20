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

from pathlib import Path
from datetime import datetime, timezone


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
    """Añade una entrada al log.md."""
    log_path = Path(wiki_dir) / "log.md"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"- **{now}** — {action}\n")


def update_index(wiki_dir: str | Path) -> None:
    """Reconstruye index.md a partir de los archivos existentes."""
    wiki = Path(wiki_dir)
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
