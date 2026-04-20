# Fase 10 — Seguridad (OWASP + base)

## Sub-pasos en orden

- **[10a]** Input validation y sanitizacion en todos los endpoints.
- **[10b]** Autenticacion si aplica (auth flow completo, no solo middleware).
- **[10c]** Headers de seguridad: CORS restrictivo, CSP, HSTS,
  X-Frame-Options.
- **[10d]** Rate limiting en endpoints publicos.
- **[10e]** Audit: revisar que no hay secretos en el codigo, .env en
  .gitignore.
- **[10f]** Registrar decisiones de seguridad con
  `apex_add_decision(category="security")`.
- **[10g]** `apex_set_phase(phase_number=10, status="completed")`.

## Criterio de salida

- Headers de seguridad configurados y verificados (securityheaders.com o
  equivalente).
- Validacion de inputs en cada endpoint.
- Sin secretos en repo (`gitleaks` o `trufflehog` limpio).
- Rate limiting activo en publicos.
- Fase marcada como `completed` en context.db.

## Siguiente paso OBLIGATORIO

Tras completar esta fase, **pasar OBLIGATORIAMENTE a fase 10.5 (AgentArmor
Gate)** antes de fase 11. Ver `phases/10.5-agentarmor-gate.md`.
