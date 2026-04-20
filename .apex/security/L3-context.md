---
layer: L3
title: Context
status: partial
reviewed_by: "apex self-audit"
reviewed_at: "2026-04-20"
asi_coverage:
  - ASI01
  - ASI06
evidence:
  - "System prompts viven en `commands/apex.md` (router) + `commands/phases/*.md` (15 archivos) + `commands/rules/absolute-rules.md`. Progressive disclosure: Claude Code solo carga la fase activa."
  - "Reglas absolutas (commands/rules/absolute-rules.md) contienen 20 invariantes que el agente debe respetar en cada fase, actuando como anchoring."
  - "Prompt versioning: todo el sistema `commands/` vive en git. `git log commands/` da trazabilidad completa de cambios."
  - "Session isolation: cada proyecto tiene su propio `.apex/context.db`. No hay memoria compartida entre proyectos salvo vía hub.db (read-only para el MCP invocador)."
  - "Canary tokens: NO implementados formalmente. El sistema depende de git + code review para detectar prompt tampering."
---

# L3 — Context

Protege: system prompt, identity anchoring, contexto del agente. Cubre
ASI01 (Goal Hijacking) y ASI06 (Memory Poisoning).

## Checklist

- [ ] **GoalLock / canary tokens**: no implementados. Mitigación:
      sistema `commands/` versionado en git con commits firmados por el
      único contribuidor.
- [ ] **Canary verification runtime**: no implementado. Ver findings.
- [x] **Template injection stripping** (parcial): los inputs llegan a
      la DB vía parametrized SQL. No se inyectan en templates Jinja ni
      similares. El contenido del wiki se renderiza tal cual en
      Markdown.
- [x] **Prompt storage auditable**: `commands/` + `skills/*/SKILL.md`
      todo en git, cambios auditables con `git log`.
- [x] **Session isolation**: context.db aislado por proyecto. Hub.db
      (cross-project) se escribe por scanner pero el MCP solo lee para
      retrieval.
- [ ] **Diff monitoring runtime**: no implementado. FINDING.

## Findings abiertos

1. **F3-01 (alta)**: añadir 3 canary tokens distribuidos en
   `commands/apex.md` + `commands/rules/absolute-rules.md`. Skill
   `flow-guardian` verifica presencia en cada transición de fase.
2. **F3-02 (media)**: script `lib/prompt_hash.py` que calcule hash de
   `commands/` + `skills/` al arrancar MCP server y avise si difiere
   del baseline esperado (stored en `.apex/security/prompt-baseline.json`).

## Evidencia complementaria

```yaml
evidence:
  - "15 archivos phases/ + 3 rules/ + router apex.md — todo bajo git"
  - "session isolation: context.db por proyecto en .apex/context.db"
  - "git log commands/ revela historial de cambios del prompt system"
```
