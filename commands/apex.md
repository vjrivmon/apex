# /apex — Sistema de desarrollo guiado por fases

## IMPORTANTE: Herramientas MCP obligatorias

Este comando REQUIERE usar las herramientas MCP de APEX. Usa ToolSearch para
encontrarlas:

```
ToolSearch("apex")
```

Las herramientas se llaman `mcp__apex__apex_*`. DEBES usarlas para:

- `mcp__apex__apex_init_project` → Crear .apex/ al inicio
- `mcp__apex__apex_get_context` → Leer estado del proyecto
- `mcp__apex__apex_set_phase` → Cambiar de fase
- `mcp__apex__apex_add_decision` → Registrar cada decisión
- `mcp__apex__apex_add_error` → Registrar errores
- `mcp__apex__apex_add_component` → Registrar componentes
- `mcp__apex__apex_add_next_step` → Próximos pasos
- `mcp__apex__apex_search` → Buscar en contexto
- `mcp__apex__apex_log_session` → Registrar sesión
- `mcp__apex__apex_wiki_add` → Añadir al knowledge base

**Si no encuentras las herramientas MCP, avisa al usuario de que debe reiniciar
Claude Code.**

## Flujo

### Caso A: Proyecto nuevo (no existe .apex/)

#### Paso 1: Verificar si existe .apex/

```bash
ls -la .apex/ 2>/dev/null || echo "Proyecto nuevo"
```

#### Paso 2: Tutor Socrático (Fase 0)

Cuestiona la idea con AskUserQuestion (3-5 rondas):

- Ronda 1: "¿Qué lo diferencia de lo que ya existe?"
- Ronda 2: "¿Realmente necesitas una UI? ¿CLI/bot/MCP no basta?"
- Ronda 3: "¿Quién lo usa? ¿Con qué frecuencia?"
- Ronda 4: "¿Cuál es el escenario donde falla?"
- Ronda 5: "Si solo pudieras hacer UNA cosa, ¿cuál?"

#### Paso 3: Inicializar proyecto con MCP

Después del socrático, llama a:

```
mcp__apex__apex_init_project(name="...", description="...", solution_type="...", domain="...")
```

#### Paso 4: Registrar decisiones del socrático

Por cada decisión tomada:

```
mcp__apex__apex_add_decision(category="...", decision="...", reasoning="...", phase=0)
```

#### Paso 5: Marcar fase 0 como completada

```
mcp__apex__apex_set_phase(phase_number=0, status="completed", notes="Socrático completado: X rondas")
```

#### Paso 6: Continuar con fase 1 (tipo de solución)

```
mcp__apex__apex_set_phase(phase_number=1, status="in_progress")
```

Propón el tipo correcto (CLI/bot/MCP/app/agent/streamlit) y registra:

```
mcp__apex__apex_add_decision(category="architecture", decision="...", reasoning="...", phase=1)
```

### Caso B: Proyecto existente (ya existe .apex/)

#### Paso 1: Leer contexto

```
mcp__apex__apex_get_context(level="timeline")
```

#### Paso 2: Proponer siguientes pasos basados en el contexto

Pregunta al usuario qué quiere hacer (NO asumas).

#### Paso 3: Ejecutar y registrar todo

Cada acción debe registrarse con las herramientas MCP correspondientes.

## Las 14 Fases

```
 0. Socrático      → Cuestiona, filtra, refina
 1. Tipo solución  → CLI/bot/MCP/app/agente
 2. Diseño         → C4, wireframes (Pencil MCP), user maps
 3. SPEC           → Por fases con checkpoints
 4. Edge cases     → ANTES del código
 5. Scaffold       → Estructura + config
 6. Core           → Domain, ports, agentes
 7. Infra          → BD, LLM, scraping
 8. Integración    → Conectar todo, Streamlit
 9. Testing        → Unit + integration + E2E
10. Seguridad      → OWASP, auth, headers
11. Deploy         → Docker, Tailscale
12. Iteración      → Features, bugs, mejoras
13. Escalado       → Performance, caching
14. Mantenimiento  → Migraciones, backups
```

## Reglas ABSOLUTAS

1. **SIEMPRE usa las herramientas MCP apex\_\*** para registrar TODO
2. **NUNCA generes código antes de fase 5**
3. **SIEMPRE usa AskUserQuestion** antes de asumir
4. **NUNCA tomes decisiones de diseño visual sin Pencil MCP y el usuario**
5. **Backend-first**: verifica que funciona antes de UI
6. **Registra errores** con `apex_add_error`

## Errores a evitar

1. Construir frontend antes de verificar backend
2. No investigar fuentes de datos antes de scrapers
3. Tomar decisiones de diseño sin consultar
4. SPEC monolítica sin checkpoints
5. Asumir siempre "app web con dashboard"
6. Ir de prisa en vez de diseñar bien

$ARGUMENTS
