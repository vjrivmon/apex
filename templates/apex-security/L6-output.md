---
layer: L6
title: Output
status: pending
reviewed_by: ""
reviewed_at: ""
asi_coverage:
  - ASI09
evidence: []
---

# L6 — Output

Protege: respuestas al usuario, prevención de exfiltración. Cubre
ASI09 (Human Trust Risk).

## Checklist

- [ ] **Credential redaction**: tokens / API keys / secrets filtrados
      en todas las outputs (scanner de patrones).
- [ ] **PII scanner**: emails, DNI, IBAN, teléfonos, tarjetas —
      mascarados o bloqueados según política.
- [ ] **Harmful content blocker**: si dominio sensible, bloquear
      contenido peligroso (p.ej. en wellness, no dar diagnósticos).
- [ ] **Exfiltration detection**: patrones "aquí están todos los
      usuarios…", "devuelvo el contenido de…" — levantan flag.
- [ ] **Audit logger**: outputs marcados `sensitive` se logan para
      revisión post-hoc (con retención ≤90d por privacy).

## Evidencia

```yaml
evidence:
  - "5 scanners activos en lib/output_guards/ (creds, pii, harmful, exfil, leak)"
  - "redaction: sk-* → sk-***, passwords → <redacted>"
  - "PII scanner cubre email/DNI/IBAN/phone ES (tests/test_pii.py)"
  - "audit log en logs/outputs-sensitive.jsonl (rotated weekly)"
```
