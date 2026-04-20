# /apex:reverse — Ingenieria inversa de un proyecto existente

Comando especializado para proyectos maduros (codigo real, historia git,
muchos archivos) donde el onboarding superficial del /apex Caso B es
insuficiente.

## Cuando usarlo

- El usuario ejecuta `/apex:reverse` en un directorio que ya tiene
  codigo trackeado en git pero NO tiene `.apex/`.
- Recomendado para repos con mas de ~50 archivos trackeados.
- Tambien sirve para re-auditar un proyecto con `.apex/` obsoleta que
  quieres refrescar.

## Regla absoluta

**El codigo es la fuente de verdad, NO los docs.** `README.md` y
`CLAUDE.md` suelen estar desactualizados (desarrollo en otra rama,
cambios sin propagar, afirmaciones aspiracionales). El scanner los lee
como pistas secundarias y emite findings cuando detecta divergencia
entre doc y codigo real.

## Flujo completo

### Paso 1: SCAN (read-only)

```
apex_reverse_scan(path="<path>", format="both", write_report=true)
```

Devuelve un `ScanReport` con:

- Metadata: lenguaje dominante, edad repo, ultimo commit, numero de
  archivos tracked.
- Completeness matrix fase 0-14 + gate 10.5 con evidencia positiva y
  missing por fase.
- Findings retroactivos clasificados alta/media/baja.
- Anti-patterns cross-project (emojis, console.log, CORS wildcards,
  secretos hardcoded, Tailwind generico).
- Docs vs code mismatches (ej: "README dice `production` pero no hay
  Dockerfile ni CI").

Con `write_report=true` persiste `.apex/reverse-report-YYYY-MM-DD.md`.

### Paso 2: REVIEW

Leer el report y extraer los findings no-obvios. Reglas:

- **Todos los findings de severity=high** van a preguntarse.
- **Findings de severity=medium** solo si bloquean MVP (fases 9, 10,
  10.5, 11).
- **Findings de severity=low** se agrupan en un solo bloque de
  confirmacion.

### Paso 3: BRAINSTORM

Para cada finding no-obvio invocar el skill `brainstorming`. Por cada
uno genera 2-3 opciones con effort/impact. Consulta
`apex_search_cross_project(query="<finding keyword>")` para basar las
opciones en soluciones ya validadas en otros proyectos del ecosistema.

### Paso 4: ASK USER (evitar falsos positivos)

Por cada finding usar `AskUserQuestion` con el formato:

```
question: "[F-10-01] Detecte CORS con wildcard en src/main.py:45. Intencional?"
options:
  a: "No, arreglarlo ahora (medium effort, high impact)"
  b: "Si, solo entorno dev. Documentar con decision"
  c: "Parcial: hay CORS custom en otra rama"
  d: "Ignorar — no es critico"
```

**Agrupar preguntas** cuando hay >5 findings del mismo tipo (ej: "He
detectado 12 emojis en componentes de UI. Quieres que los migre a
lucide-react en bloque o ir uno por uno?").

Guardar respuestas en `answers: {finding_id: "a|b|c|d"}`.

### Paso 5: PLAN

```
apex_reverse_plan(scan_report=<scan>, answers=<answers>)
```

Devuelve un `ActionPlan` con:

- `tasks[]` ordenados por action (now > verify > backlog > skip),
  severity y fase.
- `phases_to_retake[]`: fases marcadas `partial/missing/unknown` que
  habra que ejecutar secuencialmente.
- `summary`: conteo rapido.

### Paso 6: PRESENT + APPROVE

Mostrar el plan al usuario en **un solo bloque**. NO interrumpir con
preguntas individuales ya hechas en paso 4. Pedir aprobacion global:

```
"Plan propuesto: 12 tareas ahora, 8 backlog, 3 skipped. Retomaremos
desde fase 4 (edge cases). Procedo?"
```

Si el usuario rechaza o pide ajustes, volver al paso 4 para los items
concretos a revisar.

### Paso 7: APPLY

```
apex_onboard_apply(path=<path>, scan_report=<scan>, plan=<plan>)
```

Crea en el proyecto:

- `.apex/context.db` con schema completo.
- Decisiones retroactivas (`category="retroactive"`) una por finding.
- `next_steps` cargados con las tareas `now` + `verify`.
- Fases marcadas `completed/in_progress/pending` segun el scan.
- `wiki/concepts/gap-analysis.md` con el resumen del gap.
- Session log registrando el onboarding.

### Paso 8: ITERATE

Arrancar desde la primera fase marcada `pending` o `in_progress` en
orden numerico. Usar el comando `/apex` normal desde aqui — ya opera
sobre el `.apex/` poblado.

Si la primera fase pendiente es 12 (iteration), no hay fases
anteriores que reabrir — el proyecto esta en produccion y solo hay
que trabajar los next_steps del plan.

## Errores a evitar en /apex:reverse

1. **Confiar en README**: si el README dice "version 3.0 en
   produccion" pero el ultimo tag git es 1.2 de hace 6 meses, el
   codigo manda. Emitir finding "docs desactualizadas".
2. **Preguntar lo obvio**: no preguntar al usuario cosas que el codigo
   ya responde (stack, tipo de solucion, lenguaje).
3. **Asumir monolito = mal**: un script de 300 lineas puede ser
   perfecto para su proposito. Registrar `hexagonal=no` sin
   descalificar.
4. **Aplicar antes de aprobar**: NUNCA llamar a `apex_onboard_apply`
   sin aprobacion explicita del usuario.
5. **Escribir en el proyecto durante el scan**: el scan es read-only.
   Solo al paso 7 (apply) se escribe.

## Salida esperada

Al terminar, el usuario tiene:

- `.apex/` totalmente poblado con estado real.
- Un plan claro de qué fases retomar.
- next_steps accionables.
- Conocimiento sincronizado con `apex-hub/data/hub.db` (via scanner)
  para que proyectos futuros se beneficien.

$ARGUMENTS
