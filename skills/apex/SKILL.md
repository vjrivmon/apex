---
name: apex
description: Inicia o retoma el desarrollo guiado por fases de APEX en Codex. Úsala cuando el usuario invoque /apex, $apex o pida continuar un proyecto con el flujo APEX.
---

# APEX en Codex

Adapta el router compartido de APEX al entorno Codex. Conserva la petición
concreta del usuario y el estado existente del proyecto.

## Rutas y entrada

Esta skill vive en `<APEX_ROOT>/skills/apex/SKILL.md`. Resuelve la ruta real
del archivo (puede estar instalado mediante un enlace simbólico) y toma
su tercer directorio padre como `APEX_ROOT`. Las rutas `commands/`,
`skills/` y `templates/` de las instrucciones compartidas son relativas a
esa raíz. `.apex/`, el código y los artefactos pertenecen al proyecto de
la tarea actual. No cambies el directorio de trabajo al repositorio APEX.

1. Comprueba que están disponibles las herramientas MCP `apex_*`.
   Usa el catálogo o buscador de herramientas que exponga Codex; los
   prefijos pueden variar. No invoques un `ToolSearch` inexistente.
   Si falta el MCP, comprueba `codex mcp get apex` y pide reiniciar Codex
   tras configurarlo según el README de APEX. No simules escrituras a la BD.
2. Lee `<APEX_ROOT>/commands/apex.md` y las tres reglas de
   `<APEX_ROOT>/commands/rules/` indicadas por el router. Aplica las
   equivalencias de abajo al interpretar sus instrucciones para Claude.
3. Sigue la detección de proyecto del router. Si existe `.apex/`, llama
   `apex_get_context(level="timeline")` y carga solo la fase actual.
   Atiende una petición específica antes de retomar pendientes generales.
4. Lee las skills especializadas desde `<APEX_ROOT>/skills/<nombre>/SKILL.md`
   cuando una fase las necesite; no dependen de estar instaladas por separado.
   El texto que acompaña a la invocación sustituye a `$ARGUMENTS`.

## Equivalencias de entorno

- `Read`, `Bash`, `Edit`, `Write`: herramientas de lectura, terminal y
  edición disponibles en Codex.
- `Skill(nombre)` o `/apex:<modo>`: lee el archivo correspondiente en APEX.
  `reverse` usa `commands/apex-reverse.md`; `goal` usa `commands/apex-goal.md`.
- `AskUserQuestion`: herramienta de preguntas disponible o una pregunta
  directa si no existe. Mantén los checkpoints y criterios de salida.
- `Task` y `subagent_type`: si la delegación está autorizada y disponible,
  usa subagentes de Codex con el `prompt` devuelto por `apex_invoke_role`.
  No pases nombres de agentes Claude como tipos de agente Codex. Si no se
  puede delegar, ejecuta la responsabilidad del rol en la tarea actual.
  No ejecutes `apex_install_roles` para instalar agentes en Codex: escribe
  exclusivamente en `~/.claude/agents/`.
- Los hooks de `.claude/` no se ejecutan por cargar esta skill. Registra
  decisiones, errores, componentes y avances mediante MCP de forma explícita.
  Antes de cambiar de fase, verifica sus criterios y respeta los bloqueos
  de `apex_set_phase` y el gate 10.5. No asumas que un hook ya los comprobó.
  Cuando el usuario cierre la sesión APEX, guarda un handoff mediante
  `apex_handoff_write`; `apex_doctor_run` puede ejecutarse manualmente.
- No interpretes límites de Claude MAX ni sus temporizadores como límites
  de Codex. No crees automatizaciones para emularlos.

El MCP identifica el proyecto por su directorio de arranque. Si el contexto
devuelto no corresponde al proyecto de la tarea, detén las escrituras y
corrige la conexión antes de continuar. No sobrescribas otro proyecto.
