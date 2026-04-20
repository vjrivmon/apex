---
layer: L2
title: Storage
status: pending
reviewed_by: ""
reviewed_at: ""
asi_coverage:
  - ASI06
evidence: []
---

# L2 — Storage

Protege: context.db, memoria persistente del agente, secrets. Cubre
ASI06 (Memory Poisoning).

## Checklist

- [ ] **Cifrado at-rest**: AES-256-GCM en datos sensibles de la DB
      (ej. credenciales de usuario, PII).
- [ ] **HMAC integrity**: snapshots de memoria firmados; al cargar,
      verificar antes de usar.
- [ ] **Tamper detection**: hash de la DB comparado en startup.
- [ ] **Secrets fuera del repo**: `.env` en `.gitignore`, `.env.example`
      solo con nombres de variables.
- [ ] **Backups cifrados** con rotación y restore probado.

## Evidencia

```yaml
evidence:
  - "cifrado AES-256-GCM de user_secrets en lib/crypto.py:42"
  - "HMAC SHA256 en lib/memory/verify.py, clave rotada 90d"
  - "hash de context.db comparado al arrancar (app/startup.py:18)"
  - ".env en .gitignore verificado; secrets en vault"
```
