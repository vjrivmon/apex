"""LLM-Wiki Scaffold — Crea la estructura de knowledge base por proyecto.

Sigue el patrón de Karpathy (LLM-Wiki):
- SCHEMA.md: convenciones y estructura
- index.md: catálogo de contenido (navegación)
- log.md: registro cronológico de acciones (append-only)

Directorios:
- entities/: productos, servicios, conceptos del dominio
- concepts/: ideas abstractas, patrones, principios
- comparisons/: análisis comparativos
- queries/: preguntas frecuentes y sus respuestas compiladas
- raw/: fuentes inmutables (artículos, papers, transcripciones)
"""
from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone


def create_wiki(project_path: str | Path, project_name: str, domain: str = "") -> Path:
    """Crea la estructura wiki en proyecto/.apex/wiki/."""
    wiki_dir = Path(project_path) / ".apex" / "wiki"
    wiki_dir.mkdir(parents=True, exist_ok=True)

    # Subdirectorios
    for subdir in ("entities", "concepts", "comparisons", "queries", "raw"):
        (wiki_dir / subdir).mkdir(exist_ok=True)

    # SCHEMA.md
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
{f'- `{domain}`: Específico del dominio' if domain else ''}

### Tipos de página
| Tipo | Directorio | Descripción |
|------|-----------|-------------|
| entity | entities/ | Producto, servicio, componente concreto |
| concept | concepts/ | Idea abstracta, patrón, principio |
| comparison | comparisons/ | Análisis comparativo (A vs B) |
| query | queries/ | Pregunta frecuente con respuesta compilada |
| raw | raw/ | Fuente inmutable (no editar) |

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
""", encoding="utf-8")

    # log.md
    (wiki_dir / "log.md").write_text(f"""# Wiki Log — {project_name}

> Registro cronológico de acciones en la knowledge base.

---

- **{now}** — Wiki inicializada para proyecto "{project_name}"
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
    }

    lines = [f"# Knowledge Base\n"]
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines.append(f"> Última actualización: {now}\n")

    for section_name, subdir in sections.items():
        lines.append(f"\n## {section_name}")
        dir_path = wiki / subdir
        md_files = sorted(dir_path.glob("*.md"))
        if md_files:
            for f in md_files:
                slug = f"{subdir}/{f.stem}"
                # Leer título del frontmatter o usar el nombre del archivo
                title = f.stem.replace("-", " ").title()
                first_line = f.read_text(encoding="utf-8").split("\n")[0]
                if first_line.startswith("# "):
                    title = first_line[2:].strip()
                lines.append(f"- [[{slug}]] — {title}")
        else:
            lines.append(f"_Aún no hay {section_name.lower()} documentados._")

    (wiki / "index.md").write_text("\n".join(lines), encoding="utf-8")
