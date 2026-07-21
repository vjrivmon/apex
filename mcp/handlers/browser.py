"""APEX MCP handler: browser."""
from __future__ import annotations

# Imports que el refactor a handlers dejó fuera al cortar del monolito.
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[2] / 'lib'))
from pathlib import Path
from mcp.types import TextContent
import browser_trace as _browser
from apex_handlers._common import find_project_root as _find_project_root
import asyncio
from typing import Any


async def handle_apex_browser_trace(db: Any, arguments: dict) -> Any:
    """Handler for apex_browser_trace."""
    url = arguments["url"]
    nav_timeout = float(arguments.get("nav_timeout_s", 25))
    settle_ms = int(arguments.get("settle_ms", 1500))
    capture_dom = bool(arguments.get("capture_dom", True))
    save_jsonl = bool(arguments.get("save_jsonl", False))
    use_fallback = bool(arguments.get("use_fallback", True))
    include_dom = bool(arguments.get("include_dom_in_output", False))

    trace = await asyncio.to_thread(
        _browser.trace_url,
        url,
        nav_timeout_s=nav_timeout,
        settle_ms=settle_ms,
        capture_dom=capture_dom,
        use_fallback=use_fallback,
    )

    md = _browser.trace_to_markdown(trace)
    saved_path: Path | None = None
    if save_jsonl:
        project_root = _find_project_root()
        slug = (
            "".join(c if c.isalnum() else "-" for c in url)
            .strip("-")[:60]
            or "trace"
        )
        stamp = trace.started_at or 0
        saved_path = _browser.trace_to_jsonl(
            trace,
            project_root / ".apex" / "browser-traces" / f"{slug}-{int(stamp)}.json",
            include_dom=True,
        )

    sections = [md]
    third = _browser.third_party_domains(trace)
    if third:
        sections.append(
            "## Dominios externos\n" + "\n".join(f"- {d}" for d in third[:25])
        )
    if saved_path:
        sections.append(f"\n_Trace guardado en {saved_path}_")
    if include_dom and trace.dom_html:
        sections.append("## DOM (outerHTML)\n```html\n" + trace.dom_html[:200_000] + "\n```")
    return [TextContent(type="text", text="\n\n".join(sections))]

