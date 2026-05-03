"""Tests del browser_trace (Sprint 11.1).

La mayoría son puros (modelos, parseo, serialización). El test de
integración monta un HTTP server local y dispara Chrome via CDP — sólo
se salta si no hay binario de Chrome en el sistema.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

import browser_trace as bt
from browser_trace import (
    ConsoleEvent,
    NetworkEvent,
    Trace,
    third_party_domains,
    trace_to_jsonl,
    trace_to_markdown,
)


# ── Modelos ──────────────────────────────────────────────────────────────


def test_trace_defaults() -> None:
    t = Trace(url="https://example.com")
    assert t.final_url == ""
    assert t.fetcher == "cdp"
    assert t.network == []
    assert t.console == []
    assert t.num_requests == 0
    assert t.num_failed == 0
    assert t.num_5xx == 0
    assert t.num_console_errors == 0


def test_network_event_to_dict() -> None:
    n = NetworkEvent(
        request_id="r1", url="https://x/y.js", method="GET", status=200,
        mime_type="application/javascript", duration_ms=12.4,
    )
    d = n.to_dict()
    assert d["status"] == 200
    assert d["mime_type"] == "application/javascript"
    assert d["duration_ms"] == 12.4


def test_trace_metrics() -> None:
    t = Trace(url="https://x")
    t.network = [
        NetworkEvent(request_id="1", url="https://x/", status=200),
        NetworkEvent(request_id="2", url="https://x/css", status=404),
        NetworkEvent(request_id="3", url="https://x/api", status=503),
        NetworkEvent(request_id="4", url="https://x/img", failed=True, error_text="net::ERR"),
    ]
    t.console = [
        ConsoleEvent(level="log", text="hi"),
        ConsoleEvent(level="error", text="boom"),
        ConsoleEvent(level="warning", text="deprecated"),
    ]
    assert t.num_requests == 4
    assert t.num_failed == 1
    assert t.num_5xx == 1
    assert t.num_console_errors == 1


def test_trace_to_dict_excludes_dom_by_default() -> None:
    t = Trace(url="https://x", dom_html="<html>...</html>", dom_size=15)
    assert "dom_html" not in t.to_dict()
    assert "dom_html" in t.to_dict(include_dom=True)
    assert t.to_dict()["dom_size"] == 15


# ── Helpers internos ─────────────────────────────────────────────────────


def test_free_port_returns_int() -> None:
    p = bt._free_port()
    assert isinstance(p, int)
    assert 1024 <= p <= 65535


def test_pick_chrome_bin_explicit_existing(tmp_path: Path) -> None:
    fake = tmp_path / "fake-chrome"
    fake.write_text("#!/bin/sh\nexit 0\n")
    fake.chmod(0o755)
    assert bt._pick_chrome_bin(str(fake)) == str(fake)


def test_pick_chrome_bin_explicit_missing_falls_back() -> None:
    # ruta absurda: vuelve al PATH; en este host hay google-chrome
    found = bt._pick_chrome_bin("/no/such/binary/here")
    assert found is None or Path(found).exists()


def test_stringify_remote_value() -> None:
    assert bt._stringify_remote({"value": 42}) == "42"
    assert bt._stringify_remote({"description": "Error: x"}) == "Error: x"
    assert bt._stringify_remote({"unserializableValue": "Infinity"}) == "Infinity"
    assert bt._stringify_remote({"type": "undefined"}) == "undefined"


# ── third_party_domains ──────────────────────────────────────────────────


def test_third_party_domains_filters_base() -> None:
    t = Trace(url="https://acme.com/", final_url="https://acme.com/")
    t.network = [
        NetworkEvent(request_id="1", url="https://acme.com/index.html"),
        NetworkEvent(request_id="2", url="https://cdn.acme.com/app.js"),
        NetworkEvent(request_id="3", url="https://googletagmanager.com/gtm.js"),
        NetworkEvent(request_id="4", url="https://api.stripe.com/v1/checkout"),
        NetworkEvent(request_id="5", url="https://fonts.googleapis.com/css"),
    ]
    domains = third_party_domains(t)
    assert "acme.com" not in domains
    assert "cdn.acme.com" not in domains  # subdominio del base
    assert "googletagmanager.com" in domains
    assert "api.stripe.com" in domains
    assert "fonts.googleapis.com" in domains


def test_third_party_domains_orders_by_count() -> None:
    t = Trace(url="https://x.com/")
    t.network = [
        NetworkEvent(request_id="1", url="https://a.com/x"),
        NetworkEvent(request_id="2", url="https://b.com/y"),
        NetworkEvent(request_id="3", url="https://b.com/z"),
        NetworkEvent(request_id="4", url="https://b.com/w"),
    ]
    domains = third_party_domains(t)
    assert domains[0] == "b.com"


# ── Serializadores ───────────────────────────────────────────────────────


def test_trace_to_markdown_basic() -> None:
    t = Trace(
        url="https://acme.com/",
        final_url="https://acme.com/",
        title="Acme",
        duration_ms=420.5,
    )
    t.network = [
        NetworkEvent(request_id="1", url="https://acme.com/", status=200,
                     resource_type="Document", duration_ms=120.0, method="GET"),
        NetworkEvent(request_id="2", url="https://acme.com/app.js", status=200,
                     resource_type="Script", duration_ms=80.0),
    ]
    t.console = [ConsoleEvent(level="warning", text="deprecated API")]
    t.lifecycle = ["init", "load", "networkIdle"]

    md = trace_to_markdown(t)
    assert "# Browser trace: https://acme.com/" in md
    assert "Title: Acme" in md
    assert "Requests: 2" in md
    assert "Console: 1" in md
    assert "init → load → networkIdle" in md
    assert "## Network" in md
    assert "[200]" in md


def test_trace_to_markdown_with_error() -> None:
    t = Trace(url="https://x", error="cdp failed: foo | playwright failed: bar")
    md = trace_to_markdown(t)
    assert "Error: cdp failed" in md


def test_trace_to_jsonl_writes_file(tmp_path: Path) -> None:
    t = Trace(url="https://x", title="X", duration_ms=10.0,
              dom_html="<html>...</html>", dom_size=15)
    t.network = [NetworkEvent(request_id="1", url="https://x/")]
    out = trace_to_jsonl(t, tmp_path / "sub" / "trace.json")
    assert out.exists()
    data = json.loads(out.read_text())
    assert data["url"] == "https://x"
    assert "dom_html" not in data  # excluido por defecto
    assert len(data["network"]) == 1


def test_trace_to_jsonl_can_include_dom(tmp_path: Path) -> None:
    t = Trace(url="https://x", dom_html="<html>", dom_size=6)
    out = trace_to_jsonl(t, tmp_path / "trace.json", include_dom=True)
    data = json.loads(out.read_text())
    assert data["dom_html"] == "<html>"


# ── trace_url contracts ─────────────────────────────────────────────────


def test_trace_url_returns_error_trace_if_no_chrome(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sin Chrome ni Playwright, devuelve un Trace con .error en vez de raise."""
    monkeypatch.setattr(bt, "_pick_chrome_bin", lambda *a, **k: None)

    # Bloqueamos también el fallback playwright simulando ImportError
    def _fail_playwright(*a, **k):
        raise RuntimeError("Playwright no disponible para fallback")

    monkeypatch.setattr(bt, "_trace_with_playwright", _fail_playwright)

    t = bt.trace_url("https://example.com", use_fallback=True)
    assert t.error
    assert "cdp failed" in t.error
    assert "playwright failed" in t.error


