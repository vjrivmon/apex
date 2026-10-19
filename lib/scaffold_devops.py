"""Copia templates DevOps + Monitor al proyecto destino.

Renombra placeholders (PROJECT_NAME, STACK, DEPLOY_TARGET, PORT, HEALTH_PATH)
en el texto de cada archivo. Crea .github/, docker/, monitor/, devops/ en el
destino sin pisar archivos existentes (merge-safe).

Sprint 19 (Gap F): instala ademas el hook pre-commit de gitleaks en
`<destino>/.husky/pre-commit`. Es idempotente: si el hook ya existe, se
salta salvo que se pase `overwrite=True`.

Uso:
    python -m lib.scaffold_devops --target /path/proyecto --name miapp --stack python
    python -m lib.scaffold_devops --target . --name apex --with-monitoring
    python -m lib.scaffold_devops --target . --name apex --with-commands
"""
from __future__ import annotations

import argparse
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path


TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

# Hook de gitleaks: vive en templates/devops/.husky/ y se instala en
# `<destino>/.husky/pre-commit`.
HUSKY_HOOK_RELPATH = Path(".husky") / "pre-commit"

# Slash commands de APEX: templates/commands/*.md -> `<destino>/.claude/commands/`.
COMMANDS_DIRNAME = "commands"


@dataclass
class ScaffoldOptions:
    target: Path
    project_name: str
    stack: str = "python"              # python | node
    deploy_target: str = "vercel"       # vercel | fly | vps
    port: int = 8000
    health_path: str = "/health"
    with_monitoring: bool = True
    with_commands: bool = False         # slash commands de APEX (S19.3)
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
                report: ScaffoldReport, exclude_dirs: tuple[str, ...] = ()) -> None:
    for src in src_root.rglob("*"):
        if src.is_dir():
            continue
        rel = src.relative_to(src_root)
        if rel.parts and rel.parts[0] in exclude_dirs:
            continue
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


def _install_hook(src: Path, dest: Path, opts: ScaffoldOptions,
                  report: ScaffoldReport) -> None:
    """Instala un hook ejecutable (husky) en el destino.

    Idempotente: si ya existe y no se pasa `overwrite=True`, se salta. Al
    instalarse se le da el bit de ejecutable: un hook sin permiso de
    ejecucion no se ejecuta y el gate de fase 10.5 daria un falso verde.
    """
    if not src.exists():
        return
    if dest.exists() and not opts.overwrite:
        report.skipped.append(dest)
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    dest.chmod(0o755)
    report.copied.append(dest)


def install_slash_commands(target: Path | str, overwrite: bool = False) -> tuple[list[Path], list[Path]]:
    """Instala los slash commands de APEX en `<target>/.claude/commands/`.

    Devuelve (instalados, saltados). No pisa un comando que ya exista salvo
    que se pase `overwrite=True`.
    """
    dest_dir = Path(target) / ".claude" / COMMANDS_DIRNAME
    src_dir = TEMPLATES_DIR / COMMANDS_DIRNAME
    installed: list[Path] = []
    skipped: list[Path] = []
    if not src_dir.exists():
        return installed, skipped
    dest_dir.mkdir(parents=True, exist_ok=True)
    for src in sorted(src_dir.glob("*.md")):
        dest = dest_dir / src.name
        if dest.exists() and not overwrite:
            skipped.append(dest)
            continue
        shutil.copy2(src, dest)
        installed.append(dest)
    return installed, skipped


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

    # devops/ + hook de gitleaks en .husky/ (Sprint 19, Gap F)
    src = TEMPLATES_DIR / "devops"
    if src.exists():
        # La variante .husky/ NO se copia dentro de devops/: se instala en
        # la raiz del proyecto, que es donde husky la busca.
        _copy_tree(src, opts.target / "devops", opts, report,
                   exclude_dirs=(".husky",))
        _install_hook(src / HUSKY_HOOK_RELPATH,
                      opts.target / HUSKY_HOOK_RELPATH, opts, report)

    # Slash commands de APEX (Sprint 19, S19.3)
    if opts.with_commands:
        installed, skipped = install_slash_commands(opts.target, overwrite=opts.overwrite)
        report.copied.extend(installed)
        report.skipped.extend(skipped)

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
    p.add_argument("--with-commands", action="store_true",
                   help="Instala los slash commands de APEX en .claude/commands/")
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
        with_commands=args.with_commands,
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
