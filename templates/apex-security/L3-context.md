---
layer: L3
title: Context
status: pending
reviewed_by: ""
reviewed_at: ""
asi_coverage:
  - ASI01
  - ASI06
evidence: []
---

# L3 — Context

Protege: system prompt, identity anchoring, contexto del agente. Cubre
ASI01 (Goal Hijacking) y ASI06 (Memory Poisoning).

## Checklist

- [ ] **GoalLock**: system prompt contiene mínimo 3 canary tokens
      (distribuidos, no concentrados). Si cualquiera cambia → alerta.
- [ ] **Canary verification**: cada N mensajes se verifica que los
      canaries siguen ahí y en orden.
- [ ] **Template injection stripping**: inputs del usuario pasan por
      sanitizer antes de inyectar en plantillas.
- [ ] **Prompt storage**: prompts críticos en `lib/prompts/` como
      constantes, con hash versionado.
- [ ] **Diff monitoring**: si el prompt activo difiere del hash
      esperado, log ERROR y bloquear llamada.

## Evidencia

```yaml
evidence:
  - "3 canary tokens en lib/prompts/system.py (positions: pre-role, mid-rules, pre-task)"
  - "verificación en lib/guards/goal_lock.py cada 5 turnos"
  - "template sanitizer con escape de {{ }} y marcadores Jinja"
  - "prompt hashes en lib/prompts/__init__.py (auditable)"
```