def test_trace_url_no_fallback_returns_error_trace(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bt, "_pick_chrome_bin", lambda *a, **k: None)
    t = bt.trace_url("https://example.com", use_fallback=False)
    assert t.error
    assert "cdp failed" in t.error


# ── Integración con servidor local ──────────────────────────────────────


_LOCAL_HTML = b"""<!DOCTYPE html><html><head><title>APEX Local Trace</title></head>
<body><h1>Hola APEX</h1><script>console.log('cdp-ok');</script></body></html>"""


def _spawn_local_server():
    import http.server
    import socketserver
    import threading

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(_LOCAL_HTML)))
            self.end_headers()
            self.wfile.write(_LOCAL_HTML)

        def log_message(self, *a) -> None:  # silenciar
            return

    srv = socketserver.TCPServer(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv


@pytest.mark.skipif(
    shutil.which("google-chrome") is None and shutil.which("chromium") is None,
    reason="Sin Chrome/Chromium disponible (test de integración real)",
)
def test_trace_url_against_local_server() -> None:
    """CDP end-to-end contra un HTTP server local: no depende de internet."""
    srv = _spawn_local_server()
    try:
        url = f"http://127.0.0.1:{srv.server_address[1]}/"
        t = bt.trace_url(url, nav_timeout_s=10, settle_ms=300)
    finally:
        srv.shutdown()

    assert t.error == "", f"trace error: {t.error}"
    assert t.fetcher == "cdp"
    assert t.title == "APEX Local Trace"
    assert t.final_url.startswith("http://127.0.0.1:")
    assert t.num_requests >= 1
    assert any(n.status == 200 for n in t.network)
    assert "load" in t.lifecycle
    assert t.dom_size > 0
    assert any("cdp-ok" in c.text for c in t.console)
