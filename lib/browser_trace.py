"""Browser trace vía Chrome DevTools Protocol nativo (Sprint 11.1).

Captura una sesión real de navegación con Chrome para obtener señales que
``lib/research.py`` no puede sacar de un `--dump-dom` estático:

- **DOM snapshot** post-load + post-settle (DOM.getDocument).
- **Network log** completo (Network.requestWillBeSent / responseReceived /
  loadingFinished / loadingFailed): URLs, status, mimeType, latencia.
- **Console events** (Runtime.consoleAPICalled, Log.entryAdded): warnings,
  errores JS, CSP violations.
- **Page lifecycle** (Page.lifecycleEvent): firstPaint, load,
  networkAlmostIdle, networkIdle.

Casos de uso:

- Fase 02 (research competidor): ver qué APIs llama el SaaS, qué tracking
  mete, qué fonts/CSS carga.
- Fase 11 (smoke-test pre-deploy): navegar a la home recién deployada y
  verificar que no hay 5xx ni errores de consola.
- Fase 13 (apex-doctor): replicar bugs reportados con trace.

Modo principal: ``chrome --headless=new --remote-debugging-port`` y un
cliente WebSocket asyncio nativo (sólo dependencia: ``websockets``).

Fallback: si Chrome no arranca o se cae, e ``playwright`` está
disponible, se reintenta con un BrowserContext real.

API:

- ``launch_chrome(port=0, headless=True) -> ChromeProcess``
- ``discover_targets(port) -> list[Target]``
- ``trace_url(url, ...) -> Trace``  (síncrono, oculta el asyncio)
- ``trace_to_markdown(trace) -> str``
- ``trace_to_jsonl(trace, path)``
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import socket
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

DEFAULT_NAV_TIMEOUT_S = 25
DEFAULT_SETTLE_MS = 1500
CHROME_BIN_CANDIDATES = (
    "google-chrome",
    "chromium",
    "chromium-browser",
    "chrome",
    "google-chrome-stable",
)


# ── Modelos ──────────────────────────────────────────────────────────────


@dataclass
class NetworkEvent:
    request_id: str
    url: str
    method: str = "GET"
    status: int | None = None
    mime_type: str = ""
    resource_type: str = ""
    duration_ms: float | None = None
    failed: bool = False
    error_text: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ConsoleEvent:
    level: str  # log, info, warning, error
    text: str
    source: str = "console"  # console | log | exception

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Target:
    target_id: str
    title: str
    url: str
    ws_url: str
    type: str = "page"


@dataclass
class Trace:
    url: str
    final_url: str = ""
    title: str = ""
    fetcher: str = "cdp"  # "cdp" | "playwright"
    started_at: float = 0.0
    duration_ms: float = 0.0
    dom_size: int = 0
    dom_html: str = ""
    network: list[NetworkEvent] = field(default_factory=list)
    console: list[ConsoleEvent] = field(default_factory=list)
    lifecycle: list[str] = field(default_factory=list)
    error: str = ""

    def to_dict(self, *, include_dom: bool = False) -> dict:
        data = asdict(self)
        if not include_dom:
            data.pop("dom_html", None)
        return data

    @property
    def num_requests(self) -> int:
        return len(self.network)

    @property
    def num_failed(self) -> int:
        return sum(1 for n in self.network if n.failed)

    @property
    def num_5xx(self) -> int:
        return sum(1 for n in self.network if n.status and n.status >= 500)

    @property
    def num_console_errors(self) -> int:
        return sum(1 for c in self.console if c.level == "error")


# ── Helpers ──────────────────────────────────────────────────────────────


def _pick_chrome_bin(explicit: str | None = None) -> str | None:
    if explicit and Path(explicit).exists():
        return explicit
    for name in CHROME_BIN_CANDIDATES:
        path = shutil.which(name)
        if path:
            return path
    return None


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ── Chrome launcher ──────────────────────────────────────────────────────


@dataclass
class ChromeProcess:
    proc: subprocess.Popen
    port: int
    user_data_dir: Path

    def stop(self) -> None:
        if self.proc.poll() is None:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        if self.user_data_dir.exists():
            shutil.rmtree(self.user_data_dir, ignore_errors=True)


def launch_chrome(
    port: int = 0,
    headless: bool = True,
    chrome_bin: str | None = None,
    extra_flags: list[str] | None = None,
    wait_ready_s: float = 5.0,
) -> ChromeProcess:
    """Lanza Chrome con CDP en ``port`` (0 = libre). Bloquea hasta /json/version."""
    binary = _pick_chrome_bin(chrome_bin)
    if not binary:
        raise RuntimeError(
            "No se encontró Chrome/Chromium. Instala google-chrome o pasa chrome_bin."
        )
    actual_port = port or _free_port()
    user_dir = Path(tempfile.mkdtemp(prefix="apex-chrome-"))
    flags = [
        binary,
        f"--remote-debugging-port={actual_port}",
        f"--user-data-dir={user_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-gpu",
        "--disable-dev-shm-usage",
        "--no-sandbox",
    ]
    if headless:
        flags.append("--headless=new")
    if extra_flags:
        flags.extend(extra_flags)
    flags.append("about:blank")

    proc = subprocess.Popen(
        flags,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env={**os.environ, "LANG": "en_US.UTF-8"},
    )

    deadline = time.time() + wait_ready_s
    while time.time() < deadline:
        if proc.poll() is not None:
            shutil.rmtree(user_dir, ignore_errors=True)
            raise RuntimeError(f"Chrome murió antes de abrir el puerto {actual_port}")
        try:
            import httpx

            r = httpx.get(f"http://127.0.0.1:{actual_port}/json/version", timeout=0.5)
            if r.status_code == 200:
                return ChromeProcess(proc=proc, port=actual_port, user_data_dir=user_dir)
        except Exception:
            time.sleep(0.15)
    proc.terminate()
    shutil.rmtree(user_dir, ignore_errors=True)
    raise RuntimeError(f"Chrome no respondió en {wait_ready_s}s en :{actual_port}")


def discover_targets(port: int) -> list[Target]:
    """Lista de targets (pestañas + service workers) vía /json/list."""
    import httpx

    r = httpx.get(f"http://127.0.0.1:{port}/json/list", timeout=2.0)
    r.raise_for_status()
    targets: list[Target] = []
    for item in r.json():
        ws = item.get("webSocketDebuggerUrl")
        if not ws:
            continue
        targets.append(
            Target(
                target_id=item.get("id", ""),
                title=item.get("title", ""),
                url=item.get("url", ""),
                ws_url=ws,
                type=item.get("type", "page"),
            )
        )
    return targets


# ── CDP client async ─────────────────────────────────────────────────────


class _CDPSession:
    """Sesión CDP minimal sobre un único websocket.

    Patrón: cada ``send()`` envía un mensaje JSON-RPC y luego consume
    mensajes del socket hasta encontrar la respuesta con el ``id``
    correspondiente. Los mensajes que son eventos (``method``) o
    respuestas de otros ids se acumulan en ``self.events`` /
    ``self._inbox`` para no perderse.

    Esto evita la fragilidad de tener un reader-task concurrente con
    varios ``send()`` compartiendo el mismo websocket.
    """

    def __init__(self, ws):
        self.ws = ws
        self._next_id = 0
        self.events: list[dict] = []

    async def fire(self, method: str, params: dict | None = None) -> int:
        """Envía sin esperar respuesta. Útil para ``Page.navigate``, que en
        algunas builds de Chrome no devuelve respuesta hasta que la
        navegación falla — y entonces nos colgaríamos esperándola."""
        self._next_id += 1
        msg_id = self._next_id
        payload = {"id": msg_id, "method": method, "params": params or {}}
        await self.ws.send(json.dumps(payload))
        return msg_id

    async def send(
        self, method: str, params: dict | None = None, timeout: float = 10.0
    ):
        self._next_id += 1
        msg_id = self._next_id
        payload = {"id": msg_id, "method": method, "params": params or {}}
        await self.ws.send(json.dumps(payload))

        async with asyncio.timeout(timeout):
            while True:
                raw = await self.ws.recv()
                msg = json.loads(raw)
                if msg.get("id") == msg_id:
                    if "error" in msg:
                        raise RuntimeError(
                            msg["error"].get("message", "CDP error")
                        )
                    return msg.get("result", {})
                if "method" in msg:
                    self.events.append(msg)

    async def drain(self, duration_s: float) -> None:
        """Lee eventos durante ``duration_s`` segundos y los acumula."""
        deadline = asyncio.get_running_loop().time() + duration_s
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                return
            try:
                raw = await asyncio.wait_for(self.ws.recv(), timeout=remaining)
            except asyncio.TimeoutError:
                return
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            if "method" in msg:
                self.events.append(msg)

    async def drain_until(
        self, duration_s: float, *, predicate
    ) -> None:
        """Lee eventos durante ``duration_s`` o hasta que ``predicate`` sea True."""
        deadline = asyncio.get_running_loop().time() + duration_s
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                return
            try:
                raw = await asyncio.wait_for(self.ws.recv(), timeout=remaining)
            except asyncio.TimeoutError:
                return
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            if "method" in msg:
                self.events.append(msg)
                if predicate(msg):
                    return


async def _trace_with_cdp(
    ws_url: str,
    url: str,
    nav_timeout_s: float,
    settle_ms: int,
    capture_dom: bool,
) -> Trace:
    import websockets

    started = time.time()
    trace = Trace(url=url, started_at=started)

    network_starts: dict[str, float] = {}

    async with websockets.connect(ws_url, max_size=20 * 1024 * 1024) as ws:
        sess = _CDPSession(ws)

        await sess.send("Page.enable")
        await sess.send("Network.enable")
        await sess.send("Runtime.enable")
        await sess.send("Log.enable")
        await sess.send("Page.setLifecycleEventsEnabled", {"enabled": True})

        # Page.navigate en algunas builds no devuelve respuesta inmediata;
        # en su lugar disparamos y nos guiamos por los lifecycle events.
        await sess.fire("Page.navigate", {"url": url})

        # Esperar a que la navegación arranque (frameStartedNavigating o
        # primera Network.requestWillBeSent), y a partir de ese punto
        # contar load + networkIdle del nuevo frame. Sin este reset,
        # Chrome emite "networkIdle" del about:blank previo y rompemos
        # antes de tiempo.
        nav_started = {"v": False}
        seen = {"load": False, "networkIdle": False}

        def _ready(msg: dict) -> bool:
            method = msg.get("method", "")
            if method in ("Page.frameStartedNavigating", "Page.frameStartedLoading"):
                nav_started["v"] = True
                return False
            if method == "Network.requestWillBeSent":
                nav_started["v"] = True
                return False
            if method == "Page.lifecycleEvent":
                name = msg["params"].get("name", "")
                if not nav_started["v"]:
                    return False  # ignora lifecycle pre-navegación
                if name in seen:
                    seen[name] = True
                return seen["load"] and seen["networkIdle"]
            return False

        budget = max(0.5, nav_timeout_s - (time.time() - started))
        await sess.drain_until(budget, predicate=_ready)

        # Settle final para CSS-in-JS, fonts, network tail.
        await sess.drain(settle_ms / 1000.0)

        # Pasada 1: lifecycle, requests, console.
        net_index: dict[str, NetworkEvent] = {}
        for ev in sess.events:
            method = ev.get("method", "")
            params = ev.get("params", {})
            if method == "Page.lifecycleEvent":
                name = params.get("name", "")
                if name and name not in trace.lifecycle:
                    trace.lifecycle.append(name)
            elif method == "Network.requestWillBeSent":
                rid = params.get("requestId", "")
                req = params.get("request", {})
                network_starts[rid] = params.get("timestamp", time.time())
                ne = NetworkEvent(
                    request_id=rid,
                    url=req.get("url", ""),
                    method=req.get("method", "GET"),
                    resource_type=params.get("type", ""),
                )
                trace.network.append(ne)
                net_index[rid] = ne
            elif method == "Runtime.consoleAPICalled":
                level = params.get("type", "log")
                args = params.get("args", [])
                text = " ".join(_stringify_remote(a) for a in args)
                trace.console.append(ConsoleEvent(level=level, text=text[:500]))
            elif method == "Runtime.exceptionThrown":
                exc = params.get("exceptionDetails", {})
                text = exc.get("text", "")
                if exc.get("exception", {}).get("description"):
                    text = exc["exception"]["description"]
                trace.console.append(
                    ConsoleEvent(level="error", text=text[:500], source="exception")
                )
            elif method == "Log.entryAdded":
                entry = params.get("entry", {})
                trace.console.append(
                    ConsoleEvent(
                        level=entry.get("level", "log"),
                        text=entry.get("text", "")[:500],
                        source="log",
                    )
                )

        # Pasada 2: emparejar respuestas con sus requests.
        for ev in sess.events:
            method = ev.get("method", "")
            params = ev.get("params", {})
            if method == "Network.responseReceived":
                ne = net_index.get(params.get("requestId", ""))
                if ne:
                    resp = params.get("response", {})
                    ne.status = resp.get("status")
                    ne.mime_type = resp.get("mimeType", "")
            elif method == "Network.loadingFinished":
                rid = params.get("requestId", "")
                ne = net_index.get(rid)
                start = network_starts.get(rid)
                if ne and start:
                    end = params.get("timestamp", time.time())
                    ne.duration_ms = round((end - start) * 1000, 1)
            elif method == "Network.loadingFailed":
                ne = net_index.get(params.get("requestId", ""))
                if ne:
                    ne.failed = True
                    ne.error_text = params.get("errorText", "")

        # Title + URL final via Runtime.evaluate (más fiable que Target.getTargets).
        async def _eval(expr: str) -> str:
            try:
                r = await sess.send(
                    "Runtime.evaluate",
                    {"expression": expr, "returnByValue": True},
                    timeout=5.0,
                )
                return str(r.get("result", {}).get("value", ""))
            except Exception:
                return ""

        trace.title = await _eval("document.title") or trace.title
        final = await _eval("location.href")
        if final:
            trace.final_url = final
        else:
            trace.final_url = trace.final_url or url

        if capture_dom:
            html = await _eval("document.documentElement.outerHTML")
            if html:
                trace.dom_html = html
                trace.dom_size = len(html)
            else:
                trace.error = "DOM capture failed via Runtime.evaluate"

    trace.duration_ms = round((time.time() - started) * 1000, 1)
    return trace


def _stringify_remote(arg: dict) -> str:
    if "value" in arg:
        return str(arg["value"])
    if "description" in arg:
        return arg["description"]
    if "unserializableValue" in arg:
        return str(arg["unserializableValue"])
    return arg.get("type", "?")


# ── Playwright fallback ──────────────────────────────────────────────────


def _trace_with_playwright(url: str, nav_timeout_s: float, capture_dom: bool) -> Trace:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise RuntimeError("Playwright no disponible para fallback") from e

    started = time.time()
    trace = Trace(url=url, started_at=started, fetcher="playwright")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        def on_request(req):
            trace.network.append(
                NetworkEvent(
                    request_id=str(id(req)),
                    url=req.url,
                    method=req.method,
                    resource_type=req.resource_type,
                )
            )

        def on_response(resp):
            for n in trace.network:
                if n.url == resp.url and n.status is None:
                    n.status = resp.status
                    n.mime_type = resp.headers.get("content-type", "").split(";")[0]
                    break

        def on_request_failed(req):
            for n in trace.network:
                if n.url == req.url:
                    n.failed = True
                    n.error_text = req.failure or ""
                    break

        def on_console(msg):
            trace.console.append(ConsoleEvent(level=msg.type, text=msg.text[:500]))

        def on_pageerror(err):
            trace.console.append(
                ConsoleEvent(level="error", text=str(err)[:500], source="exception")
            )

        page.on("request", on_request)
        page.on("response", on_response)
        page.on("requestfailed", on_request_failed)
        page.on("console", on_console)
        page.on("pageerror", on_pageerror)

        try:
            page.goto(url, timeout=int(nav_timeout_s * 1000))
            page.wait_for_load_state("networkidle", timeout=int(nav_timeout_s * 1000))
            trace.final_url = page.url
            trace.title = page.title()
            if capture_dom:
                trace.dom_html = page.content()
                trace.dom_size = len(trace.dom_html)
        except Exception as e:
            trace.error = f"playwright nav failed: {e}"
        finally:
            context.close()
            browser.close()

    trace.duration_ms = round((time.time() - started) * 1000, 1)
    return trace


# ── API pública ──────────────────────────────────────────────────────────


def trace_url(
    url: str,
    *,
    nav_timeout_s: float = DEFAULT_NAV_TIMEOUT_S,
    settle_ms: int = DEFAULT_SETTLE_MS,
    capture_dom: bool = True,
    chrome_bin: str | None = None,
    chrome_port: int = 0,
    use_fallback: bool = True,
) -> Trace:
    """Captura una sesión de navegación a ``url`` y devuelve un ``Trace``.

    Estrategia:
    1. Lanza Chrome via CDP en ``chrome_port`` (0 = libre).
    2. Localiza la pestaña about:blank y se conecta por WebSocket.
    3. Habilita dominios Page/Network/Runtime/Log y navega.
    4. Espera load + networkIdle (lifecycle events) o ``nav_timeout_s``.
    5. Captura DOM final si ``capture_dom``.
    6. Si todo el bloque CDP falla y ``use_fallback``, intenta Playwright.
    """
    chrome: ChromeProcess | None = None
    try:
        chrome = launch_chrome(port=chrome_port, chrome_bin=chrome_bin)
        targets = discover_targets(chrome.port)
        page_targets = [t for t in targets if t.type == "page"]
        if not page_targets:
            raise RuntimeError("Chrome arrancó pero no expuso ninguna pestaña 'page'")
        ws_url = page_targets[0].ws_url
        return asyncio.run(
            _trace_with_cdp(ws_url, url, nav_timeout_s, settle_ms, capture_dom)
        )
    except Exception as cdp_err:
        if not use_fallback:
            return Trace(url=url, error=f"cdp failed: {cdp_err}")
        try:
            return _trace_with_playwright(url, nav_timeout_s, capture_dom)
        except Exception as pw_err:
            return Trace(
                url=url,
                error=f"cdp failed: {cdp_err} | playwright failed: {pw_err}",
            )
    finally:
        if chrome:
            chrome.stop()


# ── Serializadores ───────────────────────────────────────────────────────


def trace_to_markdown(trace: Trace, *, max_requests: int = 20) -> str:
    lines = [f"# Browser trace: {trace.url}", ""]
    if trace.error:
        lines.append(f"- Error: {trace.error}")
    lines.append(f"- Final URL: {trace.final_url or trace.url}")
    lines.append(f"- Title: {trace.title or '(sin title)'}")
    lines.append(f"- Fetcher: {trace.fetcher} · {trace.duration_ms:.0f}ms")
    lines.append(
        f"- Requests: {trace.num_requests} (failed {trace.num_failed}, 5xx {trace.num_5xx})"
    )
    lines.append(
        f"- Console: {len(trace.console)} (errors {trace.num_console_errors})"
    )
    if trace.lifecycle:
        lines.append(f"- Lifecycle: {' → '.join(trace.lifecycle)}")
    lines.append(f"- DOM size: {trace.dom_size:,} bytes")
    lines.append("")

    if trace.network:
        lines.append("## Network (top requests)")
        sorted_net = sorted(
            trace.network,
            key=lambda n: (n.duration_ms or 0),
            reverse=True,
        )[:max_requests]
        for n in sorted_net:
            status = n.status if n.status is not None else ("FAIL" if n.failed else "?")
            dur = f"{n.duration_ms:.0f}ms" if n.duration_ms is not None else "—"
            lines.append(
                f"- [{status}] {n.method} {n.url[:90]} ({n.resource_type}, {dur})"
            )
        lines.append("")

    if trace.console:
        lines.append("## Console")
        for c in trace.console[:30]:
            lines.append(f"- [{c.level}] {c.text}")
        lines.append("")
    return "\n".join(lines)


def trace_to_jsonl(trace: Trace, path: str | Path, *, include_dom: bool = False) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = trace.to_dict(include_dom=include_dom)
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


# ── Análisis rápido ──────────────────────────────────────────────────────


_THIRD_PARTY_DOMAINS = re.compile(
    r"https?://([^/]+)/", re.I,
)


def third_party_domains(trace: Trace, base_url: str | None = None) -> list[str]:
    """Lista de dominios externos al base_url, deduplicados."""
    base_host = ""
    target = base_url or trace.final_url or trace.url
    m = _THIRD_PARTY_DOMAINS.match(target)
    if m:
        base_host = m.group(1).lower()
    seen: dict[str, int] = {}
    for n in trace.network:
        m2 = _THIRD_PARTY_DOMAINS.match(n.url)
        if not m2:
            continue
        host = m2.group(1).lower()
        if host == base_host or host.endswith("." + base_host):
            continue
        seen[host] = seen.get(host, 0) + 1
    return sorted(seen.keys(), key=lambda h: seen[h], reverse=True)
