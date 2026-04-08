# /apex -- Sistema de desarrollo guiado por fases

## PASO CERO: Cargar herramientas MCP

Este comando REQUIERE las herramientas MCP de APEX. Ejecuta SIEMPRE al inicio:

```
ToolSearch("apex")
```

Las herramientas se llaman `mcp__apex__apex_*`. Lista completa:

- `mcp__apex__apex_init_project` -- Crear .apex/ al inicio
- `mcp__apex__apex_get_context` -- Leer estado del proyecto
- `mcp__apex__apex_set_phase` -- Cambiar de fase
- `mcp__apex__apex_add_decision` -- Registrar cada decision
- `mcp__apex__apex_add_error` -- Registrar errores
- `mcp__apex__apex_add_component` -- Registrar componentes
- `mcp__apex__apex_add_next_step` -- Proximos pasos
- `mcp__apex__apex_complete_step` -- Marcar paso completado
- `mcp__apex__apex_search` -- Buscar en contexto
- `mcp__apex__apex_log_session` -- Registrar sesion
- `mcp__apex__apex_wiki_add` -- Anadir al knowledge base
- `mcp__apex__apex_invalidate_decision` -- Invalidar decision anterior
- `mcp__apex__apex_update_component` -- Actualizar componente existente

**Si ToolSearch no devuelve herramientas apex, avisa al usuario de que debe
reiniciar Claude Code con el MCP server de APEX activo.**

---

## Deteccion del proyecto

### Paso 1: Verificar estado

```bash
ls -la .apex/ 2>/dev/null && echo "APEX_EXISTS" || echo "APEX_NEW"
uname -s
```

Segun el resultado, seguir Caso A, Caso B o Caso C.

### Caso A: Proyecto nuevo (no existe .apex/ NI codigo)

Ir directamente a **Fase 0 -- Socratico**.

### Caso B: Proyecto existente SIN .apex/ (tiene codigo/git pero no APEX)

Antes de hacer nada, analizar lo que ya existe:

1. Ejecutar:
   ```bash
   git log --oneline -20 2>/dev/null
   ls -la
   cat package.json 2>/dev/null || cat requirements.txt 2>/dev/null || cat pyproject.toml 2>/dev/null
   ls -la tests/ test/ __tests__/ spec/ 2>/dev/null
   ```
2. Detectar automaticamente que fases ya estan hechas:
   - Tiene entidades de dominio / modelos --> Fase 6 parcial o completa
   - Tiene tests --> Fase 9 parcial
   - Tiene Dockerfile / CI --> Fase 11 parcial
   - Tiene BD configurada --> Fase 7 parcial
   - Tiene endpoints / routes --> Fase 8 parcial
3. Llamar a `apex_init_project` con la info detectada
4. Marcar fases detectadas como "completed" o "partial" con `apex_set_phase`
5. Registrar cada hallazgo con `apex_add_decision(category="detected", ...)`
6. Presentar resumen: "He detectado X, Y, Z. Faltan A, B, C."
7. Proponer continuar desde la primera fase incompleta

### Caso C: Proyecto con .apex/ (continuacion)

1. `mcp__apex__apex_get_context(level="timeline")`
2. Leer fase actual y sub-paso pendiente
3. Continuar desde donde se quedo -- NO preguntar "que quieres hacer", ir
   directo al siguiente sub-paso pendiente
4. Si el usuario tiene una peticion especifica, atenderla y registrarla

---

## Las 15 Fases (0-14)

Cada fase tiene sub-pasos SECUENCIALES y OBLIGATORIOS. Se ejecutan EN ORDEN.
NUNCA preguntar "cual quieres hacer primero" -- seguir el orden definido. NUNCA
declarar una fase como completada hasta que TODOS sus sub-pasos esten terminados
y verificados.

---

### Fase 0 -- Socratico

Cuestiona la idea ANTES de construir nada. Investiga el mercado. Filtra ideas
sin valor real.

Sub-pasos en orden:

- **[0a]** Recopilar contexto: Escuchar la idea completa del usuario sin
  interrumpir. Extraer: problema, publico objetivo, tipo de solucion propuesta,
  dominio.
