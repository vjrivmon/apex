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

## Auditoría

El security gate escribe `audit-report-YYYY-MM-DD.md` aquí mismo
cuando se ejecuta. Commitea tanto las 8 capas como los reportes para
trazabilidad.
