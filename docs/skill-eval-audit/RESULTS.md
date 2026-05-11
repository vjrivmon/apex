# Resultados — Auditoría de contraste de los SKILL.md de APEX

> Run: `iteration-1`, 2026-05-11. Herramienta: `agent-skills-eval` (darkrishabh).
> Target (agente bajo test): `qwen2.5:14b-instruct` (Ollama local).
> Juez: `gpt-oss:120b-cloud` (Ollama Cloud, tier free — el run completó sin rate-limits).
> 8 skills × 2 evals × 2 modos (with_skill / without_skill) = 32 ejecuciones del target + 32 del juez.
> Artefactos: `workspace/runs/iteration-1/` (`benchmark.json` por skill, `eval-*/{with,without}_skill/`, `report/index.html`).

## 1. Veredicto en una línea

**Sí, los SKILL.md mueven la aguja — y por mucho.** Media de pass-rate del juez:
**WITH = 59.9%** vs **WITHOUT = 22.4%** → **Δ = +37.5 puntos**. Las 8 skills
muestran delta positivo; ninguna empeora en agregado. Pero hay matices
importantes (§4) y un caso en que el skill induce un comportamiento *peor*
(code-review sobre código limpio).

## 2. Tabla resumen (pass-rate del juez sobre las assertions)

| Skill | WITH | WITHOUT | Δ (pts) | Lectura |
|---|---:|---:|---:|---|
| security-audit | 88% | 0% | **+88** | Sin el skill el 14B solo pide el fichero o suelta un checklist genérico; con el skill hace la auditoría real (encuentra la SQLi, da el fix parametrizado, matiza el CORS de dev). |
| improve-architecture | 50% | 0% | **+50** | El vocabulario canónico (deep/shallow, test de borrado, locality/leverage, lista de candidatos) solo aparece con el skill. |
| tdd | 58% | 12% | **+46** | Con el skill habla de red-green-refactor 1-test-1-impl e interfaz pública; sin él, pasos genéricos o "necesito ver el código". |
| diagnose | 54% | 12% | **+42** | Con el skill: "Fase 1 construye un bucle de feedback" primero, repetir el trigger, test de regresión, limpiar instrumentación. Sin él: pasos sueltos. |
| architect | 75% | 42% | **+33** | Con el skill aplica la tabla de decisión (frecuencia/usuario/herramienta existente → tipo); sin él propone "API REST + app móvil" por defecto. |
| code-review | 50% | 33% | **+17** | Eval del bug: with 100% / without 0% (sin skill "necesito ver el código"). **Eval de código limpio: with 0% / without 67%** — el skill hace que el 14B *invente* hallazgos [CRITICO]/[ALTO] en código correcto. Ver §4.2. |
| grill-with-docs | 29% | 17% | +12 | El más flojo. En one-shot el modelo dispara las 5 preguntas de golpe en vez de una a una (justo el comportamiento multi-turno que este harness no puede medir). Una assertion la dejó en blanco el juez (artefacto). |
| socratic | 75% | 62% | +12 | El 14B ya tiende a responder con preguntas sin el skill; el skill afila (existencia/diferenciación, ¿necesitas una app web?) pero el suelo ya estaba alto. |
| **Media** | **59.9%** | **22.4%** | **+37.5** | |

(Las assertions concretas y la evidencia que citó el juez están en `workspace/runs/iteration-1/<skill>/<eval>/<mode>/grading.json` y los outputs del target en `.../outputs/response.txt`.)

## 3. Hallazgos a favor de "los skills sirven"

- **El efecto más fuerte es en skills de proceso disciplinado** (security-audit,
  diagnose, tdd, improve-architecture): el skill aporta vocabulario y un orden
  de operaciones que el modelo base simplemente no tiene. Δ entre +42 y +88.
- **El skill convierte "no hago la tarea" en "hago la tarea".** En varios evals
  con fichero adjunto, el `without_skill` del 14B respondía "Claro, necesitaría
  ver el código…" — el wrapper `<file>…</file>` no le "suena" a código. Con el
  skill en el system prompt, se pone a trabajar. (Esto es real pero infla los
  deltas de los evals con adjunto — ver §4.1.)
- **architect y socratic** muestran que incluso donde el modelo base ya hace
  *algo* razonable, el skill lo empuja hacia la respuesta que APEX quiere
  (MCP server porque ya usas Claude Code; CLI+cron+bot en vez de dashboard).

## 4. Caveats — por qué estos números NO son la última palabra

