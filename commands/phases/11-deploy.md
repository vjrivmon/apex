# Fase 11 — Deploy

**Pre-requisito técnico bloqueante**: el gate 10.5 (AgentArmor) debe
estar PASSED y el grader de fase 10 debe tener `should_block=false`.

El handler MCP de `apex_set_phase` y el hook `phase-gate.py` rechazan la
transición a fase 11 si el verdict de fase 10 está bloqueado o si las
8 capas L1-L8 de AgentArmor no son `passed`. No hay forma de avanzar a
deploy sin pasar la security gate, salvo override manual con
`force=True, force_reason="..."` (registrado como apex_add_error
severity=high).

## Sub-pasos en orden

- **[11a]** Verificar gate 10.5 vía `apex_security_gate(...)` y
  `apex_grader_evaluate(phase=10)`. Si alguno bloquea, parar y resolver.
- **[11b]** Docker / systemd / proceso configurado. Verificar que arranca
  limpio. Usa `apex_scaffold_devops(stack=...)` para templates multi-stage.
- **[11c]** CI/CD con GitHub Actions: template auto-generado que incluya
  lint, test, build. Crear `.github/workflows/ci.yml`.
- **[11d]** Auto-deploy on push: staging en PR merge, production en
  tag/release.
- **[11e]** Health checks post-deploy: endpoint `/health` que verifique BD,
  servicios externos, disco.
- **[11f]** **Smoke test post-deploy obligatorio**: tras el primer deploy
  exitoso, ejecutar smoke test E2E (`curl /health`, login mínimo si
  aplica, una operación crítica). Registrar el resultado con
  `apex_add_decision(category="deploy", decision="Smoke test go-live: PASS",
  reasoning="<output del curl/playwright>")`.
- **[11g]** Rollback plan documentado: como volver a la version anterior en
  menos de 5 minutos. Registrar con `apex_wiki_add(title="ROLLBACK-PLAN")`.
- **[11h]** Dominio y SSL: Configurar dominio (si aplica). Opciones:
  - Caddy (auto-SSL con Let's Encrypt, configuracion minima)
  - Nginx + certbot
  - Cloudflare (DNS + proxy + SSL)
  Documentar configuracion elegida. Registrar con
  `apex_add_decision(category="deploy", decision="SSL: ...")`.
- **[11i]** Launch / Go-Live checklist:
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
- **[11j]** `apex_grader_evaluate(phase=11, mode="full")` y
  `apex_set_phase(phase_number=11, status="completed")` (rechazado si
  fase 10 / gate 10.5 no pasaron).

## Criterio de salida (outcome-based)

- Verdict de fase 10 `should_block=false`.
- Gate 10.5 (AgentArmor): 8 capas L1-L8 con status `passed`.
- Deploy reproducible (Docker o systemd).
- CI/CD green con lint+test+build.
- `/health` endpoint devuelve 200.
- Smoke test post-deploy: PASS registrado en decisions.
- Rollback plan escrito y probado.
- SSL configurado.
- Go-live checklist completo.
- Verdict de fase 11 `should_block=false`.
- Fase marcada como `completed` (sólo si verdict pasa).
