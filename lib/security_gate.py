"""Security Gate — verifica que las 8 capas AgentArmor tienen evidencia.

Lee `.apex/security/L1-ingestion.md` … `L8-identity.md` (formato YAML
frontmatter + body) y comprueba que todos tienen `status: passed`. Si
alguno falta o no está en `passed`, exit code 1 → bloquea fase 11.

Formato esperado de cada archivo:

    ---
    layer: L4
    title: Planning
    status: passed | pending | failed
    reviewed_by: Vicente
    reviewed_at: 2026-04-20
    evidence:
      - "risk scoring implementado en lib/planner.py"
      - "circuit breaker con cooldown 60s tras 10 fallos"
    asi_coverage:
      - ASI02
      - ASI05
    ---
    ...notas opcionales...

Uso:
    python -m lib.security_gate --project-root .
    python -m lib.security_gate --project-root . --strict  # sin strict, warning-only
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml


REQUIRED_LAYERS = [
    ("L1", "ingestion"),
    ("L2", "storage"),
    ("L3", "context"),
    ("L4", "planning"),
    ("L5", "execution"),
    ("L6", "output"),
    ("L7", "inter-agent"),
    ("L8", "identity"),
]

# La fase del gate AgentArmor no es un entero: 10.5. SQLite la guarda como
# REAL (afinidad INTEGER, pero tipado dinámico) y se consulta igual. El gate
# escribe aquí su veredicto para que la transición a la fase 11 tenga algo
# que leer: sin veredicto, el gate no bloqueaba nada.
SECURITY_GATE_PHASE = 10.5

# Marcadores de que el proyecto tiene gitleaks configurado (Gap F, S19.1c).
# La lista vive en lib/gitleaks.py, que es su única fuente: aquí se reexporta
# porque el blueprint la nombra como parte de la API del gate.
from gitleaks import GITLEAKS_MARKERS as GITLEAKS_MARKERS  # noqa: E402
from gitleaks import is_configured as _gitleaks_is_configured  # noqa: E402


@dataclass
class LayerStatus:
    layer: str                  # L1..L8
    file_name: str              # ej. L1-ingestion
    path: Path | None
    exists: bool
    status: str                  # passed | pending | failed | missing
    evidence: list[str] = field(default_factory=list)
    asi_coverage: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass
class GateReport:
    timestamp: datetime
    project_root: Path
    layers: list[LayerStatus] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(l.status == "passed" for l in self.layers)

    @property
    def failed_layers(self) -> list[LayerStatus]:
        return [l for l in self.layers if l.status != "passed"]


def _parse_layer_file(path: Path) -> dict:
    """Extrae el frontmatter YAML del archivo."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise ValueError(f"{path.name}: no frontmatter")
    try:
        end = text.index("---", 3)
    except ValueError:
        raise ValueError(f"{path.name}: frontmatter sin cierre")
    return yaml.safe_load(text[3:end]) or {}


def check_gate(project_root: Path) -> GateReport:
    report = GateReport(
        timestamp=datetime.now(timezone.utc),
        project_root=project_root,
    )
    sec_dir = project_root / ".apex" / "security"

    for layer_id, name in REQUIRED_LAYERS:
        filename = f"{layer_id}-{name}.md"
        path = sec_dir / filename
        if not path.exists():
            report.layers.append(LayerStatus(
                layer=layer_id, file_name=filename, path=None,
                exists=False, status="missing",
                error=f"Falta {path}",
            ))
            continue
        try:
            data = _parse_layer_file(path)
        except Exception as e:
            report.layers.append(LayerStatus(
                layer=layer_id, file_name=filename, path=path,
                exists=True, status="failed", error=str(e),
            ))
            continue

        status = str(data.get("status", "pending")).lower()
        report.layers.append(LayerStatus(
            layer=layer_id, file_name=filename, path=path,
            exists=True, status=status,
            evidence=list(data.get("evidence") or []),
            asi_coverage=list(data.get("asi_coverage") or []),
        ))

    return report


def _check_gitleaks_configured(project_root: Path) -> bool:
    """¿Hay gitleaks configurado en el proyecto?

    True si existe `.husky/pre-commit` o `.gitleaks.toml` en la raíz del
    proyecto; False si no.

    El predicado vive en `lib/gitleaks.py` (única fuente) y aquí se reexporta
    para que la API que pide el blueprint S19.1c siga siendo la que usa el
    gate. Detecta la CONFIGURACIÓN, no la instalación del binario ni la
    ejecución real del hook: para eso están `lib/gitleaks.is_available()` y
    `lib/gitleaks.run_gitleaks()`. La fase 10 (seguridad) usa esto para no
    dejar pasar sin detección de secretos.
    """
    return _gitleaks_is_configured(project_root)