- **[0b]** Investigacion de mercado: Usar WebSearch para buscar si ya existen
  soluciones similares. Buscar: "{idea} app", "{problema} herramienta",
  "{dominio} software open source". Analizar resultados:
  - Si existen competidores: presentar al usuario con analisis de
    fortalezas/debilidades. Preguntar: "Que haria tu version diferente?"
  - Si no existen: posible Oceano Azul. Preguntar: "Por que crees que nadie lo
    ha hecho? Falta de demanda o falta de ejecucion?"
- **[0c]** Ronda 1: "Que problema REAL estas resolviendo? Como lo resuelves HOY
  sin esta herramienta?"
- **[0d]** Ronda 2: "Realmente necesitas UI? Un CLI, bot de Telegram, servidor
  MCP, o script no basta?"
- **[0e]** Ronda 3: "Quien lo usa? Con que frecuencia? Necesita funcionar
  offline?"
- **[0f]** Ronda 4: "Cual es el escenario donde falla? Que pasa si la BD se
  corrompe, si el servicio externo cae, si no hay internet?"
- **[0g]** Reflexion de valor: Escribir un parrafo que explique el problema
  latente que existe y que aporta de valor la solucion propuesta. Guardar en
  wiki: `apex_wiki_add(slug="concepts/value-proposition")`.
- **[0h]** Registrar TODAS las decisiones + investigacion de mercado con
  `apex_add_decision(phase=0, ...)`. Incluir resultados de la busqueda de
  competidores.
- **[0i]** `apex_set_phase(phase_number=0, status="completed")`

---

### Fase 1 -- Tipo de solucion

Determinar la forma correcta del producto. NO asumir "app web con dashboard".

Sub-pasos en orden:

- **[1a]** Analizar las respuestas del socratico y el SO del usuario
  (`uname -s`)
- **[1b]** Evaluar opciones: CLI / bot / MCP server / app web / agente autonomo
  / Streamlit / script cron / extension
- **[1c]** Decidir y registrar:
  `apex_add_decision(category="solution_type", decision="...", reasoning="...")`
- **[1d]** Si tiene componente visual, decidir: PWA / desktop / mobile /
  terminal UI
- **[1e]** `apex_set_phase(phase_number=1, status="completed")`

---

### Fase 2 -- Diseno

REGLA: NUNCA describas un diseno por texto. Usa las herramientas de diseno para
crear mockups visuales. Si la decision afecta al aspecto visual, DEBE
acompanarse de un artefacto visual.

Esta fase tiene 3 bloques: Arquitectura, Identidad Visual, y UX. Se ejecutan EN
ORDEN. No saltar a wireframes sin tener la paleta definida.

#### Herramientas de diseno y su mejor uso

| Herramienta   | Mejor para                                       | MCP tool prefix / skill              |
| ------------- | ------------------------------------------------ | ------------------------------------ |
| Pencil MCP    | Wireframes, layouts, mockups detallados          | `mcp__pencil__*`                     |
| Paper.design  | Exportar a JSX/Tailwind, iteracion rapida        | `mcp__paper__*` (si disponible)      |
| Google Stitch | Generacion completa de pantallas, design systems | skill: stitch-design, stitch-loop    |
| AI Designer   | Prototipado HTML rapido                          | `mcp__aidesigner__*` (si disponible) |
| Excalidraw    | Diagramas, flujos, mapas de navegacion           | `mcp__claude_ai_Excalidraw__*`       |

El agente debe decidir cual usar para cada tarea. Si hay duda, PREGUNTAR al
usuario.

#### Bloque A: Arquitectura

- **[2a]** Diagrama C4 (context + container) con Mermaid. Validar que la
  arquitectura tiene sentido antes de continuar. Registrar con
  `apex_add_decision(category="architecture")`.
- **[2b]** Diagrama C4 componentes (si es complejo). Descomponer cada container
  en sus componentes internos.

#### Bloque B: Identidad Visual (Design System)

OBLIGATORIO si el proyecto tiene UI. Usar MULTIPLES herramientas de diseno +
awesome-design-md.

- **[2c]** Preferencias del usuario: ANTES de crear nada, consultar context.db
  para historial de estilos preferidos del usuario (buscar decisions con
  category="design"). Si hay historial: "En proyectos anteriores elegiste estilo
  X con paleta Y. Quieres mantener esa linea o explorar algo nuevo?" Si no hay
  historial: preguntar con AskUserQuestion mostrando opciones visuales.
