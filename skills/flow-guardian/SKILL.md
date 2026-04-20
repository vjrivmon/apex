# FlowGuardian — Vigilante de Fases

## Cuándo activar

SIEMPRE. Se consulta antes de ejecutar cualquier acción en un proyecto APEX.

## Objetivo

Garantizar que se siguen las 14 fases en orden. Bloquear avance si la fase
anterior no está completa. Proponer la acción correcta según la fase actual.

## Regla cross-project (OBLIGATORIA)

Antes de proponer una decisión de stack, arquitectura, diseño visual, UX,
scraping, auth, deploy o cualquier elección que ya se haya enfrentado en otro
proyecto, ejecutar `apex_search_cross_project(query)` con los términos
relevantes. Si la tool devuelve errores o decisiones previas:

- **Errores**: NO los repitas. Explica al usuario qué error ocurrió en qué
  proyecto y por qué no vamos a repetirlo.
- **Decisiones vigentes**: propónlas como primera opción a menos que el
  contexto lo impida.
- **Decisiones invalidadas**: explícitamente evita el camino invalidado.

Si la tool devuelve "hub.db no disponible", se puede continuar, pero avisa al
usuario que el segundo cerebro está offline y registra un error para que se
lance `apex-hub` antes de seguir.

## Las 14 fases y sus criterios de completitud

### Fase 0: Socrático

- [ ] Idea cuestionada (mínimo 3 rondas)
- [ ] Tipo de solución propuesto y aceptado
- [ ] Decisiones registradas en context.db

### Fase 1: Tipo de solución

- [ ] CLI/bot/MCP/app/agente decidido
- [ ] Justificación documentada
- [ ] Usuario confirmó

### Fase 2: Diseño

- [ ] Diagrama C4 context (Pencil MCP)
- [ ] User map / user flow
- [ ] Wireframes de pantallas principales (si aplica UI)
- [ ] Todos aprobados por el usuario

### Fase 3: SPEC

- [ ] SPEC.md generado con checkpoints
- [ ] Problema, público, funcionalidades documentadas
- [ ] Stack definido
- [ ] Arquitectura SMA definida (si aplica)

### Fase 4: Edge cases

- [ ] EDGE-CASES.md generado
- [ ] Mínimo 15 edge cases identificados
- [ ] Estrategia para cada uno

### Fase 5: Scaffold

- [ ] Estructura de directorios creada
- [ ] .apex/context.db inicializada
- [ ] Config files (.env.example, .gitignore, etc.)
- [ ] Git inicializado

### Fase 6: Core

- [ ] Domain entities implementados
- [ ] Port interfaces definidos
- [ ] Tests de domain pasando

### Fase 7: Infraestructura

- [ ] Adaptadores implementados (BD, LLM, APIs)
- [ ] Tests de integración pasando
- [ ] Datos reales verificados (si aplica scraping)

### Fase 8: Integración

- [ ] Todo conectado end-to-end
- [ ] Streamlit/UI de validación funcionando
- [ ] Datos fluyendo de verdad

### Fase 9: Testing

- [ ] Tests unitarios (>80% cobertura de domain)
- [ ] Tests de integración
- [ ] Edge cases cubiertos

### Fase 10: Seguridad

- [ ] Input sanitization
- [ ] Rate limiting
- [ ] CORS restringido
- [ ] Auth (si aplica)
- [ ] Audit log

### Fase 11: Deploy

- [ ] Plan de deploy documentado
- [ ] Docker/systemd configurado
- [ ] Health checks

### Fase 12: Iteración

- [ ] context.db actualizada con estado
- [ ] Próximos pasos definidos
- [ ] Errores registrados

### Fase 13-14: Escalado + Mantenimiento

- [ ] Performance evaluada
- [ ] Backups configurados
- [ ] Migraciones documentadas

## Cómo actuar

1. Leer context.db → fase actual
2. Verificar criterios de la fase actual
3. Si no están completos → proponer qué falta
4. Si están completos → proponer avanzar a la siguiente fase
5. NUNCA dejar que se salten fases 0-4 sin completar
