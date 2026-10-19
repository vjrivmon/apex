"""Token filter heurístico para outputs ruidosos (Sprint 9.2).

Detecta cuándo un output de herramienta vale la pena archivar (mover el
texto completo a `tool_output_archive` y dejar solo un resumen en contexto).

NO se aplica automáticamente — los hooks `PostToolUse` no pueden modificar
el output que el modelo ya leyó. Esta librería se usa cooperativamente:
el agente decide archivar cuando el `post-tool-archive.py` avisa, llamando
`apex_archive_output(tool, arguments, output)`.

Heurísticas pragmáticas:
- output >5000 chars → candidato fuerte
- output >100 líneas → candidato fuerte
- pip/npm install logs (líneas con "Collecting", "Downloading", "Successfully")
- dependency trees (├──, └──)
- diffs muy largos (>200 líneas)
"""
from __future__ import annotations

try:  # el curador es opcional: sin httpx, APEX sigue funcionando igual
    import curator as _curator
except ImportError:  # pragma: no cover - solo si httpx no está instalado
    _curator = None  # type: ignore

DEFAULT_CHARS_THRESHOLD = 5_000
DEFAULT_LINES_THRESHOLD = 100

NOISY_PATTERNS = (
    "Collecting ",
    "Downloading ",
    "Successfully installed",
    "added ",  # npm
    "├──",
    "└──",
    "warning ",
    "Requirement already satisfied",
)


def char_count(output: str) -> int:
    return len(output or "")


def line_count(output: str) -> int:
    return len((output or "").splitlines())


def matches_noisy_patterns(output: str, threshold: int = 5) -> bool:
    """True si hay >=threshold ocurrencias de patrones ruidosos."""
    if not output:
        return False
    hits = 0
    for line in output.splitlines():
        for pat in NOISY_PATTERNS:
            if pat in line:
                hits += 1
                break
        if hits >= threshold:
            return True
    return False


def should_archive(output: str, tool_name: str = "",
                   chars_threshold: int = DEFAULT_CHARS_THRESHOLD,
                   lines_threshold: int = DEFAULT_LINES_THRESHOLD) -> bool:
    """True si el output vale la pena archivar."""
    if not output:
        return False
    if char_count(output) >= chars_threshold:
        return True
    if line_count(output) >= lines_threshold:
        return True
    if matches_noisy_patterns(output):
        return True
    return False


def _resumen_curado(output: str, max_chars: int) -> str | None:
    """Resumen semántico con el curador local, o None si no procede.

    El curador destila, no decide: el output original sigue archivado
    entero en `tool_output_archive`, así que un resumen pobre no pierde
    información.
    """
    if _curator is None:
        return None
    curador = _curator.get_curator()
    if not curador.enabled:
        return None
    # ~4 chars por token, el mismo criterio que usa el resto de APEX.
    return curador.summarize(output, max_tokens=max(64, max_chars // 4))


def summarize_for_context(output: str,
                           head_lines: int = 10,
                           tail_lines: int = 5,
                           max_chars: int = 1500) -> str:
    """Resumen apto para inyectar de vuelta al contexto:
    primeras N líneas + métricas + últimas M líneas."""
    if not output:
        return "(output vacío)"

    lines = output.splitlines()
    total_lines = len(lines)
    total_chars = len(output)

    if total_chars <= max_chars and total_lines <= head_lines + tail_lines + 2:
        return output  # ya es corto, no resumir

    # Sprint 18 (opt-in): con curador activo, el corte por caracteres se
    # sustituye por un resumen semántico. Si el curador está apagado o falla,
    # sigue la heurística de siempre, byte a byte.
    curado = _resumen_curado(output, max_chars)
    if curado:
        return curado

    head = lines[:head_lines]
    tail = lines[-tail_lines:] if tail_lines > 0 else []
    omitted = total_lines - len(head) - len(tail)

    parts = []
    parts.extend(head)
    if omitted > 0:
        parts.append(
            f"[... {omitted} líneas omitidas · {total_chars:,} chars totales · "
            "archivado cooperativamente, recuperar con apex_get_archived(id) ...]"
        )
    parts.extend(tail)

    summary = "\n".join(parts)
    if len(summary) > max_chars:
        summary = summary[:max_chars] + f"\n[truncado a {max_chars} chars]"
    return summary