- **[2d]** Moodboard COMPARATIVO: Generar moodboards en MULTIPLES herramientas:
  - Pencil MCP: moodboard con layout de referencia
  - Stitch (skill stitch-design): diseno de referencia desde prompt
  - Consultar awesome-design-md para DESIGN.md de apps similares Presentar las
    2-3 opciones al usuario para que elija.
- **[2e]** Paleta de colores: Definir COMPLETA:
  - Brand: primary, secondary
  - Surfaces: background, surface, elevated, overlay
  - Text: primary, secondary, tertiary, muted, inverse
  - Status: success, warning, error, info
  - Borders, shadows, dividers Generar swatches visuales con Pencil MCP.
    Registrar en context.db Y en wiki:
    `apex_wiki_add(slug="concepts/design-system")`.
- **[2f]** Tipografia: Definir:
  - Heading family + fallbacks (ej: Geist, Inter Variable)
  - Body family + fallbacks
  - Mono family + fallbacks (ej: Berkeley Mono, Geist Mono)
  - Escala completa: display (48-72px), h1-h4, body, small, caption, micro
  - Pesos por nivel: display=500-600, body=400, emphasis=500-600
  - Letter-spacing por tamano (negativo en display, normal en body)
  - Line-height por nivel Registrar en wiki design-system.
- **[2g]** Espaciado, radios y elevation: Definir:
  - Base unit (4px u 8px)
  - Escala: 2xs(2), xs(4), sm(8), md(16), lg(24), xl(32), 2xl(48), 3xl(64)
  - Border radius: none(0), sm(4), md(8), lg(12), xl(16), full(9999)
  - Elevation: flat, subtle, standard, elevated, dialog (shadow values)
  - Breakpoints: sm(640), md(768), lg(1024), xl(1280)
- **[2h]** Iconografia: Elegir paquete (Lucide, Phosphor, Heroicons) y tamanos
  estandar. NUNCA emojis. Registrar decision.
- **[2i]** Accesibilidad visual:
  - Verificar contraste WCAG AA minimo (4.5:1 para texto, 3:1 para grandes)
  - Touch targets minimo 44x44px
  - Focus visible en todos los interactivos
  - Roles ARIA documentados para componentes custom
  - Plan de screen reader para flujos principales

#### Bloque C: UX y Pantallas

- **[2j]** Wireframes en MULTIPLES herramientas:
  - Pencil MCP para wireframes low-fi de cada pantalla
  - Stitch para un high-fi de la pantalla principal Presentar opciones al
    usuario para decidir direccion.
- **[2k]** Mapa de navegacion con Excalidraw MCP: Todas las pantallas como
  nodos, flechas entre ellas indicando que boton/link lleva a donde. Exportar
  como imagen.
- **[2l]** User flows: Documentar minimo 3 flujos:
  - Flujo principal (happy path)
  - Flujo secundario (alternativa)
  - Flujo de error (que pasa cuando algo falla) Formato: Accion -> Pantalla ->
    Resultado -> Siguiente accion.
- **[2m]** Registrar TODOS los componentes detectados con `apex_add_component`
- **[2n]** Guardar design system completo en wiki + context.db:
  `apex_wiki_add(slug="concepts/design-system", content="paleta+typo+spacing")`
- **[2o]** `apex_set_phase(phase_number=2, status="completed")`

---

### Fase 3 -- SPEC

Especificacion por fases, no monolitica. Empieza con reflexion profunda.

Sub-pasos en orden:

- **[3a]** Reflexion del problema: "Que problema REAL se esta resolviendo? Cual
  es el problema latente? Que valor aporta esta solucion que no existe hoy?"
  Escribir 2-3 parrafos de analisis. Guardar en wiki:
  `apex_wiki_add(slug="concepts/problem-analysis")`.
- **[3b]** Modelo de datos: Diagrama ER con Mermaid (erDiagram). Definir todas
  las entidades, sus atributos, y las relaciones entre ellas. Incluir tipos de
  datos, constraints, e indices. Registrar en wiki:
  `apex_wiki_add(slug="entities/data-model")`.
- **[3c]** Generar SPEC.md con secciones: Problema, Solucion, Usuarios,
  Funcionalidad core (fase 1), Funcionalidad extendida (fase 2+), Stack,
  Arquitectura, Restricciones, Metricas de exito.
- **[3d]** Dividir la funcionalidad en checkpoints (MVP -> v1 -> v2). Cada
  checkpoint debe ser deployable y usable.
