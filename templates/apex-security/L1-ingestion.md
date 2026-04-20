---
layer: L1
title: Ingestion
status: pending
reviewed_by: ""
reviewed_at: ""
asi_coverage:
  - ASI01
  - ASI04
evidence: []
---

# L1 — Ingestion

Protege: inputs del usuario, fuentes externas cargadas al agente, MCP
connectors. Cubre ASI01 (Goal Hijacking) y ASI04 (Supply Chain).

## Checklist

- [ ] **Input scanning** — prompt injection detector activo en todo
      input del usuario (regex base + modelo clasificador si procede).
- [ ] **Source verification** — toda fuente externa (MCP, paper, URL)
      verificada por hash/signature antes de uso.
- [ ] **MCP audit** — cada MCP conectado tiene entrada en
      `.apex/raw/papers/mcp-audit-<name>.md` con riesgo evaluado.
- [ ] **Rate limiting** — por usuario y por tipo de input (write >
      read).
- [ ] **File type whitelist** — uploads solo aceptan extensiones
      previstas.

## Evidencia (actualizar al completar)

Ejemplo:

```yaml
evidence:
  - "prompt-injection scanner en lib/guards/prompt_injection.py (regex + modelo local)"
  - "MCP audits en .apex/raw/papers/mcp-audit-*.md (3 MCPs auditados)"
  - "rate limit 60req/min por IP en middleware/ratelimit.py"
```
