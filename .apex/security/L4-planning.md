---
layer: L4
title: Planning
status: partial
reviewed_by: "apex self-audit"
reviewed_at: "2026-04-20"
asi_coverage:
  - ASI02
  - ASI05
  - ASI08
evidence:
  - "Planning lo hace Claude Code (el caller). APEX no ejecuta planning autónomo — es un MCP server que expone herramientas bajo demanda."
  - "Cada tool del MCP (apex_*) devuelve un resultado atómico, no orquesta cadenas internas. Las cadenas viven en el prompt del usuario + commands/ + skills/."
  - "21 tools expuestos (ver mcp/apex_server.py:300-900). Ninguna ejecuta código arbitrario; mayoría son read/write sobre context.db. Excepciones: apex_scaffold_devops (escribe templates), apex_init_project (subprocess para hub launch)."
  - "apex_server.py:106-130 `_launch_hub_if_needed` lanza subprocess con allowlist: solo `[python, '-m', 'backend']` en `_HUB_DIR` fijo. No acepta argumentos del usuario."
  - "Flow-guardian skill (skills/flow-guardian/SKILL.md) bloquea transiciones de fase si sub-pasos no están completos."
---

# L4 — Planning

Protege: decision-making del agente, cadenas de tool calls. Cubre
ASI02 (Tool Misuse), ASI05 (Code Execution), ASI08 (Cascading Failures).

## Checklist

- [x] **Scope limitado**: MCP server no ejecuta planes autónomos. Solo
      responde a tool calls individuales. El planner es Claude Code.
- [x] **Tool allowlist**: las 21 tools están fijadas en
      `apex_server.py:300-900`. No hay mecanismo de carga dinámica.
- [x] **Subprocess allowlist**: único subprocess en
      `_launch_hub_if_needed` (apex_server.py:106-130) con binario fijo
      (`python -m backend`) y cwd fijo (`_HUB_DIR`).
- [ ] **Semantic risk scoring**: no formalizado. Las tools read
      (get_context, search) y write (add_decision, wiki_add) no
      distinguen risk level.
- [x] **Phase transition guards**: skill `flow-guardian` bloquea
      avanzar de fase si sub-pasos `[Na] → [Ni]` no están completos o
      si gate 10.5 (AgentArmor) no está passed.
- [ ] **Chain depth limit**: no aplicable al MCP server. Claude Code
      gestiona su propio límite de turnos.

## Findings abiertos

1. **F4-01 (baja)**: marcar en cada tool del server el risk level como
   metadata (`"risk_level": "read|write|exec"`). Útil para auditoría
   futura, no bloqueante.
2. **F4-02 (media)**: `apex_scaffold_devops` y `apex_portfolio_draft`
   escriben a paths fuera de `.apex/` (`.github/workflows/`,
   `vr-web/content/cases/`). Documentar rutas exactas permitidas y
   rechazar paths con `..`.

## Evidencia complementaria

```yaml
evidence:
  - "21 tools declarados estáticamente en apex_server.py"
  - "subprocess allowlist: solo python -m backend en apex-hub dir"
  - "flow-guardian: skills/flow-guardian/SKILL.md bloquea transitions"
```
