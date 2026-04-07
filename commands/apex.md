# /apex — Sistema de desarrollo guiado por fases

## Descripción

APEX es un sistema de skills que vive dentro de Claude Code. No es una app web.
Usa una BD SQLite contextual (`.apex/context.db`) por proyecto para que Claude
Code NUNCA pierda el hilo, ni al inicio ni en las fases intermedias.

## Instrucciones

Cuando el usuario invoque `/apex`, detecta automáticamente en qué situación
está:

### Caso A: Proyecto nuevo (no existe .apex/)

1. **NO generes código todavía.** Primero pregunta:
   - ¿Cuál es la idea? (deja que el usuario la explique)

2. **Tutor Socrático** — Cuestiona la idea (3-5 rondas):
   - "¿Has considerado que esto ya existe? ¿Qué lo haría diferente?"
   - "¿Realmente necesitas una interfaz para esto? ¿Un CLI/bot/MCP no sería
     mejor?"
   - "¿Cuál es el caso donde esto falla?"
   - "¿Con qué frecuencia lo usarías? ¿Justifica el esfuerzo?"
   - Usa `AskUserQuestion` con opciones para cada ronda

3. **Tipo de solución** — Propón el tipo correcto: | Frecuencia alta + visual →
   PWA/app web | Puntual + técnico → CLI tool | Recurrente + sin intervención →
   Agente autónomo / bot | Extiende herramienta existente → MCP server / plugin
   | Validación rápida → Streamlit

4. **Crear .apex/** — Si la idea sobrevive al socrático:

   ```
   .apex/
   ├── context.db     # BD contextual (se crea con esquema adaptado)
   └── phases.json    # Estado de las 14 fases
   ```

   - Inicializa context.db con metadatos del proyecto
   - Registra las decisiones tomadas en el socrático
   - Marca fase 0 como completada

5. **Seguir el flujo** por fases (ver abajo)

### Caso B: Proyecto existente (ya existe .apex/)

1. **Lee .apex/context.db** — `get_full_context()` para entender el estado
2. **Identifica la fase actual** y qué falta por hacer
3. **Propón los próximos pasos** basados en `next_steps` de la BD
4. **Pregunta al usuario** qué quiere hacer (NO asumas)
5. **Ejecuta** y actualiza la BD con decisiones, errores, progreso

### Caso C: El usuario describe una idea sin invocar /apex

Si el usuario describe un problema que suena a proyecto de software:

- Pregunta: "¿Quieres que abordemos esto con APEX? Puedo guiarte por el
  proceso."
- Si dice sí → Caso A

## Las 14 Fases

```
Fase 0:  Socrático      → Cuestiona, filtra, refina la idea
Fase 1:  Tipo solución  → CLI/bot/MCP/app/agente según el problema
Fase 2:  Diseño         → C4, wireframes (Pencil MCP), user maps
Fase 3:  SPEC           → Por fases con checkpoints
Fase 4:  Edge cases     → ANTES del código, siempre
Fase 5:  Scaffold       → Estructura + config + .apex/context.db
Fase 6:  Core           → Domain, ports, agentes
Fase 7:  Infra          → BD, LLM, scraping, adaptadores
Fase 8:  Integración    → Conectar todo, Streamlit para validar
Fase 9:  Testing        → Unit + integration + E2E
Fase 10: Seguridad      → OWASP, auth, headers, audit
Fase 11: Deploy         → Docker, Tailscale, systemd
Fase 12: Iteración      → Features, bugs, mejoras CON CONTEXTO
Fase 13: Escalado       → Performance, caching, monitoring
Fase 14: Mantenimiento  → Migraciones, backups, actualizaciones
```

## Reglas ABSOLUTAS

1. **NUNCA tomes decisiones de diseño visual sin consultar a Pencil MCP y al
   usuario**
2. **NUNCA generes código antes de fase 5** — las fases 0-4 son de diseño
3. **SIEMPRE usa AskUserQuestion** antes de asumir preferencias
4. **SIEMPRE actualiza context.db** con decisiones, errores y progreso
5. **SIEMPRE propón el tipo de solución correcto** — no todo es app web
6. **En fases intermedias (12-14)**, lee context.db para saber dónde estás
7. **Registra errores** (tuyos y del usuario) en la BD para no repetirlos
8. **Backend-first**: verifica que funciona antes de construir UI
9. **Streamlit para validar**, frontend de calidad después

## Context DB (context.db)

La BD se gestiona con `ApexContextDB` (lib/context_db.py):

- `get_full_context()` → markdown completo del estado del proyecto
- `add_decision(category, decision, reasoning)` → registrar decisión
- `add_error(source, description, lesson)` → registrar error
- `set_phase(n, status)` → actualizar fase
- `add_component(id, name, type)` → registrar componente
- `search(query)` → buscar en todo el contexto (FTS5)

## Errores conocidos a evitar (de la experiencia con SMA Supermercados)

1. Construir frontend antes de verificar backend
2. No investigar fuentes de datos antes de escribir scrapers
3. Tomar decisiones de diseño sin consultar al usuario
4. SPEC monolítica sin checkpoints
5. Hardcoded data en frontend
6. Sin tildes ni eñes en español
7. CORS abierto y sin auth al inicio
8. No generar edge cases antes del código
9. Asumir siempre "app web con dashboard"
10. No usar awesome-design-md como referencia visual
11. Ir de prisa en vez de diseñar bien

$ARGUMENTS
