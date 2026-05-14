# Fase 10 — Seguridad (OWASP + base)

## Gate de entrada (OBLIGATORIO antes del sub-paso [10a])

```
apex_phase_entry_check(phase=10, context_hint="<endpoints publicos y datos sensibles>")
```

Lee el bloque `### Lecciones cross-project aplicadas`. Presta especial atencion
a errores de secretos en repo, CORS abierto, o rate limiting ausente.

**Queries internas**: "seguridad OWASP secretos errores", "rate limit headers auth".

## Sub-pasos en orden

- **[10a]** Input validation y sanitizacion en todos los endpoints.
- **[10b]** Autenticacion si aplica (auth flow completo, no solo middleware).
- **[10c]** Headers de seguridad: CORS restrictivo, CSP, HSTS,
  X-Frame-Options.
- **[10d]** Rate limiting en endpoints publicos.
- **[10e]** Audit: revisar que no hay secretos en el codigo, .env en
  .gitignore.
- **[10e-sec]** Ejecutar scanner de secretos:
  ```bash
  git log --all --oneline | head -20  # revisar historial reciente
  grep -rn "sk-\|ghp_\|AKIA\|AIza\|BEGIN PRIVATE" . --include="*.py" --include="*.ts" --include="*.js" --include="*.env*" | grep -v ".gitignore" | grep -v "node_modules"
  ```
  Si hay hits en archivos trackeados: usar `git filter-repo` o BFG para limpiar historial.
  Registrar con `apex_add_decision(category="security", decision="secretos auditados limpio")`.
  Verificar brute-force protection: rate limiting con backoff exponencial en login/auth endpoints
  (minimo: 5 intentos → 429 con Retry-After header).
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
