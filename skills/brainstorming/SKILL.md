# brainstorming — Generación de soluciones por finding

## Cuándo invocar

Inmediatamente después de `apex_reverse_scan`. Para cada
`RetroactiveFinding` no-trivial, generar 2-3 soluciones candidatas con
estimación de effort/impact.

También puede invocarse a mano durante Fase 12 (Iteración) cuando
aparece un bug o una feature ambigua y se quiere un abanico de enfoques
antes de decidir.

## Regla número 1: basado en evidencia cross-project

**Antes** de inventar soluciones, consultar `apex_search_cross_project`
con el keyword del finding para ver cómo se resolvió en proyectos
anteriores. Los patrones que funcionaron se reutilizan; los que
fallaron se descartan.

```
cross = apex_search_cross_project(query="<finding keyword>")
```

Si hay hits con solución documentada: esa solución va la primera en el
abanico, marcada como "validada en proyecto X".

## Formato de salida

Por cada finding, producir:

```yaml
finding_id: F-9-01
finding_title: "Fase 9: Sin tests detectados"
options:
  - id: A
    label: "Quick path: pytest + coverage básico"
    effort: low       # <4h
    impact: medium
    description: >
      Añadir pytest con coverage=80% en domain/. Empezar por los 3
      módulos más críticos.
    source: "validado en DNI Valencia v4.0 (coverage 85%)"
  - id: B
    label: "Full path: unit + integration + E2E"
    effort: high      # >16h
    impact: high
    description: >
      pytest + integration con BD real + Playwright E2E. Cubre flujos
      de usuario completos. Requiere fixtures de datos.
    source: "validado en Osyris-Web (reducción 80% admin sin regresiones)"
  - id: C
    label: "Defer: documentar como backlog post-MVP"
    effort: minimal
    impact: low
    description: >
      Aceptar deuda técnica temporal. Solo válido si el proyecto es un
      spike o un prototipo desechable.
    source: "anti-patrón documentado en 3+ proyectos"
recommended: A
```

## Reglas de brainstorming

1. **Cuantificar effort**: low (<4h), medium (4-16h), high (>16h).
2. **Cuantificar impact** por fase a la que pertenece el finding:
   - Fase 9 (tests) / Fase 10 (security): impact alto por defecto.
   - Fase 13/14 (escalado/maintenance): impact medio o bajo.
3. **Incluir siempre una opción "defer"** con condición explícita
   ("solo si es un spike desechable"). Permite al usuario optar por no
   abordarlo ya sin sentir que se salta el framework.
4. **Cross-project source obligatorio** si existe un hit en
   `apex_search_cross_project`. Si no hay evidencia previa, marcar
   `source: "primera vez — sin precedente en el hub"`.
5. **Anti-patterns explícitos**: si el finding coincide con un
   anti-pattern de `commands/rules/errors-to-avoid.md` (ej. emojis,
   mock data), incluir referencia: `source: "regla absoluta #5"`.

## Integración con AskUserQuestion

Tras brainstorming, formatear preguntas para `AskUserQuestion`:

```python
question = f"[{finding.id}] {finding.title}"
options = [
  f"A. {opt.label} (effort={opt.effort}, impact={opt.impact})"
  for opt in finding.options
]
```

El skill `reverse-engineer` se encarga de invocar AskUserQuestion; este
skill solo produce el material.

## Output al `reverse-report`

Las opciones + decisión del usuario se persisten en el report. Si el
usuario elige B pero el recommended era A, queda registro del por qué
(en el campo `notes`).
