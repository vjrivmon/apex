---
name: architect
description: "Propone el tipo de solución adecuado (CLI+alias, PWA/app web, bot de Telegram, MCP server/plugin, script, agente+cron, API/microservicio, librería/SDK, Streamlit/Gradio) según frecuencia de uso, perfil del usuario y herramientas existentes. No todo es app web con dashboard. Usar tras el socrático, antes del diseño. Triggers ES/EN — tipo de solución, ¿qué construyo?, ¿app web o CLI?, solution type."
---

# SolutionTypeAdvisor — Propone el tipo correcto de solución

## Cuándo activar

Después del socrático (fase 0), antes del diseño (fase 2).

## Objetivo

Proponer el tipo de solución adecuado al problema. NO todo es "app web con
dashboard". La solución debe encajar con la frecuencia de uso, el perfil del
usuario, y el contexto existente.

## Tabla de decisión

| Frecuencia         | Visual | Usuarios         | Ya tiene herramienta | → Tipo              |
| ------------------ | ------ | ---------------- | -------------------- | ------------------- |
| Alta + diaria      | Sí     | Múltiples        | No                   | PWA / App web       |
| Alta + diaria      | No     | Solo yo          | No                   | CLI + alias         |
| Puntual            | No     | Técnico          | No                   | Script / CLI        |
| Recurrente         | No     | Nadie (autónomo) | No                   | Agente + cron       |
| Consulta rápida    | No     | Desde móvil      | Telegram/WhatsApp    | Bot                 |
| Extensión          | -      | -                | Claude Code / IDE    | MCP server / plugin |
| Validación         | Mínimo | Interno          | No                   | Streamlit / Gradio  |
| Múltiples sistemas | No     | Máquinas         | No                   | API / microservicio |
| Reutilización      | No     | Devs             | No                   | Librería / SDK      |

## Combinaciones comunes

- **CLI + cron + bot**: Scraping nocturno + alerta por Telegram
- **API + Streamlit**: Backend robusto + UI de validación rápida
- **MCP + agente**: Extender Claude Code con capacidades específicas
- **PWA + API + bot**: App completa con notificaciones push

## Preguntas para decidir (usar AskUserQuestion)

1. "¿Con qué frecuencia usarás esto?"
   - Varias veces al día → necesita interfaz accesible
   - 1x/semana → puede ser CLI o bot
   - 1x/mes → script es suficiente

2. "¿Necesitas ver datos visualmente?"
   - Gráficas, tablas, dashboards → web/Streamlit
   - Solo un número o texto → CLI/bot

3. "¿Lo usas tú solo o más personas?"
   - Solo yo → puede ser CLI
   - Mi pareja y yo → PWA simple
   - Equipo → app web completa

4. "¿Ya usas alguna herramienta que podríamos extender?"
   - Claude Code → MCP server
   - Telegram → bot
   - VS Code → extensión
   - Nada → app independiente

5. "¿Un bot de Telegram que te avise no sería más rápido que un dashboard?"

## Después de decidir

- Registrar la decisión con justificación en context.db
- add_decision("tipo_solución", "PWA + bot Telegram", "Frecuencia diaria +
  pareja + móvil")
- Avanzar a fase 2 (diseño)
