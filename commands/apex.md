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

Cuestiona la idea ANTES de construir nada.

Sub-pasos en orden:

- **[0a]** Ronda 1: "Que lo diferencia de lo que ya existe? Que has probado y
  por que no te sirve?"
- **[0b]** Ronda 2: "Realmente necesitas una UI? Un CLI, bot de Telegram,
  servidor MCP, o script no basta?"
- **[0c]** Ronda 3: "Quien lo usa? Con que frecuencia? Cuantos usuarios?"
- **[0d]** Ronda 4: "Cual es el escenario donde falla? Que pasa si no tienes
  internet, si la BD se corrompe, si el scraping falla?"
- **[0e]** Ronda 5: "Si solo pudieras hacer UNA cosa, cual seria?"
- **[0f]** Registrar TODAS las decisiones con `apex_add_decision(phase=0, ...)`
- **[0g]** `apex_set_phase(phase_number=0, status="completed")`

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

REGLA: NUNCA describas un diseno por texto. Usa Pencil MCP para crear un mockup
visual. Si la decision afecta al aspecto visual, DEBE acompanarse de un archivo
.pen.

Sub-pasos en orden:

- **[2a]** Diagrama C4 (context + container) con Mermaid. Validar que la
  arquitectura tiene sentido antes de continuar. Registrar con
  `apex_add_decision`.
- **[2b]** Wireframes principales con Pencil MCP. Crear un .pen por pantalla
  principal. Minimo: pantalla principal, flujo critico, pantalla de
  configuracion.
- **[2c]** Flujo de pantallas con Pencil MCP. Mapa de navegacion que muestre
  TODAS las pantallas conectadas con flechas. Cada boton/link tiene una flecha a
  la pantalla destino. Generar un .pen con el mapa completo de navegacion.
- **[2d]** User flows. Documentar los flujos principales del usuario paso a
  paso: desde que abre la app hasta que completa su objetivo. Formato: Accion ->
  Pantalla -> Resultado -> Siguiente accion.
- **[2e]** Registrar componentes detectados con `apex_add_component`
- **[2f]** `apex_set_phase(phase_number=2, status="completed")`

---

### Fase 3 -- SPEC

Especificacion por fases, no monolitica.

Sub-pasos en orden:

- **[3a]** Generar SPEC.md con secciones: Problema, Solucion, Usuarios,
  Funcionalidad core (fase 1), Funcionalidad extendida (fase 2+), Stack,
  Arquitectura, Restricciones, Metricas de exito.
- **[3b]** Dividir la funcionalidad en checkpoints (MVP -> v1 -> v2). Cada
  checkpoint debe ser deployable y usable.
- **[3c]** Definir criterios de "hecho" para cada checkpoint.
- **[3d]** Revisar con el usuario. Pedir feedback en bloque (NO interrumpir con
  preguntas una a una).
- **[3e]** Registrar SPEC como wiki: `apex_wiki_add(title="SPEC", ...)`
- **[3f]** `apex_set_phase(phase_number=3, status="completed")`

---

### Fase 4 -- Edge cases

ANTES de escribir codigo, pensar en que puede fallar.

Sub-pasos en orden:

- **[4a]** Generar EDGE-CASES.md con minimo 15 escenarios agrupados por
  categoria: inputs invalidos, red/servicios caidos, concurrencia, datos
  corruptos, limites (0, max, unicode, inyeccion), permisos, estados imposibles.
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
- **[9f]** `apex_set_phase(phase_number=9, status="completed")`

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
- **[11f]** `apex_set_phase(phase_number=11, status="completed")`

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
- **[14e]** `apex_set_phase(phase_number=14, status="completed")`

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
4. **NUNCA** describir un diseno visual con texto. Usar Pencil MCP para crear
   .pen files. Si la decision afecta al aspecto visual, DEBE tener mockup.
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

---

## Errores a evitar

1. Construir frontend antes de verificar que el backend devuelve datos reales.
2. No investigar fuentes de datos antes de implementar scrapers.
3. Tomar decisiones de diseno visual sin mockup en Pencil MCP.
4. SPEC monolitica sin checkpoints incrementales.
5. Asumir siempre "app web con dashboard" sin evaluar alternativas.
6. Ir de prisa saltando fases en vez de disenar bien.
7. Preguntar al usuario cosas que se pueden resolver leyendo el codigo o la BD.
8. Declarar "hecho" sin verificar que funciona de verdad.
9. Proponer herramientas de un SO diferente al del usuario.
10. Usar emojis donde deberian ir iconos de una libreria profesional.

---

## Resumen de fases

```
 0. Socratico       -> Cuestiona, filtra, refina (5 rondas)
 1. Tipo solucion   -> CLI/bot/MCP/app/agente (evaluar SO)
 2. Diseno          -> C4 + wireframes Pencil + flujo pantallas + user flows
 3. SPEC            -> Por fases con checkpoints deployables
 4. Edge cases      -> ANTES del codigo, minimo 15 escenarios
 5. Scaffold        -> Estructura + config + verificar que compila
 6. Core            -> Domain, ports, casos de uso, agentes
 7. Infra           -> BD, LLM, scraping, adapters
 8. Integracion     -> Conectar todo, Streamlit para validar
 9. Testing         -> Unit 80% + integration + E2E Playwright + edge cases
10. Seguridad       -> Validation, auth, headers, rate limit, audit
11. Deploy          -> Docker + CI/CD GitHub Actions + health checks + rollback
12. Iteracion       -> Features (mini-socratico) / bugs (fix+test) / mejoras (medir)
13. Escalado        -> Profiling + caching + monitoring + health dashboard
14. Mantenimiento   -> CI/CD + backups + docs auto-generadas + migraciones
```

$ARGUMENTS
