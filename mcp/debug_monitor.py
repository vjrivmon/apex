"""APEX Debug Monitor — Servidor HTTP que registra todos los eventos del MCP.

Corre como proceso separado mientras usas Claude Code. Captura cada llamada
al MCP server y la registra con timestamp, herramienta, argumentos y resultado.

Uso:
    # Terminal 1: arrancar monitor
    cd ~/RoadToDevOps/apex
    .venv/bin/python3 mcp/debug_monitor.py

    # Terminal 2: usar Claude Code normalmente
    cd ~/RoadToDevOps/test-apex
    claude

    # El monitor muestra en tiempo real cada herramienta que se invoca.
    # Al terminar, genera debug_session_YYYY-MM-DD_HH-MM.log para análisis.

Endpoints:
    GET  /           → Dashboard en tiempo real (auto-refresh)
    GET  /events     → JSON con todos los eventos
    GET  /export     → Descarga el log completo
    POST /event      → Registrar evento (llamado por apex_server.py)
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Intentar importar uvicorn/fastapi, si no usar http.server básico
try:
    from http.server import HTTPServer, BaseHTTPRequestHandler
except ImportError:
    pass

_events: list[dict] = []
_start_time = datetime.now(timezone.utc)
_log_dir = Path(__file__).parent.parent / "logs"


def _log_path() -> Path:
    _log_dir.mkdir(exist_ok=True)
    ts = _start_time.strftime("%Y-%m-%d_%H-%M")
    return _log_dir / f"debug_session_{ts}.log"


def _add_event(tool: str, arguments: dict, result: str, duration_ms: int = 0) -> None:
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tool": tool,
        "arguments": arguments,
        "result": result[:500],  # Truncar resultados largos
        "duration_ms": duration_ms,
        "event_number": len(_events) + 1,
    }
    _events.append(event)

    # Escribir al log
    with open(_log_path(), "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")

    # Imprimir en consola con colores
    color = {
        "apex_get_context": "\033[36m",     # cyan
        "apex_init_project": "\033[32m",    # green
        "apex_set_phase": "\033[33m",       # yellow
        "apex_add_decision": "\033[34m",    # blue
        "apex_add_error": "\033[31m",       # red
        "apex_add_component": "\033[35m",   # magenta
        "apex_search": "\033[36m",          # cyan
        "apex_log_session": "\033[37m",     # white
    }.get(tool, "\033[0m")
    reset = "\033[0m"

    ts = datetime.now().strftime("%H:%M:%S")
    print(f"{color}[{ts}] #{event['event_number']} {tool}{reset}")
    print(f"  Args: {json.dumps(arguments, ensure_ascii=False)[:200]}")
    print(f"  Result: {result[:150]}")
    if duration_ms:
        print(f"  Duration: {duration_ms}ms")
    print()


class DebugHandler(BaseHTTPRequestHandler):
    """HTTP handler para el dashboard de debug."""

    def do_GET(self):
        if self.path == "/" or self.path == "/dashboard":
            self._serve_dashboard()
        elif self.path == "/events":
            self._serve_json(_events)
        elif self.path == "/export":
            self._serve_export()
        elif self.path == "/stats":
            self._serve_stats()
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == "/event":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8")
            data = json.loads(body)
            _add_event(
                tool=data.get("tool", "unknown"),
                arguments=data.get("arguments", {}),
                result=data.get("result", ""),
                duration_ms=data.get("duration_ms", 0),
            )
            self._serve_json({"ok": True, "event_number": len(_events)})
        else:
            self.send_error(404)

    def _serve_dashboard(self):
        html = f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="utf-8">
    <title>APEX Debug Monitor</title>
    <meta http-equiv="refresh" content="3">
    <style>
        body {{ background: #08090a; color: #f7f8f8; font-family: 'Inter', monospace; padding: 20px; }}
        h1 {{ color: #5e6ad2; }}
        .event {{ border: 1px solid rgba(255,255,255,0.08); border-radius: 8px; padding: 12px; margin: 8px 0; background: #0f1011; }}
        .tool {{ color: #7170ff; font-weight: 600; }}
        .args {{ color: #8a8f98; font-size: 13px; }}
        .result {{ color: #d0d6e0; font-size: 13px; }}
        .time {{ color: #62666d; font-size: 12px; }}
        .stats {{ display: flex; gap: 20px; margin: 20px 0; }}
        .stat {{ background: #191a1b; padding: 16px; border-radius: 8px; text-align: center; }}
        .stat-value {{ font-size: 24px; color: #5e6ad2; font-weight: 600; }}
        .stat-label {{ color: #8a8f98; font-size: 12px; }}
        .error {{ border-color: #ef4444; }}
        .phase {{ border-color: #eab308; }}
        .decision {{ border-color: #5e6ad2; }}
    </style>
</head>
<body>
    <h1>APEX Debug Monitor</h1>
    <div class="stats">
        <div class="stat"><div class="stat-value">{len(_events)}</div><div class="stat-label">Eventos</div></div>
        <div class="stat"><div class="stat-value">{len(set(e['tool'] for e in _events))}</div><div class="stat-label">Herramientas</div></div>
        <div class="stat"><div class="stat-value">{sum(1 for e in _events if 'error' in e['tool'])}</div><div class="stat-label">Errores</div></div>
    </div>
    <div id="events">"""

        for event in reversed(_events):
            css_class = "event"
            if "error" in event["tool"]:
                css_class += " error"
            elif "phase" in event["tool"]:
                css_class += " phase"
            elif "decision" in event["tool"]:
                css_class += " decision"

            html += f"""
        <div class="{css_class}">
            <span class="time">#{event['event_number']} — {event['timestamp'][:19]}</span><br>
            <span class="tool">{event['tool']}</span><br>
            <span class="args">{json.dumps(event['arguments'], ensure_ascii=False)[:300]}</span><br>
            <span class="result">{event['result'][:200]}</span>
        </div>"""

        html += """
    </div>
    <p style="color: #62666d; margin-top: 20px;">Auto-refresh cada 3 segundos</p>
</body></html>"""

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def _serve_json(self, data):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))

    def _serve_export(self):
        log = _log_path()
        content = log.read_text(encoding="utf-8") if log.exists() else "No events yet"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Disposition", f'attachment; filename="{log.name}"')
        self.end_headers()
        self.wfile.write(content.encode("utf-8"))

    def _serve_stats(self):
        tools_used = {}
        for e in _events:
            tools_used[e["tool"]] = tools_used.get(e["tool"], 0) + 1
        self._serve_json({
            "total_events": len(_events),
            "unique_tools": len(tools_used),
            "tools_used": tools_used,
            "session_start": _start_time.isoformat(),
            "log_path": str(_log_path()),
        })

    def log_message(self, format, *args):
        """Silenciar logs HTTP del server para no ensuciar la consola."""
        pass


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8099
    print(f"\033[32m╔══════════════════════════════════════════╗\033[0m")
    print(f"\033[32m║     APEX Debug Monitor — Puerto {port}     ║\033[0m")
    print(f"\033[32m╠══════════════════════════════════════════╣\033[0m")
    print(f"\033[32m║  Dashboard: http://localhost:{port}         ║\033[0m")
    print(f"\033[32m║  Eventos:   http://localhost:{port}/events  ║\033[0m")
    print(f"\033[32m║  Export:    http://localhost:{port}/export  ║\033[0m")
    print(f"\033[32m║  Log:       {_log_path().name}  ║\033[0m")
    print(f"\033[32m╚══════════════════════════════════════════╝\033[0m")
    print()
    print("Esperando eventos del MCP server...")
    print()

    server = HTTPServer(("localhost", port), DebugHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print(f"\n\033[33mSesión finalizada. {len(_events)} eventos registrados.\033[0m")
        print(f"Log guardado en: {_log_path()}")


if __name__ == "__main__":
    main()
