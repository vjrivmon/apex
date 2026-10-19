# .apex/security/ — AgentArmor 8-layer

Cada archivo L1..L8 es la evidencia de una capa de seguridad.

## Flujo

1. `python -m lib.security_gate --scaffold` crea las 8 plantillas si
   no existen.
2. Completa cada archivo con evidencia real (código, commits, config).
3. Cambia `status: pending` → `status: passed` cuando la capa esté
   cubierta.
4. `apex_security_gate()` verifica que los 8 están en `passed` antes
   de permitir fase 11 (Deploy).

## Capas

| L | Archivo | Cubre | OWASP ASI |
|---|---------|-------|-----------|
| L1 | `L1-ingestion.md` | Inputs + supply chain | ASI01, ASI04 |
| L2 | `L2-storage.md` | Memoria persistente | ASI06 |
| L3 | `L3-context.md` | Goal lock + canaries | ASI01, ASI06 |
| L4 | `L4-planning.md` | Chain tracking + risk | ASI02, ASI05, ASI08 |
| L5 | `L5-execution.md` | Runtime guards | ASI02, ASI03, ASI05 |
| L6 | `L6-output.md` | Redaction + exfil | ASI09 |
| L7 | `L7-inter-agent.md` | Mutual auth | ASI07, ASI10 |
| L8 | `L8-identity.md` | Rotation + JIT | ASI03, ASI10 |

## Qué significa cada `status`

| Valor | Significado |
|---|---|
| `passed` | Todas las afirmaciones afirmativas de la capa están verificadas contra el código actual, con referencia `fichero:línea`, y cada control prometido por la plantilla de la capa (`templates/apex-security/L*.md`) está implementado o es N/A por diseño, con el motivo escrito. Las mejoras opcionales de severidad baja quedan listadas como findings y no bloquean. |
| `partial` | La capa tiene controles implementados y verificados, pero queda al menos uno sin implementar. El finding abierto dice exactamente qué falta y qué evidencia lo cerraría. |
| `pending` | La capa no se ha revisado todavía. |
| `failed` | La revisión encontró que una afirmación de la capa es falsa. |

`partial` NO es un fallo del gate: es la señal de que la mitigación está
pendiente. El gate sigue bloqueando la fase 11 mientras haya capas en
`partial`, y eso es lo correcto: el gate debe reflejar la realidad, no
el deseo de avanzar.

## Estado a 2026-10-19

| Capa | Status | Por qué |
|---|---|---|
| L1 | `partial` | Sin detector de prompt injection (F1-01), sin documento de MCP audit (F1-02), slug del wiki sin sanitizar (F1-03) e ingesta que acepta paths absolutos (F1-04). |
| L2 | `partial` | Sin backups automatizados (F2-01), sin pre-check de secretos en el wiki (F2-02), sin detección de manipulación de la BD (F2-03). |
| L3 | `partial` | Sin canary tokens (F3-01), sin hash de prompt (F3-02). |
| L4 | `partial` | Sin risk level por tool (F4-01), paths de scaffold/portfolio sin validar (F4-02), sin detección de cadenas sospechosas (F4-03). |
| L5 | `partial` | Hay cuatro rutas de red y seis subprocess (F5-02, F5-03), sin resource limits (F5-01), sin circuit breaker (F5-04), allowlist de filesystem incompleta (F5-05). |
| L6 | `partial` | Sin redaction de credenciales en las outputs (F6-01), sin scanner de PII (F6-03), sin detección de exfiltración (F6-04). |
| L7 | `passed` | Sistema mono-agente: caller único, `hub.db` en `mode=ro`, Obsidian unidireccional, sin callbacks. Residual de integridad documentado (F7-01, baja). |
| L8 | `passed` | Identidad = OS + filesystem, resolución de proyecto que no puede caer en `~/.apex`, memoria global separada, audit trail con timestamps. Rotación y revocación son N/A por diseño (F8-01, F8-02). |

## Reglas de evidencia

- Toda referencia es `fichero:línea` relativa a la raíz del repo, y el
  fichero tiene que existir con esa línea dentro de su rango.
- Los números que se pueden derivar de un comando NO se hardcodean. El
  número de tools MCP sale de `len(await list_tools())`
  (`mcp/apex_server.py:566-2087`): 64 tools MCP al 2026-10-19.
  Recalcular con `grep -c '^        Tool($' mcp/apex_server.py` tras cada
  tool nueva; si cambia, el test lo detecta y la cifra hay que
  actualizarla.
- `tests/test_security_layers_evidence.py` comprueba que las 8 capas
  existen, que su frontmatter tiene las claves que el gate espera, que
  cada `status` está en el conjunto que el gate acepta, que cada
  referencia `fichero:línea` apunta a un fichero real y a una línea
  real, y que ninguna capa afirma un número de tools MCP desactualizado.

## Auditoría

El security gate escribe `audit-report-YYYY-MM-DD.md` aquí mismo
cuando se ejecuta. Commitea tanto las 8 capas como los reportes para
trazabilidad.

La re-verificación del 2026-10-19 detectó que las 8 capas llevaban
`status: partial` desde el 2026-04-20 con evidencia obsoleta (número de
tools, rangos de líneas desplazados, conteos de ficheros que ya no
existían). Ese informe no reescribió el estado para forzar el verde:
corrigió las referencias contra el código y dejó cada capa en el status
que su contenido real sostiene.
