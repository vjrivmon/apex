---
layer: L7
title: Inter-Agent
status: pending
reviewed_by: ""
reviewed_at: ""
asi_coverage:
  - ASI07
  - ASI10
evidence: []
---

# L7 — Inter-Agent

Protege: comunicación entre agentes, cadenas de delegación (solo si el
sistema es SMA). Cubre ASI07 (Inter-Agent) y ASI10 (Rogue Agents).

Si el proyecto es un solo agente, marcar `status: passed` con
`evidence: ["sistema mono-agente, no aplica L7"]`.

## Checklist

- [ ] **Mutual auth**: cada mensaje entre agentes lleva HMAC firmado
      con la clave del emisor.
- [ ] **Trust scoring con time-decay**: cada agente tiene score que
      sube con interacciones exitosas y decae con inactividad.
- [ ] **Delegation depth**: max N niveles de delegación (default 3).
      Super delegaciones rechazadas.
- [ ] **Message replay protection**: nonce + timestamp, ventana ≤30s.

## Evidencia

```yaml
evidence:
  - "HMAC SHA256 en todos los mensajes A2A (lib/a2a/auth.py)"
  - "trust matrix en state/trust_scores.json, decay 0.1/d"
  - "delegation depth 3 en orchestrator.py:102"
  - "nonce+timestamp window 30s en lib/a2a/replay_guard.py"
```
