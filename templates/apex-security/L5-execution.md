---
layer: L5
title: Execution
status: pending
reviewed_by: ""
reviewed_at: ""
asi_coverage:
  - ASI02
  - ASI03
  - ASI05
evidence: []
---

# L5 — Execution

Protege: ejecución de código, llamadas a servicios externos. Cubre
ASI02, ASI03, ASI05.

## Checklist

- [ ] **DNS rebinding guards** en todas las requests outbound.
- [ ] **Rate limiting** por tool, por user, por IP.
- [ ] **Circuit breakers** con half-open state tras cooldown.
- [ ] **Resource budgets**: CPU/RAM/disk caps por invocación (usar
      `resource.setrlimit` en Python, o container limits).
- [ ] **Sandbox** para código generado: containers efímeros o
      `firejail` / `bwrap`.
- [ ] **Allowlist de hosts**: outbound solo a dominios previstos.

## Evidencia

```yaml
evidence:
  - "DNS rebinding guard en lib/http/safe_client.py:23"
  - "rate limit por tool en middleware/tool_limits.py"
  - "CB half-open en lib/resilience/cb.py"
  - "rlimit CPU=5s, RSS=512M en subprocess_runner.py"
  - "outbound allowlist: api.openai.com, localhost:11434 (config/allowlist.yml)"
```