### 4.1 El target es un 14B local, no Claude
Un `qwen2.5:14b` tiene mucho más headroom que Opus/Sonnet. Parte del Δ es
"el skill le enseña algo que Claude probablemente ya sabe". Con Claude como
target esperaría deltas más pequeños, sobre todo en code-review/socratic.
Además, varios baselines `without_skill` fallaron por *no engancharse con el
fichero adjunto* — eso no le pasaría a Claude. Conclusión: **los deltas de los
evals con `files/` (code-review #1, security-audit #1, tdd #1) están inflados**;
los de los evals sin adjunto (improve-architecture, diagnose, architect, los
socratic) son más limpios.

### 4.2 El skill puede inducir comportamiento *peor* (code-review sobre código limpio)
`code-review-says-lgtm-on-clean-code`: el `Money` que le pasé es correcto.
Sin el skill el 14B no inventa nada (2/3). **Con el skill, el 14B "cumple el
formato" y fabrica un `[CRITICO] money.py:L26` y un `[ALTO] money.py:L42`** —
exactamente lo que el skill prohíbe ("no crear issues fantasma", "decir LGTM").
El skill empuja a producir el *artefacto* (informe con hallazgos) más que a
respetar la *regla* (no inventar). Esto es una señal accionable: el SKILL.md de
code-review debería reforzar el caso "sin hallazgos" — quizá con un ejemplo
explícito de review que termina en "LGTM, sin hallazgos críticos" al principio,
no al final. (En un modelo más capaz puede no reproducirse; conviene re-correr
este eval con Claude antes de actuar.)

### 4.3 One-shot ≠ agéntico
`grill-with-docs` y, en parte, `socratic` y `tdd` están diseñados para
multi-turno (una pregunta → feedback → siguiente). En una sola respuesta el
modelo vuelca todo de golpe y la assertion "preguntas de una en una" falla
aunque el skill esté funcionando. Este harness mide "¿la guía cambia la primera
respuesta?", no "¿la guía conduce bien una conversación?". Las skills más
conversacionales están infravaloradas aquí.

### 4.4 Los SKILL.md están escritos para Claude Code
Mencionan `apex_search_cross_project`, `context.db`, `AskUserQuestion`, fases,
`wiki/decisions/` — el 14B no tiene nada de eso. El grueso del comportamiento
(vocabulario, severidades, umbral de confianza, tabla de decisión, orden de
fases) sí transfiere, pero parte del SKILL.md es ruido para el target. Un
SKILL.md "destilado" sin las referencias internas podría rendir aún mejor en
este setup — no necesariamente en el real.

### 4.5 Los evals los escribió Claude
Los `evals.json` son mi interpretación de qué *debería* provocar cada skill, y
las assertions están redactadas con el vocabulario del propio SKILL.md (p.ej.
"menciona seam y adapter"). Eso favorece estructuralmente al `with_skill`: si la
assertion pide una palabra que solo está en el skill, el baseline casi no puede
pasarla. Es un sesgo conocido de este tipo de eval; Vicente revisó y aprobó los
evals antes del run, pero conviene tenerlo presente al leer los Δ.

### 4.6 Artefactos del juez
- `grill-with-docs` eval B: el juez (gpt-oss) devolvió un `assertion_results`
  corto y dejó 2 de 3 assertions como "judge omitted this assertion result" →
  cuentan como FAIL. Subestima ese eval.
- `tdd` eval B `without_skill`: el juez puso `N/A` como evidencia en 3
  assertions (output del baseline demasiado pobre para evaluar) → FAIL. Correcto
  de facto, pero es un baseline degenerado, no una comparación informativa.

## 5. Qué haría con esto

1. **Re-correr con Claude como target** (vía un endpoint OpenAI-compat de
   Anthropic) para 3-4 evals clave — sobre todo `code-review-clean-code` (¿se
   reproduce la alucinación de hallazgos?) y los evals con `files/` (¿sigue
   habiendo Δ cuando el baseline sí lee el fichero?). Eso separa "el skill
   enseña algo" de "el skill compensa la debilidad del 14B".
2. **Acción concreta sobre code-review.md**: mover el ejemplo "LGTM / sin
   hallazgos" arriba y reforzar "no crear issues fantasma" — el run muestra que
   un modelo mediano lo ignora bajo presión de formato.
3. **Para las ~16 skills workflow/CLI**: este harness no las mide. Si Vicente
   quiere cobertura ahí, hace falta un harness propio que ejercite el bucle
   agéntico (tool calls, hooks, multi-turno) — anotado como sprint futuro.
4. **Si se decide que esto aporta**: institucionalizar `evals/evals.json` por
   skill en APEX (cada skill nueva ⇒ su eval), y meter `agent-skills-eval` como
   gate opcional en CI.

## 6. Reproducir

```bash
cd docs/skill-eval-audit
export OLLAMA_API_KEY=ollama
npx agent-skills-eval --config agent-skills-eval.yaml --baseline --report
# → workspace/runs/iteration-2/ (no sobrescribe iteration-1)
xdg-open workspace/runs/iteration-1/report/index.html
```
