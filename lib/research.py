"""Research helper para fase 0/2 (Sprint 10.2).

Fetch + extract de páginas web con dos modos:

- **Static**: `httpx.get(url)` para sitios renderizados en servidor.
- **SPA**: `chromium --headless --dump-dom URL` con virtual time budget
  para que el JS termine de ejecutar antes del dump. Necesario en
  landing pages SaaS modernas (Next.js, Astro hidrated, etc.).

Sin dependencia obligatoria de Scrapling. Si está instalado, se usa
como fallback con anti-detection. Si no, httpx cubre el 80% de casos.

API:
- `fetch_static(url)` — devuelve HTML por httpx (timeout corto)
- `fetch_spa(url, virtual_time_ms)` — chromium dump-dom
- `fetch_auto(url, ...)` — primero static, si HTML <2KB o tiene `<noscript>`
  importante, cae a SPA.
- `extract_signals(html)` — H1, H2, navegación, CTAs, paleta, fuentes.
- `summarize_competitor(url)` — combo de fetch_auto + extract_signals
  apto para wiki entry.
"""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path

DEFAULT_TIMEOUT_S = 10
DEFAULT_VTIME_MS = 8000  # virtual-time-budget para SPAs


@dataclass
class Signals:
    url: str
    title: str = ""
    h1: list[str] = field(default_factory=list)
    h2: list[str] = field(default_factory=list)
    nav_links: list[str] = field(default_factory=list)
    ctas: list[str] = field(default_factory=list)
    colors: list[str] = field(default_factory=list)
    fonts: list[str] = field(default_factory=list)
    raw_size: int = 0
    fetcher: str = "static"

    def to_dict(self) -> dict:
        return asdict(self)


# ── Fetchers ─────────────────────────────────────────────────────────────

def fetch_static(url: str, timeout: float = DEFAULT_TIMEOUT_S) -> str:
    """HTML estático vía httpx. Sin renderizar JS."""
    try:
        import httpx
    except ImportError:
        return ""
    try:
        r = httpx.get(url, timeout=timeout, follow_redirects=True,
                      headers={"User-Agent": "apex-research/1.0"})
        return r.text if r.status_code == 200 else ""
    except Exception:
        return ""


def fetch_spa(url: str, virtual_time_ms: int = DEFAULT_VTIME_MS,
              chromium_bin: str | None = None) -> str:
    """SPA con chromium --headless --dump-dom. Requiere chromium en PATH."""
    bin_name = chromium_bin or "chromium"
    cmd = [
        bin_name, "--headless", "--no-sandbox", "--disable-gpu",
        f"--virtual-time-budget={virtual_time_ms}",
        "--dump-dom", url,
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return r.stdout if r.returncode == 0 else ""
    except FileNotFoundError:
        # Fallback: probar 'chromium-browser', 'google-chrome'
        for alt in ("chromium-browser", "google-chrome", "chrome"):
            try:
                cmd[0] = alt
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                if r.returncode == 0:
                    return r.stdout
            except FileNotFoundError:
                continue
        return ""
    except subprocess.TimeoutExpired:
        return ""
    except Exception:
        return ""


def fetch_auto(url: str, prefer_spa: bool = False) -> tuple[str, str]:
    """Devuelve (html, fetcher) eligiendo el mejor método.

    Heurística: si prefer_spa=True o la respuesta estática es muy pequeña
    o tiene el bloque típico de "you need JavaScript enabled", cae a SPA.
    """
    if prefer_spa:
        spa = fetch_spa(url)
        if spa:
            return spa, "spa"

    static = fetch_static(url)
    if static and len(static) > 2000 and "noscript" not in static.lower()[:1000]:
        return static, "static"

    spa = fetch_spa(url)
    if spa:
        return spa, "spa"
    return static, "static"


# ── Extracción ───────────────────────────────────────────────────────────

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.I | re.S)
_H2_RE = re.compile(r"<h2[^>]*>(.*?)</h2>", re.I | re.S)
_BUTTON_RE = re.compile(
    r'<(?:a|button)[^>]*?(?:class="[^"]*(?:btn|button|cta)[^"]*")[^>]*>(.*?)</(?:a|button)>',
    re.I | re.S,
)
_NAV_RE = re.compile(r"<nav[^>]*>(.*?)</nav>", re.I | re.S)
_LINK_TEXT_RE = re.compile(r"<a[^>]*>(.*?)</a>", re.I | re.S)
_HEX_RE = re.compile(r"#[0-9A-Fa-f]{6}\b")
_FONT_FAMILY_RE = re.compile(
    r"font-family\s*:\s*([^;\"\'}]+)", re.I,
)


def _strip_tags(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html or "").strip()


def _dedupe_keep_order(items):
    seen = set()
    out = []
    for it in items:
        key = it.lower()
        if key in seen or not it:
            continue
        seen.add(key)
        out.append(it)
    return out


def extract_signals(url: str, html: str, fetcher: str = "static") -> Signals:
    s = Signals(url=url, fetcher=fetcher, raw_size=len(html or ""))
    if not html:
        return s

    m = _TITLE_RE.search(html)
    if m:
        s.title = _strip_tags(m.group(1))[:200]

    s.h1 = _dedupe_keep_order(
        _strip_tags(x)[:200] for x in _H1_RE.findall(html)
    )[:5]
    s.h2 = _dedupe_keep_order(
        _strip_tags(x)[:200] for x in _H2_RE.findall(html)
    )[:10]

    nav_match = _NAV_RE.search(html)
    if nav_match:
        nav_html = nav_match.group(1)
        s.nav_links = _dedupe_keep_order(
            _strip_tags(x) for x in _LINK_TEXT_RE.findall(nav_html)
        )[:12]

    s.ctas = _dedupe_keep_order(
        _strip_tags(x) for x in _BUTTON_RE.findall(html)
    )[:8]

    s.colors = _dedupe_keep_order(_HEX_RE.findall(html))[:12]

    fonts = []
    for raw in _FONT_FAMILY_RE.findall(html):
        for token in raw.split(","):
            token = token.strip().strip("'\"")
            if token and not token.lower() in {"sans-serif", "serif", "monospace"}:
                fonts.append(token)
    s.fonts = _dedupe_keep_order(fonts)[:6]

    return s


# ── API conveniente ──────────────────────────────────────────────────────

def summarize_competitor(url: str, prefer_spa: bool = False) -> Signals:
    """Combo de fetch_auto + extract_signals."""
    html, fetcher = fetch_auto(url, prefer_spa=prefer_spa)
    return extract_signals(url, html, fetcher=fetcher)


def signals_to_markdown(s: Signals) -> str:
    """Convierte Signals en bloque Markdown para inyectar en wiki."""
    lines = [f"# Research: {s.url}", ""]
    lines.append(f"- Title: {s.title or '(sin title)'}")
    lines.append(f"- Fetcher: {s.fetcher} · {s.raw_size:,} bytes")
    if s.h1:
        lines.append(f"- H1: {' | '.join(s.h1)}")
    if s.h2:
        lines.append(f"- H2 ({len(s.h2)}): {' | '.join(s.h2[:5])}")
    if s.nav_links:
        lines.append(f"- Nav: {', '.join(s.nav_links)}")
    if s.ctas:
        lines.append(f"- CTAs: {', '.join(s.ctas)}")
    if s.colors:
        lines.append(f"- Paleta: {', '.join(s.colors)}")
    if s.fonts:
        lines.append(f"- Fuentes: {', '.join(s.fonts)}")
    return "\n".join(lines) + "\n"
