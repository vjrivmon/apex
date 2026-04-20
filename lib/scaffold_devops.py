"""Copia templates DevOps + Monitor al proyecto destino.

Renombra placeholders (PROJECT_NAME, STACK, DEPLOY_TARGET, PORT, HEALTH_PATH)
en el texto de cada archivo. Crea .github/, docker/, monitor/ en el destino
sin pisar archivos existentes (merge-safe).

Uso:
    python -m lib.scaffold_devops --target /path/proyecto --name miapp --stack python
    python -m lib.scaffold_devops --target . --name apex --with-monitoring
"""
from __future__ import annotations

import argparse
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path


TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"


@dataclass
class ScaffoldOptions:
    target: Path
    project_name: str
    stack: str = "python"              # python | node
    deploy_target: str = "vercel"       # vercel | fly | vps
    port: int = 8000
    health_path: str = "/health"
    with_monitoring: bool = True
    overwrite: bool = False


@dataclass
class ScaffoldReport:
    copied: list[Path] = field(default_factory=list)
    skipped: list[Path] = field(default_factory=list)


def _replace_placeholders(text: str, opts: ScaffoldOptions) -> str:
    return (
        text
        .replace("{{PROJECT_NAME}}", opts.project_name)
        .replace("{{STACK}}", opts.stack)
        .replace("{{DEPLOY_TARGET}}", opts.deploy_target)
        .replace("{{PORT}}", str(opts.port))
        .replace("{{HEALTH_PATH}}", opts.health_path)
    )


def _copy_tree(src_root: Path, dest_root: Path, opts: ScaffoldOptions,
                report: ScaffoldReport) -> None:
    for src in src_root.rglob("*"):
        if src.is_dir():
            continue
        rel = src.relative_to(src_root)
        dest = dest_root / rel

        if dest.exists() and not opts.overwrite:
            report.skipped.append(dest)
            continue

        dest.parent.mkdir(parents=True, exist_ok=True)

        if src.suffix in {".yml", ".yaml", ".json", ".md", ".py", ".example", ".toml"} \
           or src.name in {"Dockerfile", ".dockerignore"}:
            content = src.read_text(encoding="utf-8")
            dest.write_text(_replace_placeholders(content, opts), encoding="utf-8")
        else:
            shutil.copy2(src, dest)
        report.copied.append(dest)


def scaffold(opts: ScaffoldOptions) -> ScaffoldReport:
    """Copia templates al target. Retorna un reporte."""
    opts.target = opts.target.resolve()
    opts.target.mkdir(parents=True, exist_ok=True)

    report = ScaffoldReport()

    # .github/workflows/
    src = TEMPLATES_DIR / ".github"
    if src.exists():
        _copy_tree(src, opts.target / ".github", opts, report)

    # docker/
    src = TEMPLATES_DIR / "docker"
    if src.exists():
        _copy_tree(src, opts.target / "docker", opts, report)

    # monitor/
    if opts.with_monitoring:
        src = TEMPLATES_DIR / "monitor"
        if src.exists():
            _copy_tree(src, opts.target / "monitor", opts, report)

    return report


# --- CLI ---

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--target", type=Path, required=True,
                   help="Directorio destino (suele ser el root del proyecto)")
    p.add_argument("--name", required=True, help="Nombre del proyecto")
    p.add_argument("--stack", choices=["python", "node"], default="python")
    p.add_argument("--deploy-target", choices=["vercel", "fly", "vps"], default="vercel")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--health-path", default="/health")
    p.add_argument("--no-monitoring", dest="with_monitoring", action="store_false")
    p.add_argument("--overwrite", action="store_true",
                   help="Sobrescribe archivos existentes (por defecto: skip)")
    args = p.parse_args(argv)

    opts = ScaffoldOptions(
        target=args.target,
        project_name=args.name,
        stack=args.stack,
        deploy_target=args.deploy_target,
        port=args.port,
        health_path=args.health_path,
        with_monitoring=args.with_monitoring,
        overwrite=args.overwrite,
    )
    report = scaffold(opts)
    print(f"Copiados: {len(report.copied)} archivos")
    for p_ in report.copied:
        print(f"  + {p_.relative_to(opts.target)}")
    if report.skipped:
        print(f"\nSaltados ({len(report.skipped)}, ya existían; usa --overwrite para forzar):")
        for p_ in report.skipped:
            print(f"  · {p_.relative_to(opts.target)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