- **[3e]** Definir criterios de "hecho" para cada checkpoint.
- **[3f]** Revisar con el usuario. Pedir feedback en bloque (NO interrumpir con
  preguntas una a una).
- **[3g]** Registrar SPEC como wiki: `apex_wiki_add(title="SPEC", ...)`
- **[3h]** `apex_set_phase(phase_number=3, status="completed")`

---

### Fase 4 -- Edge cases

ANTES de escribir codigo, pensar en que puede fallar.

Sub-pasos en orden:

- **[4a]** Generar TODOS los edge cases posibles, sin limite. Agrupar por
  categoria: inputs invalidos, red/servicios caidos, concurrencia, datos
  corruptos, limites (0, max, unicode, inyeccion), permisos, estados imposibles,
  recursos agotados (disco, memoria, conexiones), temporales (timezone, DST,
  leap year), internacionalizacion, navegadores/dispositivos. Cuantos mas,
  mejor. NO limitar.
- **[4b]** Para cada edge case: describir escenario, comportamiento esperado, y
  estrategia de mitigacion.
- **[4c]** Priorizar: cuales bloquean el MVP y cuales son post-MVP.
- **[4d]** Registrar con `apex_wiki_add(title="EDGE-CASES", ...)`
- **[4e]** `apex_set_phase(phase_number=4, status="completed")`

---

### Fase 5 -- Scaffold

Crear estructura sin logica. Solo esqueleto.

Sub-pasos en orden:

- **[5a]** Crear estructura de directorios segun la arquitectura de fase 2.
- **[5b]** Configurar dependencias: package.json / requirements.txt /
  pyproject.toml. Instalar y verificar que no hay conflictos.
- **[5c]** Configurar linter, formatter, y TypeScript strict si aplica.
- **[5d]** Crear .env.example con todas las variables necesarias (sin valores
  reales).
- **[5e]** Crear archivos base vacios con imports y exports para que la
  estructura compile sin errores.
- **[5f]** Verificar que `npm run build` / `python -m py_compile` pasa sin
  errores.
- **[5g]** Registrar componentes con `apex_add_component`
- **[5h]** `apex_set_phase(phase_number=5, status="completed")`

---

### Fase 6 -- Core (dominio)

Implementar la logica de negocio pura, sin dependencias externas.

Sub-pasos en orden:

- **[6a]** Entidades de dominio (modelos, value objects, enums).
- **[6b]** Puertos/interfaces (repositorios, servicios externos).
- **[6c]** Casos de uso / application services.
- **[6d]** Agentes si es un SMA (orquestador, workers, pipeline).
- **[6e]** Verificar que todo compila y los imports son correctos.
- **[6f]** Registrar cada componente con `apex_add_component`
- **[6g]** `apex_set_phase(phase_number=6, status="completed")`

---

### Fase 7 -- Infraestructura

Implementar los adaptadores que conectan con el mundo exterior.

Sub-pasos en orden:

- **[7a]** Base de datos: adapter, migraciones, seed data.
- **[7b]** Servicios externos: LLM adapter, APIs de terceros, scraping.
- **[7c]** Verificar que cada adapter implementa su puerto/interfaz
  correctamente.
- **[7d]** Test manual rapido: conectar, insertar, leer, borrar.
- **[7e]** Registrar con `apex_add_component`
- **[7f]** `apex_set_phase(phase_number=7, status="completed")`

---

### Fase 8 -- Integracion

Conectar todo y verificar que funciona end-to-end.

Sub-pasos en orden:

- **[8a]** Conectar adaptadores al lifespan de la app (dependency injection).
- **[8b]** Endpoints / CLI commands / bot handlers funcionales.
- **[8c]** Si tiene UI: Streamlit para validar datos reales ANTES de frontend
  definitivo.
- **[8d]** Verificar flujo completo: input -> proceso -> output -> persistencia.
- **[8e]** Si algo falla: registrar con `apex_add_error` y corregir antes de
  avanzar.
- **[8f]** `apex_set_phase(phase_number=8, status="completed")`

---

### Fase 9 -- Testing

Sub-pasos en orden:

- **[9a]** Unit tests: cobertura minima 80% en dominio (entidades, casos de uso,
  agentes). Ejecutar y verificar que pasan.