def verdict_from_report(report: GateReport) -> dict:
    """Traduce el informe del gate a los campos de `grader_verdicts`.

    Los devuelve como kwargs de `db.add_verdict()`. `should_block` es
    exactamente lo contrario de `report.passed`: si alguna capa no está en
    `passed`, el veredicto bloquea la transición.

    `quality` se deriva de las capas superadas (0-4): la escala del grader
    es de 1 a 4, y aquí se reparte el rango completo porque 0 capas
    superadas (nada revisado) tiene que distinguirse de 4.
    """
    total = len(report.layers) or 1
    superadas = sum(1 for capa in report.layers if capa.status == "passed")
    fallidas = report.failed_layers
    quality = (superadas * 4) // total
    issues = [f"{capa.layer}: {capa.status}" for capa in fallidas]
    if fallidas:
        detalle = ", ".join(f"{capa.layer} ({capa.status})" for capa in fallidas)
        reasoning = (
            f"Gate AgentArmor 10.5: {superadas}/{total} capas en passed. "
            f"Bloquean: {detalle}."
        )
    else:
        reasoning = f"Gate AgentArmor 10.5: {superadas}/{total} capas en passed."
    return {
        "phase": SECURITY_GATE_PHASE,
        "quality": quality,
        "category": "security",
        "issues": issues,
        "should_block": not report.passed,
        "reasoning": reasoning,
        "deterministic_checks": {
            capa.layer: (capa.status == "passed") for capa in report.layers
        },
        "llm_judged": False,
    }


def render_report(report: GateReport) -> str:
    lines = [
        f"# Security Gate Report — {report.timestamp.strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        f"- Proyecto: `{report.project_root}`",
        f"- Gate: **{'PASSED' if report.passed else 'BLOCKED'}**",
        "",
        "## Capas AgentArmor",
        "",
        "| Layer | Status | Evidencia | ASI Coverage |",
        "|-------|--------|-----------|--------------|",
    ]
    icons = {"passed": "✓", "pending": "…", "failed": "✗", "missing": "—"}
    for l in report.layers:
        ev = f"{len(l.evidence)} items" if l.evidence else "sin evidencia"
        asi = ", ".join(l.asi_coverage) if l.asi_coverage else "—"
        lines.append(
            f"| {l.layer} | {icons.get(l.status, '?')} {l.status} | {ev} | {asi} |"
        )

    failed = report.failed_layers
    if failed:
        lines.append("")
        lines.append("## Capas que bloquean el deploy")
        lines.append("")
        for l in failed:
            lines.append(f"### {l.layer} — {l.file_name}")
            if l.error:
                lines.append(f"Error: {l.error}")
            else:
                lines.append(f"Status actual: `{l.status}`")
                if not l.evidence:
                    lines.append("No hay evidencia registrada. Añadir items "
                                 "concretos en `evidence:` y cambiar `status: passed`.")
            lines.append("")

    lines.append("## Cómo desbloquear")
    lines.append("")
    lines.append("1. Completa cada capa con evidencia concreta (archivo/línea/commit).")
    lines.append("2. Cambia `status: passed` en el frontmatter.")
    lines.append("3. Vuelve a ejecutar `apex_security_gate` hasta que pase.")
    lines.append("4. Solo entonces permitir fase 11 (Deploy).")

    return "\n".join(lines)


def write_report(report: GateReport) -> Path:
    out_dir = report.project_root / ".apex" / "security"
    out_dir.mkdir(parents=True, exist_ok=True)
    date = report.timestamp.strftime("%Y-%m-%d")
    path = out_dir / f"audit-report-{date}.md"
    path.write_text(render_report(report), encoding="utf-8")
    return path


def scaffold_templates(project_root: Path) -> list[Path]:
    """Copia los templates L1-L8.md a `.apex/security/` si no existen."""
    templates_dir = Path(__file__).resolve().parent.parent / "templates" / "apex-security"
    dest_dir = project_root / ".apex" / "security"
    dest_dir.mkdir(parents=True, exist_ok=True)
    copied: list[Path] = []
    for layer_id, name in REQUIRED_LAYERS:
        src = templates_dir / f"{layer_id}-{name}.md"
        dst = dest_dir / f"{layer_id}-{name}.md"
        if dst.exists():
            continue
        if src.exists():
            dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
            copied.append(dst)
    readme_src = templates_dir / "README.md"
    readme_dst = dest_dir / "README.md"
    if readme_src.exists() and not readme_dst.exists():
        readme_dst.write_text(readme_src.read_text(encoding="utf-8"), encoding="utf-8")
        copied.append(readme_dst)
    return copied


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--project-root", type=Path, default=Path("."))
    p.add_argument("--strict", action="store_true", default=True,
                   help="Exit 1 si alguna capa no está en passed (default)")
    p.add_argument("--warning-only", dest="strict", action="store_false",
                   help="Exit 0 siempre, solo imprime el report")
    p.add_argument("--scaffold", action="store_true",
                   help="Copia L1..L8 templates a .apex/security/ si no existen")
    p.add_argument("--no-write", action="store_true",
                   help="No escribe audit-report-YYYY-MM-DD.md")
    args = p.parse_args(argv)

    root = args.project_root.resolve()

    if args.scaffold:
        copied = scaffold_templates(root)
        print(f"Scaffolded {len(copied)} archivos en .apex/security/")
        for p_ in copied:
            print(f"  + {p_.relative_to(root)}")

    report = check_gate(root)
    md = render_report(report)
    print(md)
    if not args.no_write:
        out = write_report(report)
        print(f"\n(Report: {out})", file=sys.stderr)

    return 0 if (report.passed or not args.strict) else 1


if __name__ == "__main__":
    sys.exit(main())
