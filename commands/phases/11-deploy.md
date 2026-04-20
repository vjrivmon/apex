# Fase 11 — Deploy

Requiere que el gate de fase 10.5 (AgentArmor) este PASSED.

## Sub-pasos en orden

- **[11a]** Docker / systemd / proceso configurado. Verificar que arranca
  limpio. Usa `apex_scaffold_devops(stack=...)` para templates multi-stage.
- **[11b]** CI/CD con GitHub Actions: template auto-generado que incluya
  lint, test, build. Crear `.github/workflows/ci.yml`.
- **[11c]** Auto-deploy on push: staging en PR merge, production en
  tag/release.
- **[11d]** Health checks post-deploy: endpoint `/health` que verifique BD,
  servicios externos, disco.
- **[11e]** Rollback plan documentado: como volver a la version anterior en
  menos de 5 minutos. Registrar con `apex_wiki_add(title="ROLLBACK-PLAN")`.
- **[11f]** Dominio y SSL: Configurar dominio (si aplica). Opciones:
  - Caddy (auto-SSL con Let's Encrypt, configuracion minima)
  - Nginx + certbot
  - Cloudflare (DNS + proxy + SSL)
  Documentar configuracion elegida. Registrar con
  `apex_add_decision(category="deploy", decision="SSL: ...")`.
- **[11g]** Launch / Go-Live checklist:
  - [ ] Todos los tests pasan (green CI)
  - [ ] Security gate 10.5 PASSED
  - [ ] Backups configurados y probados
  - [ ] Monitoring activo (health checks respondiendo)
  - [ ] Documentacion de usuario lista
  - [ ] Rollback plan probado
  - [ ] Usuarios notificados / onboarding preparado
  - [ ] Metricas de exito definidas (de SPEC) → como medirlas
  Registrar fecha de lanzamiento en context.db con
  `apex_add_decision(category="launch", decision="Go-live: YYYY-MM-DD")`.
- **[11h]** `apex_set_phase(phase_number=11, status="completed")`.

## Criterio de salida

- Deploy reproducible (Docker o systemd).
- CI/CD green con lint+test+build.
- `/health` endpoint devuelve 200.
- Rollback plan escrito y probado.
- SSL configurado.
- Go-live checklist completo.
- Fase marcada como `completed` en context.db.
