---
description: Inicia o retoma APEX en el proyecto actual
---

Sigue APEX para esta petición: $ARGUMENTS

1. Carga y sigue la skill `apex` disponible en OpenCode. Resuelve `APEX_ROOT` desde la ruta real de la skill; no uses como raíz la ruta del enlace `~/.agents/skills/apex`.
2. Usa las herramientas del MCP `apex` que aparecen bajo `tools.apex`. No busques `ToolSearch` ni uses nombres `mcp__apex__*`, que pertenecen a Claude Code.
3. Si el directorio actual ya tiene `.apex/`, llama primero a `tools.apex.apex_get_context({level: "timeline"})`. Confirma que `nombre` corresponde al proyecto actual antes de cualquier escritura. Si el contexto no corresponde o el MCP no está conectado, detente y avísame; no escribas en otra base de datos.
4. Lee `<APEX_ROOT>/commands/apex.md` y las tres reglas `<APEX_ROOT>/commands/rules/absolute-rules.md`, `errors-to-avoid.md` y `ux-verification.md`. Aplica las equivalencias de OpenCode indicadas por la skill y carga solo la fase que corresponda.
5. Atiende la petición concreta antes de retomar pendientes generales. Conserva las fases, gates y criterios de verificación de APEX.