- **[9b]** Integration tests: BD real, APIs reales, servicios conectados.
- **[9c]** E2E tests con Playwright siguiendo flujos reales de usuario. Cada
  flujo mapeado en fase 2 (ej: crear item -> ver en lista -> completar). Si
  falla: capturar screenshot + estado + error y registrar con `apex_add_error`.
- **[9d]** Edge case tests: implementar los escenarios de EDGE-CASES.md marcados
  como MVP-blocking.
- **[9e]** Verificar que TODOS los tests pasan antes de continuar.
- **[9f]** Coverage report: Ejecutar coverage y generar report HTML.
  - Python: `pytest --cov --cov-report=html`
  - JS/TS: `npx nyc` / `jest --coverage` Threshold minimo: 80% en domain, 60%
    global. Si no se alcanza, registrar que falta y como next_step con
    `apex_add_next_step`.
- **[9g]** `apex_set_phase(phase_number=9, status="completed")`

---

### Fase 10 -- Seguridad

Sub-pasos en orden:

- **[10a]** Input validation y sanitizacion en todos los endpoints.
- **[10b]** Autenticacion si aplica (auth flow completo, no solo middleware).
- **[10c]** Headers de seguridad: CORS restrictivo, CSP, HSTS, X-Frame-Options.
- **[10d]** Rate limiting en endpoints publicos.
- **[10e]** Audit: revisar que no hay secretos en el codigo, .env en .gitignore.
- **[10f]** Registrar decisiones de seguridad con
  `apex_add_decision(category="security")`
- **[10g]** `apex_set_phase(phase_number=10, status="completed")`

---

### Fase 11 -- Deploy

Sub-pasos en orden:

- **[11a]** Docker / systemd / proceso configurado. Verificar que arranca
  limpio.
- **[11b]** CI/CD con GitHub Actions: template auto-generado que incluya lint,
  test, build. Crear `.github/workflows/ci.yml`.
- **[11c]** Auto-deploy on push: staging en PR merge, production en tag/release.
- **[11d]** Health checks post-deploy: endpoint /health que verifique BD,
  servicios externos, disco.
- **[11e]** Rollback plan documentado: como volver a la version anterior en
  menos de 5 minutos. Registrar con `apex_wiki_add(title="ROLLBACK-PLAN")`.
