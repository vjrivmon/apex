"""Generador de draft MDX para el portfolio VR. Web desde context.db.

Extrae campos de `.apex/context.db` y produce un archivo MDX en
`vr-web/content/cases/<slug>.mdx` compatible con el schema `CaseStudy` del
portfolio. Si el archivo destino ya existe, fusiona preservando valores
manuales (strategy: los campos auto-generados reemplazan, los escritos a mano
se conservan si no hay fuente autoritativa).

Convención: el proyecto registra sus campos de portfolio como `meta` en
context.db con prefijo `portfolio_` (añadido por el MCP cuando el usuario los
aprueba). Campos soportados:

- portfolio_title, portfolio_client, portfolio_duration, portfolio_stack
- portfolio_status, portfolio_headline
- portfolio_context, portfolio_problem, portfolio_approach
- portfolio_constraints (JSON array de strings)
- portfolio_results (JSON array de {metric, value})
- portfolio_learnings (JSON array de strings)
- portfolio_related_pack (citadel/compass/forge)
- portfolio_related_pack_cta
- portfolio_repo_url, portfolio_demo_url
- portfolio_tags (JSON array)
- portfolio_built_with_apex (bool, default True)

Uso:
  python -m lib.portfolio_publish --slug apex --context-db .apex/context.db
  python -m lib.portfolio_publish --slug apex --apply
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

import yaml

DEFAULT_OUT_DIR = Path.home() / "RoadToDevOps" / "vr-web" / "content" / "cases"

PORTFOLIO_META_KEYS = {
    "portfolio_title": "title",
    "portfolio_client": "client",
    "portfolio_duration": "duration",
    "portfolio_stack": "stack",
    "portfolio_status": "status",
    "portfolio_headline": "headline",
    "portfolio_context": "context",
    "portfolio_problem": "problem",
    "portfolio_approach": "approach",
    "portfolio_related_pack": "relatedPack",
    "portfolio_related_pack_cta": "relatedPackCta",
    "portfolio_repo_url": "repoUrl",
    "portfolio_demo_url": "demoUrl",
}
PORTFOLIO_META_LISTS = {
    "portfolio_constraints": "constraints",
    "portfolio_results": "results",
    "portfolio_learnings": "learnings",
    "portfolio_tags": "tags",
}


def _read_meta_all(conn: sqlite3.Connection) -> dict[str, str]:
    """Lee project_meta como dict {key: value} — tolera que la tabla no exista."""
    try:
        rows = conn.execute("SELECT key, value FROM project_meta").fetchall()
        return {str(r[0]): str(r[1]) if r[1] is not None else "" for r in rows}
    except sqlite3.OperationalError:
        return {}


def _fallback_from_decisions(conn: sqlite3.Connection) -> dict[str, Any]:
    """Si faltan campos portfolio_*, intenta inferir valores desde decisiones
    vigentes de categorías relevantes (stack, architecture, design)."""
    inferred: dict[str, Any] = {}
    try:
        stack_rows = conn.execute(
            "SELECT decision FROM decisions WHERE category IN ('stack', 'architecture') "
            "AND invalid_from IS NULL ORDER BY id DESC LIMIT 3"
        ).fetchall()
        if stack_rows:
            inferred["stack"] = "; ".join(r[0][:100] for r in stack_rows)
    except sqlite3.OperationalError:
        pass
    return inferred


def _build_case_dict(conn: sqlite3.Connection, slug: str) -> dict[str, Any]:
    meta = _read_meta_all(conn)
    case: dict[str, Any] = {"slug": slug}

    # Campos scalar
    for meta_key, case_field in PORTFOLIO_META_KEYS.items():
        if meta.get(meta_key):
            case[case_field] = meta[meta_key]

    # Campos lista (JSON en meta)
    for meta_key, case_field in PORTFOLIO_META_LISTS.items():
        raw = meta.get(meta_key)
        if not raw:
            continue
        try:
            value = json.loads(raw)
            if isinstance(value, list):
                case[case_field] = value
        except (json.JSONDecodeError, TypeError):
            # Si no es JSON válido, ignorar silencioso
            continue

    # Fallback por nombre del proyecto
    if "title" not in case:
        case["title"] = meta.get("nombre") or slug

    # builtWithApex default True (APEX es la herramienta que genera esto)
    if meta.get("portfolio_built_with_apex"):
        case["builtWithApex"] = meta["portfolio_built_with_apex"].lower() in ("true", "1", "yes")
    else:
        case["builtWithApex"] = True

    # Inferencia si faltan campos core
    if "stack" not in case or "problem" not in case:
        case.update({k: v for k, v in _fallback_from_decisions(conn).items() if k not in case})

    # Normalizar orden de campos para output estable
    ordered_fields = [
        "slug", "title", "client", "duration", "stack", "status", "headline",
        "context", "problem", "constraints", "approach", "results", "learnings",
        "relatedPack", "relatedPackCta", "repoUrl", "demoUrl", "tags",
        "builtWithApex",
    ]
    return {f: case[f] for f in ordered_fields if f in case}


def _merge_with_existing(draft: dict[str, Any], existing_path: Path) -> dict[str, Any]:
    """Si ya existe un MDX, fusiona preservando campos manuales.

    Regla: para cada campo que ya existe en el MDX y NO viene de context.db
    con un valor no-vacío, se mantiene el del archivo. Esto evita pisar
    ediciones manuales cuando el publisher se ejecuta varias veces.
    """
    if not existing_path.exists():
        return draft
    raw = existing_path.read_text(encoding="utf-8")
    if not raw.startswith("---"):
        return draft
    try:
        fm_end = raw.index("---", 3)
    except ValueError:
        return draft
    existing = yaml.safe_load(raw[3:fm_end]) or {}
    merged: dict[str, Any] = dict(existing)
    for key, value in draft.items():
        if value is None or value == "" or value == []:
            continue
        merged[key] = value
    return merged


def _format_mdx(case: dict[str, Any]) -> str:
    """Serializa el dict a MDX con YAML frontmatter. Body queda vacío: todo
    el contenido estructurado vive en el frontmatter."""
    # Forzar block style en listas y multi-line en strings con \n para legibilidad
    yaml_text = yaml.safe_dump(
        case,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
        width=10_000,  # evita line wrapping agresivo
    )
    return f"---\n{yaml_text}---\n"


def generate(slug: str, context_db_path: Path, out_dir: Path, apply: bool = False) -> Path:
    """Genera el MDX draft o definitivo para `slug`.

    Args:
        slug: identificador del caso (mismo que file stem en content/cases/).
        context_db_path: path a .apex/context.db.
        out_dir: directorio de destino (ej. vr-web/content/cases/).
        apply: si True escribe `<slug>.mdx` (final). Si False escribe
               `<slug>.mdx.draft` para que el usuario revise antes de aprobar.

    Returns:
        Path al archivo escrito.
    """
    if not context_db_path.exists():
        raise FileNotFoundError(f"context.db no encontrada: {context_db_path}")
    out_dir.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(f"file:{context_db_path}?mode=ro", uri=True)
    try:
        case = _build_case_dict(conn, slug)
    finally:
        conn.close()

    final_path = out_dir / f"{slug}.mdx"
    case = _merge_with_existing(case, final_path)

    target = final_path if apply else (out_dir / f"{slug}.mdx.draft")
    target.write_text(_format_mdx(case), encoding="utf-8")
    return target


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--slug", required=True, help="Slug del caso (ej. 'apex', 'dni')")
    p.add_argument("--context-db", type=Path, default=Path(".apex/context.db"))
    p.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    p.add_argument("--apply", action="store_true", help="Escribe el .mdx final en vez del .draft")
    args = p.parse_args(argv)

    try:
        path = generate(args.slug, args.context_db, args.out_dir, apply=args.apply)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    print(f"Escrito: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
