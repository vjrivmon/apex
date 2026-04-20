# Fase 14 — Mantenimiento

## Sub-pasos en orden

- **[14a]** CI/CD verificado y funcionando (si no se hizo en fase 11,
  hacerlo ahora).
- **[14b]** Backups automatizados: script cron o GitHub Action que respalde
  BD y configuracion. Documentar frecuencia y ubicacion.
- **[14c]** Documentacion auto-generada desde context.db. Generar estos
  archivos:
  - ARCHITECTURE.md — decisiones de arquitectura + diagrama C4 actualizado
  - STACK.md — tecnologias elegidas y POR QUE (extraido de decisions en
    context.db)
  - GUIDE.md — como funciona la app para el usuario final (flujos
    principales)
  - DECISIONS.md — historial completo de decisiones + invalidaciones
  - CHANGELOG.md — generado desde `git log --oneline`
- **[14d]** Migraciones de BD documentadas: cada cambio de esquema con su
  migracion reversible.
- **[14e]** Plan de deprecacion: Documentar que pasa cuando:
  - Una dependencia deja de mantenerse (alternativas evaluadas)
  - Una API externa cambia (versioning strategy)
  - Un modelo de Ollama se retira (fallback models)
  Configurar: dependabot o renovate para PRs automaticos de actualizacion.
  Registrar con `apex_add_decision(category="maintenance", decision="...")`.
- **[14f]** Publicar al portfolio si aplica: `apex_portfolio_draft(slug=...,
  apply=false)` genera MDX en vr-web para revision manual.
- **[14g]** `apex_set_phase(phase_number=14, status="completed")`.

## Criterio de salida

- CI/CD verde con lint+test+build+deploy.
- Backups automaticos + prueba de restore.
- 5 docs auto-generadas presentes.
- Migraciones documentadas.
- Plan de deprecacion escrito.
- (Opcional) Portfolio draft generado.
- Fase marcada como `completed` en context.db.
