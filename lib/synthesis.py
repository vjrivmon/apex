"""Density-triggered synthesis — dispara dream_deep cuando el cerebro crece.

El módulo es una capa delgada sobre `ApexContextDB.dream_deep()`:

1. Calcula "densidad reciente" (últimos 7 días): nuevas decisiones,
   nuevos errores, páginas wiki sin sync, session logs.
2. Si supera umbrales, ejecuta dream_deep.
3. Escribe un informe en `.apex/wiki/synthesis/YYYY-MM-DD.md` con los
   items promovidos, agrupados por categoría.

Uso:
    python -m lib.synthesis --project-root .              # auto (respeta umbrales)
    python -m lib.synthesis --project-root . --force       # fuerza dream_deep
    python -m lib.synthesis --project-root . --min-score 0.5

Tool MCP:
    apex_synthesize(trigger="auto"|"force", min_score=0.6)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Permitir import como módulo o como script suelto
sys.path.insert(0, str(Path(__file__).parent))
from context_db import ApexContextDB

try:  # el curador es opcional: sin httpx, APEX sigue funcionando igual
    import curator as _curator
except ImportError:  # pragma: no cover - solo si httpx no está instalado
    _curator = None  # type: ignore


DEFAULT_THRESHOLDS = {
    "new_decisions_7d": 5,
    "new_errors_7d": 3,
    "new_wiki_7d": 10,
    "unsynth_days": 14,   # si hace >14 días que no se sintetiza, aunque densidad baja, disparar
}


@dataclass
class DensitySnapshot:
    new_decisions_7d: int
    new_errors_7d: int
    new_wiki_7d: int
    days_since_last_synthesis: float
    should_trigger: bool
    reason: str


def _read_counts(db_path: Path) -> dict:
    """Cuenta señales frescas usando sqlite3 sync (más simple que asyncio para una lectura)."""
    conn = sqlite3.connect(str(db_path))
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=7)).isoformat()
    res = {
        "new_decisions_7d": 0,
        "new_errors_7d": 0,
        "new_wiki_7d": 0,
    }
    try:
        res["new_decisions_7d"] = conn.execute(
            "SELECT COUNT(*) FROM decisions WHERE valid_from >= ?", (cutoff,)
        ).fetchone()[0]
    except sqlite3.OperationalError:
        pass
    try:
        res["new_errors_7d"] = conn.execute(
            "SELECT COUNT(*) FROM errors WHERE created_at >= ?", (cutoff,)
        ).fetchone()[0]
    except sqlite3.OperationalError:
        pass
    try:
        res["new_wiki_7d"] = conn.execute(
            "SELECT COUNT(*) FROM wiki_pages WHERE updated_at >= ?", (cutoff,)
        ).fetchone()[0]
    except sqlite3.OperationalError:
        pass
    # Última síntesis
    last: str | None = None
    try:
        row = conn.execute(
            "SELECT MAX(ran_at) FROM dreaming_log WHERE phase = 'deep'"
        ).fetchone()
        last = row[0] if row else None
    except sqlite3.OperationalError:
        last = None
    conn.close()

    days_since = 999.0
    if last:
        try:
            dt = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            days_since = (now - dt).total_seconds() / 86400
        except ValueError:
            pass
    res["days_since_last_synthesis"] = days_since
    return res


def check_density(db_path: Path, thresholds: dict | None = None) -> DensitySnapshot:
    t = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    raw = _read_counts(db_path)

    reasons = []
    if raw["new_decisions_7d"] >= t["new_decisions_7d"]:
        reasons.append(f"decisiones(7d)={raw['new_decisions_7d']}≥{t['new_decisions_7d']}")
    if raw["new_errors_7d"] >= t["new_errors_7d"]:
        reasons.append(f"errores(7d)={raw['new_errors_7d']}≥{t['new_errors_7d']}")
    if raw["new_wiki_7d"] >= t["new_wiki_7d"]:
        reasons.append(f"wiki(7d)={raw['new_wiki_7d']}≥{t['new_wiki_7d']}")
    if raw["days_since_last_synthesis"] >= t["unsynth_days"]:
        reasons.append(f"unsynth_days={raw['days_since_last_synthesis']:.0f}≥{t['unsynth_days']}")

    return DensitySnapshot(
        new_decisions_7d=raw["new_decisions_7d"],
        new_errors_7d=raw["new_errors_7d"],
        new_wiki_7d=raw["new_wiki_7d"],
        days_since_last_synthesis=raw["days_since_last_synthesis"],
        should_trigger=bool(reasons),
        reason="; ".join(reasons) if reasons else "densidad baja, sin trigger",
    )


async def _run_dream_deep(db_path: Path, min_score: float) -> list[dict]:
    db = ApexContextDB(str(db_path))
    return await db.dream_deep(min_score=min_score)


# ── Re-rank con el curador (Sprint 18, opt-in) ────────────────────────────

def rerank_with_curator(query: str, results: list[dict],
                        db_path: Path | str | None = None) -> list[dict]:
    """Reordena los resultados de búsqueda usando el curador local.

    Sin curador —o si la llamada al modelo falla— devuelve la lista tal cual:
    el orden BM25 manda. El curador REORDENA, nunca descarta: el conjunto de
    resultados es el mismo, solo cambia el orden.
    """
    if not results:
        return results
    if _curator is None:
        return results
    curador = _curator.get_curator(db_path=db_path)
    if not curador.enabled:
        return results
    docs = [str(r.get("content", "")) for r in results]
    orden = curador.rerank(query, docs)
    if not orden or len(orden) != len(results):
        return results
    if sorted(orden) != list(range(len(results))):
        # Orden no válido: antes la heurística que una permutación rota.
        return results
    return [results[i] for i in orden]


def _render_synthesis(snapshot: DensitySnapshot, promoted: list[dict]) -> str:
    now = datetime.now(timezone.utc)
    lines = [
        f"# Synthesis — {now.strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "## Densidad",
        "",
        f"- Nuevas decisiones (7d): {snapshot.new_decisions_7d}",
        f"- Nuevos errores (7d): {snapshot.new_errors_7d}",
        f"- Wiki updates (7d): {snapshot.new_wiki_7d}",
        f"- Días desde última síntesis: {snapshot.days_since_last_synthesis:.1f}",
        f"- Trigger: {snapshot.reason}",
        "",
    ]
    if not promoted:
        lines.append("Dream Deep no promovió señales (todas bajo umbral).")
        return "\n".join(lines)

    # Agrupar por source (decision/error/component/...)
    by_source: dict[str, list[dict]] = {}
    for p in promoted:
        by_source.setdefault(p.get("source", "other"), []).append(p)

    lines.append(f"## Promovidas ({len(promoted)})")
    lines.append("")
    for source, items in sorted(by_source.items(), key=lambda x: -len(x[1])):
        lines.append(f"### {source.title()} ({len(items)})")
        lines.append("")
        for it in sorted(items, key=lambda x: -x.get("score", 0))[:10]:
            score = it.get("score", 0)
            lines.append(f"- **[{score:.2f}]** {it.get('content', '')[:180]}")
            if it.get("reasoning"):
                lines.append(f"  - Reasoning: {it['reasoning'][:160]}")
        lines.append("")

    lines.append("## Cómo usar este informe")
    lines.append("")
    lines.append("Las señales promovidas ya están en `wiki_pages` (tipo `dreaming`). ")
    lines.append("Revisarlas con `apex_search(\"<término>\")` y, si validan algún ")
    lines.append("patrón estable, promoverlas manualmente a `wiki/concepts/` o ")
    lines.append("`wiki/entities/` con `apex_wiki_add`.")
    return "\n".join(lines)


def synthesize(
    project_root: Path,
    force: bool = False,
    min_score: float = 0.6,
    thresholds: dict | None = None,
) -> dict:
    """Punto de entrada síncrono."""
    db_path = project_root / ".apex" / "context.db"
    if not db_path.exists():
        return {"ok": False, "reason": f"context.db no encontrada en {db_path}"}

    snapshot = check_density(db_path, thresholds=thresholds)
    if not snapshot.should_trigger and not force:
        return {
            "ok": True,
            "triggered": False,
            "snapshot": asdict(snapshot),
            "promoted": 0,
        }

    # Ejecutar dream_deep
    try:
        promoted = asyncio.run(_run_dream_deep(db_path, min_score))
    except RuntimeError:
        # Si ya hay un event loop, crear uno nuevo en thread
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            promoted = pool.submit(
                lambda: asyncio.new_event_loop().run_until_complete(
                    _run_dream_deep(db_path, min_score)
                )
            ).result()

    md = _render_synthesis(snapshot, promoted)
    out_dir = project_root / ".apex" / "wiki" / "synthesis"
    out_dir.mkdir(parents=True, exist_ok=True)
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_path = out_dir / f"{date}.md"
    out_path.write_text(md, encoding="utf-8")

    return {
        "ok": True,
        "triggered": True,
        "snapshot": asdict(snapshot),
        "promoted": len(promoted),
        "report": str(out_path),
    }


# --- CLI ---

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--project-root", type=Path, default=Path("."))
    p.add_argument("--force", action="store_true",
                   help="Ejecuta dream_deep aunque la densidad sea baja")
    p.add_argument("--min-score", type=float, default=0.6)
    args = p.parse_args(argv)

    res = synthesize(args.project_root.resolve(), force=args.force, min_score=args.min_score)
    print(json.dumps(res, indent=2, ensure_ascii=False, default=str))
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
