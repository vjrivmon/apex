---
layer: L8
title: Identity
status: pending
reviewed_by: ""
reviewed_at: ""
asi_coverage:
  - ASI03
  - ASI10
evidence: []
---

# L8 — Identity

Protege: identidades de agentes, credenciales, permisos. Cubre ASI03
(Identity Abuse) y ASI10 (Rogue Agents).

## Checklist

- [ ] **Agent identity**: cada agente (humano, sub-agente, MCP) tiene
      identity verificable (DID, public key, API key con scope).
- [ ] **JIT permissions**: permisos se otorgan para una acción
      concreta y se revocan al terminar. No hay permisos "siempre
      activos".
- [ ] **Credential rotation**: llaves rotan cada ≤90d. Alerta si falta
      <7d para expirar.
- [ ] **Revocation**: lista de identidades revocadas; verificación
      antes de cada request.
- [ ] **Audit trail**: quién autenticó, cuándo, con qué permisos.

## Evidencia

```yaml
evidence:
  - "agent registry en state/agents.yml con public keys"
  - "JIT permissions grant/revoke en lib/auth/jit.py"
  - "rotation policy 90d con alerta a -7d (cron: check_expiry.py)"
  - "CRL check en middleware/auth.py:34"
  - "audit trail en logs/auth.jsonl"
```
