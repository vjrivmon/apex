# Verificacion UX/UI automatica

Despues de CADA cambio de frontend (cualquier fase), ejecutar esta
verificacion:

1. Usar Playwright MCP (`mcp__playwright__browser_navigate` +
   `browser_take_screenshot`) para tomar screenshot de las pantallas
   afectadas.
2. Analizar automaticamente:
   - Spacing minimo 16px entre elementos interactivos.
   - Touch targets minimo 44px (idealmente 48px).
   - Contraste de texto: ratio minimo 4.5:1 (WCAG AA).
   - Fitts' Law: CTAs principales son grandes y accesibles.
   - No hay texto cortado ni overflow visible.
   - Emojis presentes? → BLOQUEAR (violacion regla absoluta #5).
   - Tildes o enes rotas? → BLOQUEAR (violacion regla absoluta #19).
   - Ancho editorial coherente? (max-w-5xl + max-w-[720px] interior) →
     regla absoluta #20.
3. Reportar violaciones al usuario como lista priorizada.
4. Registrar con `apex_add_error` si hay violaciones criticas.

## /apex:idea — Nueva idea a mitad de proyecto

Si el usuario dice "se me ha ocurrido algo", presenta una nueva idea, o
quiere anadir algo mientras esta en fases 6+:

1. Evaluar: es una feature del proyecto actual o un proyecto completamente
   nuevo?
2. **Si es feature del proyecto actual:**
   - Mini-socratico (2 rondas): "Que resuelve?" + "Como encaja con lo que
     hay?"
   - Registrar como next_step con prioridad: `apex_add_next_step(...)`.
   - Continuar con la fase actual. La idea se ejecutara cuando toque
     (fase 12) o si es critica, intercalarla ahora.
3. **Si es un proyecto nuevo:**
   - Proponer crear un directorio separado.
   - Iniciar el flujo /apex completo desde fase 0 en ese directorio.
   - NO mezclar con el proyecto actual.
