---
layer: L6
title: Output
status: partial
reviewed_by: "apex self-audit"
reviewed_at: "2026-04-20"
asi_coverage:
  - ASI09
evidence:
  - "Outputs del MCP son JSON con campos estructurados (phases, decisions, errors, wiki_pages). No hay output libre de texto del agente — todo viene de la DB."
  - "El MCP no tiene modelo LLM dentro: es puro CRUD + FTS5. Las hallucinations no aplican al output del server."
  - "Portfolio publisher (lib/portfolio_publish.py) genera MDX con frontmatter YAML parametrizado por slug. Revisa estructura antes de escribir (draft=true por default)."
  - "Ningún tool devuelve credenciales ni tokens porque no se almacenan. PII opcional solo si el usuario lo añade manualmente vía apex_wiki_add."
  - "Obsidian sync solo append-only al log del proyecto, truncado a 100 chars por línea (apex_server.py:203-223)."
---

# L6 — Output

Protege: respuestas al usuario, prevención de exfiltración. Cubre
ASI09 (Human Trust Risk).

## Checklist

- [x] **Schema-validated output**: todas las tools devuelven estructuras
      tipadas (dict con claves fijas). No hay texto libre del LLM.
- [x] **No credentials en DB**: el schema no tiene columnas sensibles.
      Mitigación parcial: el usuario puede filtrar secreto en
      `wiki_pages.content` — depende de su autodisciplina.
- [ ] **Credential redaction runtime**: no hay scanner automático en
      outputs. FINDING.
- [ ] **PII scanner**: no implementado. N/A para APEX mismo (no hay
      PII), pero relevante si un proyecto decide registrar tickets con
      datos de usuario en context.db.
- [ ] **Exfiltration detection**: no aplicable (MCP es local y
      read-only externamente).
- [x] **Output truncation**: resumen de wiki pages limitado a 500
      chars; Obsidian sync trunca a 100.
- [x] **Portfolio draft safety**: `apex_portfolio_draft(apply=false)`
      por default. Usuario revisa antes de aplicar.

## Findings abiertos

1. **F6-01 (media)**: añadir `lib/output_guards.py` con regex básica
   para `sk-...`, `ghp_...`, `xoxb-...`, `AKIA...` en el contenido
   devuelto por `apex_get_context` y `apex_search`. Si hit → redactar y
   warning.
2. **F6-02 (baja)**: documentar en README.md el contrato de
   `apex_wiki_add`: el contenido NO debe incluir secretos. Añadir
   pre-check antes de escribir.

## Evidencia complementaria

```yaml
evidence:
  - "outputs tipados: todas las tools devuelven dict con claves fijas"
  - "sin LLM en el MCP: zero hallucination surface"
  - "portfolio draft default apply=false (portfolio_publish.py:24)"
```
