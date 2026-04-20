---
layer: L4
title: Planning
status: pending
reviewed_by: ""
reviewed_at: ""
asi_coverage:
  - ASI02
  - ASI05
  - ASI08
evidence: []
---

# L4 — Planning

Protege: decision-making del agente, cadenas de tool calls. Cubre
ASI02 (Tool Misuse), ASI05 (Code Execution), ASI08 (Cascading Failures).

## Checklist

- [ ] **Action chain tracking**: cada tool call se registra con
      request_id, parent_id, timestamp.
- [ ] **Semantic risk scoring**: cada tool tiene risk level asignado
      (read=1, write=3, exec=5, external-call=7).
- [ ] **Multi-step attack detection**: heurísticas para secuencias
      sospechosas (ej. read-secret → write-external, exec-code tras
      input-usuario).
- [ ] **Chain depth limit**: max N tool calls por request (default 8).
- [ ] **Circuit breaker**: tras M fallos consecutivos, abrir CB por T
      segundos.

## Evidencia

```yaml
evidence:
  - "action chain en lib/audit/chain.py con request_id propagado"
  - "risk scores en config/tool_risks.yml"
  - "detector en lib/guards/chain_anomaly.py (patrones: leak, escalate)"
  - "chain depth 8 configurado en orchestrator.py:64"
  - "circuit breaker con cooldown 60s tras 10 fallos (lib/resilience/cb.py)"
```
