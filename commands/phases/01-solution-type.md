# Fase 1 — Tipo de solucion

Determinar la forma correcta del producto. NO asumir "app web con dashboard".

## Sub-pasos en orden

- **[1a]** Analizar las respuestas del socratico y el SO del usuario
  (`uname -s`).
- **[1b]** Evaluar opciones: CLI / bot / MCP server / app web / agente autonomo
  / Streamlit / script cron / extension.
- **[1c]** Decidir y registrar:
  `apex_add_decision(category="solution_type", decision="...", reasoning="...")`.
- **[1d]** Si tiene componente visual, decidir: PWA / desktop / mobile /
  terminal UI.
- **[1e]** `apex_set_phase(phase_number=1, status="completed")`.

## Regla

El agente decide el ORDEN, pero la FORMA del producto siempre se valida con el
usuario via `AskUserQuestion` con opciones concretas. Nunca asumir.

## Criterio de salida

- Una decision unica registrada en `category="solution_type"`.
- Justificacion escrita de por que NO son las otras opciones.
- Fase marcada como `completed` en context.db.
