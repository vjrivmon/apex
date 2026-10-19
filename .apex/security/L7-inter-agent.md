---
layer: L7
title: Inter-Agent
status: passed
reviewed_by: "apex self-audit (re-verificado 2026-10-19)"
reviewed_at: "2026-10-19"
asi_coverage:
  - ASI07
  - ASI10
evidence:
  - "Sistema mono-agente: APEX es un MCP server que se comunica SOLO con Claude Code (cliente) via JSON-RPC sobre stdio (mcp/apex_server.py:1962). No hay transporte de red, ni listener, ni segundo proceso que hable con el servidor."
  - "No hay agentes autonomos dentro del MCP: apex_invoke_role solo PREPARA la invocacion y devuelve al orquestador el `Task(subagent_type=...)` que debe lanzar Claude Code (mcp/handlers/roles.py:62-110). Los skills son Markdown que guia al LLM (skills/flow-guardian/SKILL.md:1)."
  - "Cross-project retrieval en modo SOLO LECTURA: hub.db se abre con el URI `file:...?mode=ro`, de modo que SQLite rechaza cualquier escritura (mcp/handlers/_common.py:115, mcp/apex_server.py:440, mcp/apex_server.py:524). El scanner de apex-hub corre en otro proceso y es quien escribe."
  - "Obsidian sync unidireccional: MCP -> filesystem, append-only en el log del proyecto (mcp/handlers/_common.py:68-101). El vault no puede influir en el MCP: no hay ningun camino de entrada desde el vault."
  - "Hub launch sin callback: el servidor puede arrancar `python -m backend` del apex-hub como subprocess fire-and-forget, con lista de argumentos fija y cwd fijo (mcp/apex_server.py:175-220, Popen en mcp/apex_server.py:191-197). El hub no puede llamar de vuelta al MCP."
  - "Residual documentado: el contenido de hub.db no se valida (no hay checksum ni HMAC, F7-01). La mitigacion es que se abre en solo lectura, que el threat model es single-user y que hub.db es un agregado reconstruible por el scanner de apex-hub. La plantilla de la capa autoriza marcar passed en sistemas mono-agente."
---

# L7 — Inter-Agent

Protege: comunicacion entre agentes, cadenas de delegacion. Cubre
ASI07 (Inter-Agent) y ASI10 (Rogue Agents).

Estado: **passed**. APEX es un MCP single-process con un unico caller
(Claude Code) y no tiene agentes autonomos dentro. La plantilla de la
capa autoriza explicitamente marcar `passed` con la evidencia
"sistema mono-agente, no aplica L7", y las propiedades que si aplican
—caller unico, canal de solo lectura, sin callbacks— estan verificadas
contra el codigo. Queda un residual de baja severidad (F7-01) que no
abre un canal de comunicacion entre agentes.

## Checklist

Controles de la plantilla de la capa (`templates/apex-security/L7-inter-agent.md`)
y las propiedades que si aplican a esta arquitectura:

- [x] **Mono-caller**: el MCP server solo acepta conexiones stdio desde
      Claude Code (mcp/apex_server.py:1962). No hay socket ni puerto.
- [x] **Sub-agentes = skills estaticos**: cada skill es un `.md` en git.
      No ejecutan codigo, solo guian al LLM. `apex_invoke_role` no lanza
      nada: prepara el prompt y se lo devuelve al orquestador
      (mcp/handlers/roles.py:62-110). La profundidad de delegacion la
      controla Claude Code, no APEX.
- [x] **Mutual auth**: N/A por diseno. No hay mensajes entre agentes. El
      unico segundo proceso (apex-hub) no llama de vuelta al MCP
      (mcp/apex_server.py:191-197), asi que no hay nada que autenticar.
- [x] **Trust scoring con time-decay**: N/A. No hay agentes con score: el
      unico actor es el caller.
- [x] **Delegation depth**: N/A para el MCP (no hay delegacion autonoma).
      Claude Code controla sus propios subagentes.
- [x] **Message replay protection**: N/A. No hay canal de mensajes con
      nonce ni timestamp entre agentes.
- [x] **Cross-project read-only**: `hub.db` se abre con
      `file:...?mode=ro` (mcp/handlers/_common.py:115, mcp/apex_server.py:440,
      mcp/apex_server.py:524), de modo que la garantia de solo lectura la
      impone SQLite y no una convencion del codigo. La escritura la hace
      el scanner separado de apex-hub.
- [x] **Obsidian sync unidireccional**: MCP -> filesystem, append-only en
      el log del proyecto (mcp/handlers/_common.py:68-101). No hay
      lectura del vault ni callback.
- [x] **Hub launch sin callback**: `python -m backend` con argumentos y
      cwd fijos (mcp/apex_server.py:191-197), fire-and-forget. El hub no
      tiene forma de invocar al MCP.
- [ ] **Checksum de integridad del contenido de hub.db (mejora opcional,
      F7-01)**: el contenido no se valida. No hay checksum ni HMAC al
      leer. Si alguien modifica
      `~/RoadToDevOps/apex-hub/data/hub.db` en local, el MCP leera lo que
      haya. Mitigaciones: apertura en solo lectura (modo `ro`),
      permisos de filesystem y threat model single-user; ademas hub.db es
      un agregado reconstruible por el scanner. No es un control de la
      plantilla para un sistema mono-agente, asi que no bloquea la capa.

## Findings abiertos

1. **F7-01 (baja)**: checksum SHA256 de `hub.db` en los metadatos del
   hub, verificado al leer, para detectar manipulacion local. Mitiga el
   residual de integridad, no un canal de comunicacion. Evidencia que lo
   cerraria: el hash publicado por el hub y la comparacion en la lectura
   de mcp/handlers/_common.py:115, con test que altere el fichero.
2. **F7-02 (baja)**: si APEX creciera hacia un runtime SMA, anadir HMAC
   entre agentes, nonce y ventana anti-replay. No urgente: la
   arquitectura actual no lo necesita. Evidencia que lo cerraria: la
   decision documentada de que no habra runtime SMA, revisada si aparece.

## Verificacion reproducible (2026-10-19)

```bash
# Unico caller, stdio
sed -n '1962p' mcp/apex_server.py
# apex_invoke_role no lanza agentes: devuelve el Task al orquestador
sed -n '100,110p' mcp/handlers/roles.py
# hub.db en solo lectura, impuesto por SQLite
grep -n "mode=ro" mcp/handlers/_common.py mcp/apex_server.py
# Obsidian: solo escritura, append-only
sed -n '68,101p' mcp/handlers/_common.py
# Hub launch: argumentos y cwd fijos
sed -n '191,197p' mcp/apex_server.py
```