- **[11f]** Dominio y SSL: Configurar dominio (si aplica). Opciones:
  - Caddy (auto-SSL con Let's Encrypt, configuracion minima)
  - Nginx + certbot
  - Cloudflare (DNS + proxy + SSL) Documentar configuracion elegida. Registrar
    con `apex_add_decision(category="deploy", decision="SSL: ...")`.
- **[11g]** Launch / Go-Live checklist:
  - [ ] Todos los tests pasan (green CI)
  - [ ] Security audit completado (sin issues criticos)
  - [ ] Backups configurados y probados
  - [ ] Monitoring activo (health checks respondiendo)
  - [ ] Documentacion de usuario lista
  - [ ] Rollback plan probado
  - [ ] Usuarios notificados / onboarding preparado
  - [ ] Metricas de exito definidas (de SPEC) -> como medirlas Registrar fecha
        de lanzamiento en context.db con
        `apex_add_decision(category="launch", decision="Go-live: YYYY-MM-DD")`.
- **[11h]** `apex_set_phase(phase_number=11, status="completed")`

---

### Fase 12 -- Iteracion

Para features, bugs y mejoras post-deploy.

Sub-pasos en orden:

- **[12a]** Leer context.db para entender estado actual:
  `apex_get_context(level="timeline")`
- **[12b]** Si es **feature nueva**: Mini-socratico (2 rondas: "Que resuelve?" +
  "Como afecta a lo existente?"). Escribir mini-SPEC (1 parrafo: que, por que,
  criterio de hecho). Implementar -> test -> registrar con `apex_add_component`.
- **[12c]** Si es **bug**: Diagnosticar (reproducir, localizar, causa raiz). Fix
  minimo (cambiar lo menos posible). Test que cubra el bug (rojo sin fix, verde
  con fix). Registrar con
  `apex_add_error(error="...", solution="...", lesson="...")`.
- **[12d]** Si es **mejora/refactor**: Medir ANTES (tiempo, memoria, lineas,
  complejidad). Optimizar. Medir DESPUES y comparar. Solo mergear si la mejora
  es medible.
- **[12e]** SIEMPRE registrar en context.db con las herramientas MCP
  correspondientes.
- **[12f]** `apex_set_phase(phase_number=12, status="in_progress")` (esta fase
  nunca se "completa" definitivamente)

---

### Fase 13 -- Escalado

Sub-pasos en orden:

- **[13a]** Performance profiling: medir, NO adivinar. Identificar los 3 cuellos
  de botella reales con datos (tiempo de respuesta, queries lentas, memoria).
- **[13b]** Caching strategy: definir que se cachea, TTLs, estrategia de
  invalidacion. Registrar con `apex_add_decision(category="performance")`.
- **[13c]** Monitoring setup: health checks, alertas, metricas.
- **[13d]** Health dashboard: generar un endpoint `/status` o panel Streamlit
  que muestre: Backend UP/DOWN con timestamp del ultimo check; BD conexion
  OK/FAIL, tamano, ultimo backup; Servicios externos estado de cada uno; Ultima
  actividad timestamp + tipo; Disco espacio usado/libre; Errores recientes
  ultimos 10 de context.db.
- **[13e]** `apex_set_phase(phase_number=13, status="completed")`

---

### Fase 14 -- Mantenimiento

Sub-pasos en orden:

- **[14a]** CI/CD verificado y funcionando (si no se hizo en fase 11, hacerlo
  ahora).
- **[14b]** Backups automatizados: script cron o GitHub Action que respalde BD y
  configuracion. Documentar frecuencia y ubicacion.
- **[14c]** Documentacion auto-generada desde context.db. Generar
  automaticamente estos archivos:
  - ARCHITECTURE.md -- decisiones de arquitectura + diagrama C4 actualizado
  - STACK.md -- tecnologias elegidas y POR QUE (extraido de decisions en
    context.db)
  - GUIDE.md -- como funciona la app para el usuario final (flujos principales)
  - DECISIONS.md -- historial completo de decisiones + invalidaciones
  - CHANGELOG.md -- generado desde `git log --oneline`
- **[14d]** Migraciones de BD documentadas: cada cambio de esquema con su
  migracion reversible.
- **[14e]** Plan de deprecacion: Documentar que pasa cuando:
  - Una dependencia deja de mantenerse (alternativas evaluadas)
  - Una API externa cambia (versioning strategy)
  - Un modelo de Ollama se retira (fallback models) Configurar: dependabot o
    renovate para PRs automaticos de actualizacion. Registrar con
    `apex_add_decision(category="maintenance", decision="...")`.
- **[14f]** `apex_set_phase(phase_number=14, status="completed")`

---

## /apex:idea -- Nueva idea a mitad de proyecto

Si el usuario dice "se me ha ocurrido algo", presenta una nueva idea, o quiere
anadir algo mientras esta en fases 6+:

1. Evaluar: es una feature del proyecto actual o un proyecto completamente
   nuevo?
2. **Si es feature del proyecto actual:**
   - Mini-socratico (2 rondas): "Que resuelve?" + "Como encaja con lo que hay?"
   - Registrar como next_step con prioridad:
     `apex_add_next_step(description="...", priority="high/medium/low")`
   - Continuar con la fase actual. La idea se ejecutara cuando toque (fase 12) o
     si es critica, intercalarla ahora.
3. **Si es un proyecto nuevo:**
   - Proponer crear un directorio separado
   - Iniciar el flujo /apex completo desde fase 0 en ese directorio
   - NO mezclar con el proyecto actual

---

## Verificacion UX/UI automatica

Despues de CADA cambio de frontend (cualquier fase), ejecutar esta verificacion:

1. Usar Playwright para tomar screenshot de las pantallas afectadas
2. Analizar automaticamente:
   - Spacing minimo 16px entre elementos interactivos
   - Touch targets minimo 44px (idealmente 48px)
   - Contraste de texto: ratio minimo 4.5:1 (WCAG AA)
   - Fitts' Law: CTAs principales son grandes y accesibles
   - No hay texto cortado ni overflow visible
3. Reportar violaciones al usuario como lista priorizada
4. Registrar con `apex_add_error` si hay violaciones criticas

---

## Reglas ABSOLUTAS

1. **SIEMPRE** ejecutar `ToolSearch("apex")` al inicio de cada sesion para
   cargar las herramientas MCP.
2. **SIEMPRE** usar las herramientas MCP `apex_*` para registrar TODO:
   decisiones, errores, componentes, fases.
3. **NUNCA** generar codigo antes de fase 5. Las fases 0-4 son de analisis y
   diseno.
4. **NUNCA** describir un diseno visual con texto. Usar Pencil MCP, Stitch,
   Excalidraw u otra herramienta de diseno para crear artefactos visuales. Si la
   decision afecta al aspecto visual, DEBE tener mockup.
5. **NUNCA** usar emojis como iconos en el codigo. Siempre Lucide, Phosphor,
   Heroicons o SVG custom.
6. **NUNCA** preguntar "cual sub-paso quieres hacer primero". Los sub-pasos son
   secuenciales y obligatorios. Seguir el orden.
7. **NUNCA** declarar una fase completada sin que TODOS sus sub-pasos esten
   terminados y verificados.
8. **NUNCA** interrumpir con preguntas obvias. Completar el bloque de trabajo y
   despues pedir feedback.
9. **Backend-first**: verificar que el backend funciona ANTES de construir UI
   definitiva. Streamlit para validar datos reales si hace falta.
10. **SIEMPRE** verificar el SO del usuario (`uname -s`) antes de proponer stack
    que dependa de plataforma (systemd vs launchd, apt vs brew, etc.).
11. **SIEMPRE** verificar frontend con Playwright ANTES de presentar al usuario.
    No mostrar algo que no se ha comprobado que renderiza correctamente.
12. **SIEMPRE** registrar errores con `apex_add_error` incluyendo la leccion
    aprendida.
13. **SIEMPRE** registrar decisiones invalidadas con `apex_invalidate_decision`
    cuando cambie el contexto.
14. **NUNCA** inventar decisiones de diseno. Si hay CUALQUIER duda sobre estilo,
    paleta, tipografia, o layout, PREGUNTAR al usuario con AskUserQuestion.
    Consultar context.db para historial de preferencias antes de proponer.
15. Para diseno visual: generar opciones en MULTIPLES herramientas y presentar
    al usuario para que elija. No acotarse a una sola herramienta.
16. El agente decide el ORDEN de implementacion, no el usuario. El usuario
    define QUE quiere, el agente decide COMO y en que orden construirlo.

---

## Errores a evitar

1. Construir frontend antes de verificar que el backend devuelve datos reales.
2. No investigar fuentes de datos antes de implementar scrapers.
3. Tomar decisiones de diseno visual sin mockup en herramienta de diseno.
4. SPEC monolitica sin checkpoints incrementales.
5. Asumir siempre "app web con dashboard" sin evaluar alternativas.
6. Ir de prisa saltando fases en vez de disenar bien.
7. Preguntar al usuario cosas que se pueden resolver leyendo el codigo o la BD.
8. Declarar "hecho" sin verificar que funciona de verdad.
9. Proponer herramientas de un SO diferente al del usuario.
10. Usar emojis donde deberian ir iconos de una libreria profesional.
11. Usar una sola herramienta de diseno cuando hay multiples disponibles.
12. No investigar competidores antes de empezar a construir.

---

## Resumen de fases

```
 0. Socratico       -> Escuchar, investigar mercado, cuestionar (4 rondas + reflexion)
 1. Tipo solucion   -> CLI/bot/MCP/app/agente (evaluar SO)
 2. Diseno          -> C4 + design system + wireframes multi-tool + navegacion Excalidraw + user flows
 3. SPEC            -> Reflexion + modelo de datos + checkpoints deployables
 4. Edge cases      -> ANTES del codigo, TODOS los posibles, sin limite
 5. Scaffold        -> Estructura + config + verificar que compila
 6. Core            -> Domain, ports, casos de uso, agentes
 7. Infra           -> BD, LLM, scraping, adapters
 8. Integracion     -> Conectar todo, Streamlit para validar
 9. Testing         -> Unit 80% + integration + E2E Playwright + edge cases + coverage report
10. Seguridad       -> Validation, auth, headers, rate limit, audit
11. Deploy          -> Docker + CI/CD + health checks + rollback + SSL + go-live checklist
12. Iteracion       -> Features (mini-socratico) / bugs (fix+test) / mejoras (medir)
13. Escalado        -> Profiling + caching + monitoring + health dashboard
14. Mantenimiento   -> CI/CD + backups + docs auto-generadas + migraciones + plan deprecacion
```

$ARGUMENTS
