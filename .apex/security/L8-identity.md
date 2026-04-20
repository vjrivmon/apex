---
layer: L8
title: Identity
status: partial
reviewed_by: "apex self-audit"
reviewed_at: "2026-04-20"
asi_coverage:
  - ASI03
  - ASI10
evidence:
  - "APEX no tiene sistema de identidad propio: el usuario se autentica en el OS (filesystem perms) + Claude Code MCP config. Single-user local threat model."
  - "No API keys, no tokens, no sesiones. Nada que rotar ni revocar."
  - "Identidad del proyecto activo: `_find_project_root()` en mcp/apex_server.py:855-880 resuelve el proyecto por cwd + presencia de `.apex/`. Evita escribir en el proyecto equivocado."
  - "Sync a Obsidian usa nombre del proyecto como partition key (apex_server.py:194). Evita cross-pollination entre proyectos del mismo vault."
  - "Audit trail: context.db guarda timestamps + phase en cada decision/error/component/wiki/session. git log de `commands/` y `skills/` da trazabilidad de cambios del prompt system."
---

# L8 — Identity

Protege: identidades de agentes, credenciales, permisos. Cubre ASI03
(Identity Abuse) y ASI10 (Rogue Agents).

## Checklist

- [x] **Threat model single-user local**: sin multi-tenancy, sin
      network-accessible API. Identidad = filesystem ownership.
- [x] **Project identity**: `_find_project_root` + presencia obligada
      de `.apex/` evitan escrituras cruzadas entre proyectos.
- [x] **Audit trail**: timestamps + phase en cada fila de context.db.
      git log para cambios del prompt.
- [ ] **JIT permissions**: N/A (no hay permisos granulares; todo o
      nada por stdio). Si APEX evoluciona a modo network, añadir.
- [ ] **Credential rotation**: N/A (no hay credenciales).
- [ ] **Revocation list**: N/A.

## Findings abiertos

1. **F8-01 (baja)**: añadir `apex_version` + `schema_version` a
   context.db `project_meta`. Útil para detectar si el schema cambió
   sin migración.
2. **F8-02 (media)**: si en el futuro APEX expone un socket de red
   (HTTP para dashboard remoto, por ejemplo), requerir OAuth + scopes
   por tool.

## Evidencia complementaria

```yaml
evidence:
  - "single-user local threat model documentado"
  - "project root resolution: _find_project_root en apex_server.py"
  - "audit trail: timestamps en todas las filas"
  - "git log commands/ skills/ revela cambios de prompts"
```
