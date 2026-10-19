---
layer: L4
title: Planning
status: partial
reviewed_by: "apex self-audit (re-verificado 2026-10-19)"
reviewed_at: "2026-10-19"
asi_coverage:
  - ASI02
  - ASI05
  - ASI08
evidence:
  - "Planning lo hace Claude Code (el caller). APEX no ejecuta planning autonomo: es un MCP server que expone herramientas bajo demanda, una tool por llamada (mcp/apex_server.py:2090-2092)."
  - "Superficie de tools: 64 tools MCP al 2026-10-19, valor derivado de `len(await list_tools())` en mcp/apex_server.py:566-2087. No se hardcodea: recalcular con `grep -c '^        Tool($' mcp/apex_server.py` tras cada tool nueva."
  - "Sin carga dinamica de tools: el registro de handlers es un dict literal (mcp/handlers/__init__.py:72-137), el set de tools de biblioteca es un frozenset literal (mcp/handlers/books.py:21-23) y el del VirtualFS tambien (mcp/handlers/vfs.py:49-51)."
  - "Subprocess con allowlist: el unico Popen del servidor MCP es el del hub, con lista fija [python, -m, backend], cwd fijo _HUB_DIR y sin argumentos del caller (mcp/apex_server.py:175-220, Popen en mcp/apex_server.py:191-197). Se dispara al arrancar el server (mcp/apex_server.py:2153-2156), NO desde apex_init_project (mcp/handlers/context.py:18-33)."
  - "Escrituras fuera de .apex/: el scaffold de devops copia plantillas a .github/, docker/ y monitor/ del target (lib/scaffold_devops.py:75-96) y el portfolio escribe <slug>.mdx en el out_dir (mcp/handlers/portfolio.py:40-53). Ninguno de los dos valida que el path no salga del proyecto (F4-02)."
  - "Trazabilidad de tool calls: cada PostToolUse (salvo las tools de SKIP_LOG) inserta una fila en tool_call_log (lib/context_db.py:183-190), alimentado por el hook .claude/hooks/skill-forge-watch.py:162-166. Es un log, no una cadena con request_id/parent_id."
  - "Guardas de transicion: la skill flow-guardian describe el gate 10.5 como bloqueante para la fase 11 (skills/flow-guardian/SKILL.md:69-90) y el hook de fase delega el veredicto en el grader (.claude/hooks/phase-gate.py:200-244)."
---

# L4 — Planning

Protege: decision-making del agente, cadenas de tool calls. Cubre
ASI02 (Tool Misuse), ASI05 (Code Execution), ASI08 (Cascading Failures).

Estado: **partial**. El control de superficie (allowlist de tools, sin
carga dinamica) es solido y verificable. Quedan dos huecos reales: no
hay risk level por tool (F4-01) y las tools que escriben fuera del
proyecto no validan el path (F4-02).

## Checklist

- [x] **Scope limitado**: el MCP server no ejecuta planes autonomos. Solo
      responde a tool calls individuales; el planner es Claude Code
      (mcp/apex_server.py:2090-2092).
- [x] **Tool allowlist**: las tools estan fijadas en la lista literal de
      `list_tools()` (mcp/apex_server.py:566-2087) y los handlers en un
      dict literal (mcp/handlers/__init__.py:72-137). No hay mecanismo de
      carga dinamica.
- [x] **Subprocess allowlist**: unico Popen del servidor, con binario y
      cwd fijos y sin argumentos del caller (mcp/apex_server.py:191-197).
- [ ] **Semantic risk scoring**: no formalizado. Las tools read
      (apex_get_context, apex_search) y write (apex_add_decision,
      apex_wiki_add) no distinguen risk level, y el schema de la tool no
      lleva metadata de riesgo (mcp/apex_server.py:901-913). Ver F4-01.
- [x] **Phase transition guards**: el hook de fase bloquea `apex_set_phase`
      cuando el veredicto del grader dice `should_block`, con exit code 2
      (.claude/hooks/phase-gate.py:230-244), y la skill flow-guardian
      describe el gate 10.5 como bloqueante para la fase 11
      (skills/flow-guardian/SKILL.md:69-90).
- [x] **Trazabilidad de tool calls**: cada tool call deja fila en
      `tool_call_log` (lib/context_db.py:183-190) via el hook PostToolUse
      (.claude/hooks/skill-forge-watch.py:162-166). Es un log de tool +
      args + timestamp; no es una cadena con request_id/parent_id.
- [ ] **Chain depth limit**: no aplica al MCP server. Claude Code gestiona
      su propio limite de turnos. Pero la deteccion de cadenas
      sospechosas (read-secret -> write-external) no existe: ver F4-03.
- [ ] **Semantic risk / attack-chain detection**: ausente. Ver F4-03.

## Findings abiertos

1. **F4-01 (baja)**: marcar en cada tool del server el risk level como
   metadata (`"risk_level": "read|write|exec|external"`). Util para
   auditoria futura, no bloqueante. Evidencia que lo cerraria: el campo en
   todos los schemas de tool y un test que verifique que toda tool lo
   declara.
2. **F4-02 (media)**: `apex_scaffold_devops` y `apex_portfolio_draft`
   escriben a paths fuera de `.apex/` (`.github/workflows/`, `docker/`,
   `monitor/`, `content/cases/`). El scaffold solo hace
   `Path(target).resolve()` (lib/scaffold_devops.py:77) y el portfolio
   acepta `out_dir` tal cual (mcp/handlers/portfolio.py:44). Deben
   rechazar paths con `..` y absolutos fuera del proyecto. Evidencia que
   lo cerraria: validacion explicita con test que pase `../../etc` y vea
   el rechazo.
3. **F4-03 (media, NUEVO)**: no hay deteccion de cadenas de tool calls
   sospechosas ni limite de profundidad. `tool_call_log` se consulta para
   el Skill Forge (lib/skill_forge.py:166) pero no para detectar
   secuencias de ataque. Evidencia que lo cerraria: heuristicas sobre
   `tool_call_log` (leer secreto -> escribir fuera, exec tras input de
   usuario) con test de una secuencia que dispare el aviso.

## Verificacion reproducible (2026-10-19)

```bash
# Superficie de tools (derivada, no hardcodeada)
grep -c '^        Tool($' mcp/apex_server.py                  # 64
# Sin carga dinamica: dict y frozenset literales
sed -n '72p' mcp/handlers/__init__.py
sed -n '21p' mcp/handlers/books.py
sed -n '49p' mcp/handlers/vfs.py
# Subprocess allowlist del hub
sed -n '191,197p' mcp/apex_server.py
# El hub se lanza al arrancar el server, no en apex_init_project
sed -n '2153,2156p' mcp/apex_server.py
sed -n '18,33p' mcp/handlers/context.py
```
