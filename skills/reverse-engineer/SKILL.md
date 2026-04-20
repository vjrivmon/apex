# reverse-engineer — Ingeniería inversa de proyectos existentes

## Cuándo invocar

Siempre que `/apex` detecte **Caso B** (proyecto con código pero sin
`.apex/`) y el proyecto tenga más de ~50 archivos trackeados por git.
Para proyectos triviales, el onboarding superficial del comando basta.

## Regla número 1: el código manda

No confíes en `README.md` ni en `CLAUDE.md` como fuente de verdad
primaria. Están desactualizados con probabilidad alta. Si hay
discrepancia, **el código gana**. El scanner emite findings
"docs vs code" cuando detecta divergencias; repórtalas al usuario.

Lee los docs SOLO para:

- Extraer claims verificables ("tenemos tests con coverage", "está en
  producción", "arquitectura hexagonal").
- Medir edad (`git log -1 --format=%ct -- README.md`) para saber si la
  doc acompaña al código o está fosilizada.

## Flujo completo

1. **SCAN** — ejecutar `apex_reverse_scan(path)` (MCP tool). Devuelve
   un `ScanReport` con:
   - Completeness matrix por fase (0-14 + gate 10.5).
   - Findings retroactivos priorizados (alta/media/baja).
   - Anti-patterns cross-project (emojis, console.log, TODO viejos,
     Tailwind genérico, etc.).
   - Docs vs code mismatches.
2. **REVIEW** — leer el informe en markdown. Identificar los findings
   no-obvios (los de alta siempre; los de media si afectan al MVP).
3. **BRAINSTORM** — por cada finding no-obvio, invocar skill
   `brainstorming`. Recibe el finding + el ScanReport y devuelve 2-3
   soluciones con effort/impact usando
   `apex_search_cross_project(query)` para ver cómo se resolvió antes.
4. **ASK USER** — para cada finding no-obvio, usar `AskUserQuestion`
   con formato:
   ```
   "Detecté [FINDING]. ¿Es intencional?"
     a) Sí, saltar esta fase (documentar razón).
     b) No, priorizar como tarea ahora.
     c) No, pero dejarlo como backlog post-MVP.
     d) Parcial: existe en rama/carpeta que el scanner no vio.
   ```
   Anotar respuestas en una estructura `answers[]`.
5. **PLAN** — llamar a `apex_reverse_plan(scan_report, answers)`. Genera
   un `ActionPlan` con tareas priorizadas, mapeadas a fases a retomar.
6. **PRESENT** — mostrar el plan al usuario en bloque (NO interrumpir
   con preguntas). Pedir aprobación global.
7. **APPLY** — tras aprobación, llamar a `apex_onboard_apply(plan)`.
   Esto crea `.apex/` con:
   - `context.db` pre-cargada con decisiones retroactivas
     (`category="retroactive"`), componentes detectados, errores
     marcados como "no abordado en su fase".
   - Wiki con `entities/<stack>.md`, `concepts/architecture-as-is.md`,
     `concepts/gap-analysis.md`.
   - Fases marcadas como `completed/partial/pending` según el scan.
   - `next_steps` cargados con las tareas del plan.
8. **ITERATE** — arrancar desde la primera fase marcada `pending` o
   `partial` en orden numérico. No saltar. Cada fase completa hasta
   que su criterio de salida se cumpla.

## Brainstorming: qué preguntar y qué no

- **Sí preguntar**: decisiones de diseño, priorización MVP vs backlog,
  ambigüedad en el stack, elecciones con impacto en tiempo.
- **No preguntar**: cosas que el código ya dice (no preguntar "¿usas
  FastAPI?" si `pyproject.toml` lo declara).
- **Agrupar preguntas**: si hay 10 findings de fase 10 (security), no
  hacer 10 preguntas — hacer una ronda: "He detectado 10 issues de
  seguridad. ¿Abordarlos como bloque pre-deploy o como backlog?".

## Output esperado

Un `.apex/reverse-report-YYYY-MM-DD.md` en el proyecto escaneado,
persistente, que acompaña al `context.db` recién creada. Lo guarda
`apex_onboard_apply`.

## Relación con otros skills

- `onboard-existing` se queda para proyectos triviales (<50 archivos).
- `flow-guardian` retoma el control en el paso 8 (iteración de fases).
- `second-brain` se alimenta del `context.db` poblado.
- `security-audit` se invoca automáticamente si el scan detecta
  findings altos en fase 10.
