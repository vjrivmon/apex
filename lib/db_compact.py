"""DB compaction for APEX context.db.

Provides periodic cleanup of log/archive tables that grow indefinitely,
plus VACUUM for reclaiming disk space.

Usage (from MCP tool or hook):
    from lib.db_compact import apex_db_compact
    stats = apex_db_compact("/path/to/.apex/context.db", retention_days=30)

CLI:
    python -m lib.db_compact --db .apex/context.db --retention-days 30
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path


# Tables with continuously growing rows (logs, traces, archives).
#
# La columna de tiempo es la que REALMENTE existe en cada tabla. Antes,
# `advisor_reviews` pedía `reviewed_at` y `tool_output_archive` pedía
# `archived_at`: ninguna de las dos existe, así que el DELETE lanzaba
# OperationalError y el error quedaba escondido en `stats["errors"]`, que
# nadie lee. Las dos tablas —que son justo las que más crecen— nunca se
# compactaban. La comprobación de columnas de más abajo lo hace explícito.
_LOG_TABLES = {
    "tool_call_log": "created_at",
    "tool_output_archive": "created_at",
    "reasoning_traces": "created_at",
    "advisor_reviews": "triggered_at",
    "advisor_advice": "created_at",
    "advice_outcomes": "computed_at",
    "skill_handoffs": "created_at",
    "advisor_tuning_history": "applied_at",
}


def _get_db(db_path: str | Path) -> sqlite3.Connection:
    """Open a sync connection with standard PRAGMAs."""
    conn = sqlite3.connect(str(db_path), timeout=5.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def apex_db_compact(
    db_path: str | Path,
    retention_days: int = 30,
) -> dict:
    """Compact context.db: clean old log rows + VACUUM.

    Args:
        db_path: path to the SQLite database
        retention_days: delete rows older than this many days

    Returns:
        dict with stats: rows_deleted, vacuum_before_kb, vacuum_after_kb,
        tables_cleaned, errors
    """
    db_path = Path(db_path)
    if not db_path.exists():
        return {"error": f"database not found: {db_path}", "rows_deleted": 0}

    cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
    stats = {
        "rows_deleted": 0,
        "vacuum_before_kb": 0,
        "vacuum_after_kb": 0,
        "tables_cleaned": [],
        "tables_skipped": [],
        "errors": [],
    }

    conn = _get_db(db_path)
    try:
        # Check which tables actually exist
        existing = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }

        # Clean old rows from log tables
        for table, ts_column in _LOG_TABLES.items():
            if table not in existing:
                stats["tables_skipped"].append(
                    f"{table}: no existe en esta base"
                )
                continue
            columns = {
                row[1]
                for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
            }
            if ts_column not in columns:
                # Fallo de esquema: se dice en voz alta, no se traga.
                stats["tables_skipped"].append(
                    f"{table}: no tiene la columna {ts_column!r} "
                    f"(columnas: {', '.join(sorted(columns))})"
                )
                continue
            try:
                cursor = conn.execute(
                    f"DELETE FROM {table} WHERE {ts_column} < ?",
                    (cutoff,),
                )
                deleted = cursor.rowcount
                if deleted > 0:
                    stats["rows_deleted"] += deleted
                    stats["tables_cleaned"].append(table)
            except sqlite3.Error as exc:
                stats["errors"].append(f"{table}: {exc}")

        conn.commit()

        # Measure DB size before VACUUM
        page_count = conn.execute("PRAGMA page_count").fetchone()[0]
        page_size = conn.execute("PRAGMA page_size").fetchone()[0]
        stats["vacuum_before_kb"] = round((page_count * page_size) / 1024, 1)

        # VACUUM
        try:
            conn.execute("VACUUM")
        except sqlite3.Error as exc:
            stats["errors"].append(f"VACUUM: {exc}")

        # Measure DB size after VACUUM
        page_count = conn.execute("PRAGMA page_count").fetchone()[0]
        page_size = conn.execute("PRAGMA page_size").fetchone()[0]
        stats["vacuum_after_kb"] = round((page_count * page_size) / 1024, 1)

    finally:
        conn.close()

    return stats


def main() -> int:
    """CLI: compacta una `context.db` y publica las estadísticas en JSON."""
    parser = argparse.ArgumentParser(
        description="Compacta la context.db de un proyecto APEX"
    )
    parser.add_argument(
        "--db", required=True, help="ruta de la context.db a compactar"
    )
    parser.add_argument(
        "--retention-days", type=int, default=30,
        help="elimina filas de log más antiguas que N días (por defecto 30)",
    )
    args = parser.parse_args()
    stats = apex_db_compact(args.db, retention_days=args.retention_days)
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    # 1 si la compactación falló; 0 si fue limpia o sólo hubo skips.
    return 1 if stats.get("errors") else 0


if __name__ == "__main__":
    raise SystemExit(main())
