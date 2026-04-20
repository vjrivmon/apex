---
layer: L7
title: Inter-Agent
status: partial
reviewed_by: "apex self-audit"
reviewed_at: "2026-04-20"
asi_coverage:
  - ASI07
  - ASI10
evidence:
  - "APEX es un MCP server que se comunica SOLO con Claude Code (cliente) vía JSON-RPC sobre stdio. No hay transporte de red."
  - "No hay agentes autónomos dentro del MCP. Los 'skills' (skills/*/SKILL.md) son prompts — los ejecuta Claude Code, no el server."
  - "Cross-project retrieval: MCP lee hub.db (read-only) en `~/RoadToDevOps/apex-hub/data/hub.db`. El scanner del hub se ejecuta separado y NO comparte proceso con el MCP server."
  - "Obsidian sync: append-only a filesystem local. Unidireccional (MCP → vault). El vault no puede influir al MCP."
  - "Hub launch: MCP server puede lanzar `python -m backend` del apex-hub como subprocess fire-and-forget. No hay callback del hub al MCP."
---

# L7 — Inter-Agent

Protege: comunicación entre agentes, cadenas de delegación (solo si el
sistema es SMA). Cubre ASI07 (Inter-Agent) y ASI10 (Rogue Agents).

APEX como tal es un MCP single-process con caller único (Claude Code).
Los "skills" son documentación + prompts, no agentes ejecutables.

## Checklist

- [x] **Mono-caller**: MCP server solo acepta conexiones stdio desde
      Claude Code (configurado en el MCP settings del usuario).
- [x] **Sub-agentes = skills estáticos**: cada skill es un `.md` en
      git. No ejecutan código, solo guían al LLM. Delegation depth se
      controla por Claude Code (no por APEX).
- [x] **Cross-project read-only**: hub.db solo se lee, nunca se
      escribe desde el MCP. La escritura la hace el scanner separado.
- [x] **Obsidian sync unidireccional**: MCP → filesystem, sin
      callback.
- [ ] **Integrity del hub.db**: no hay verificación HMAC al leer hub.db.
      Si un atacante escribe en ~/RoadToDevOps/apex-hub/data/hub.db
      (local write), el MCP lo leerá. Mitigación: filesystem perms +
      threat model single-user.
- [ ] **Delegation depth**: N/A para el MCP (no hay delegación
      autónoma). Claude Code controla sus propios subagentes.

## Findings abiertos

1. **F7-01 (baja)**: añadir checksum SHA256 de hub.db en metadata del
   hub, verificar al leer. Mitiga tampering local no detectado.
2. **F7-02 (baja)**: si APEX crece hacia SMA runtime, añadir HMAC +
   replay guard. No urgente — arquitectura actual no lo necesita.

## Evidencia complementaria

```yaml
evidence:
  - "transport: JSON-RPC stdio, single caller (Claude Code)"
  - "skills no ejecutables: solo .md con prompts"
  - "hub.db read-only desde MCP (cross_project_search en apex_server.py)"
```
