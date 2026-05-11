# Auditoría de contraste: ¿sirven de algo los SKILL.md de APEX?

> Estado: **EJECUTADO** (iteration-1, 2026-05-11). Resultados y veredicto en `RESULTS.md`.
> Decisiones §6 tomadas: alcance = 8 skills de inyección de conocimiento (las ~16 workflow/CLI
> quedan para un harness propio); target = `qwen2.5:14b-instruct` local; juez = `gpt-oss:120b-cloud`;
> evals revisados y aprobados antes del run.
> Creado: 2026-05-11. Este documento queda como registro del diseño; ver `RESULTS.md` para hallazgos.

## 1. Objetivo

Verificar **empíricamente** —no por intuición— si los archivos `SKILL.md` de
APEX cambian medible el comportamiento de un agente. Es decir: experimentos de
contraste **con skill vs. sin skill**, juzgados por un modelo evaluador.

Herramienta elegida por Vicente: **`agent-skills-eval`**
(https://github.com/darkrishabh/agent-skills-eval), de Rishabh ("darkrishabh").

## 2. Qué hace `agent-skills-eval` (resumen del README)

Framework de test para "Agent Skills" (el estándar abierto de Anthropic). Para
cada eval:

1. Manda el **mismo prompt** al modelo target **dos veces**:
   - Run A: con el `SKILL.md` inyectado en el contexto.
   - Run B: baseline, sin el skill.
2. Un **modelo juez** puntúa ambas salidas contra las mismas `assertions`.
3. Reporta pass/fail por lado → permite ver si el skill **mueve la aguja**.

Salida: artefactos JSON + informe HTML estático en `iteration-N/report/index.html`.
Cumple la spec de `agentskills.io` (validación de `SKILL.md`, schema de
`evals.json`, layout `iteration-N`, reglas de frontmatter, comparación baseline).

### Instalación / ejecución

```bash
npm install agent-skills-eval        # o: npx agent-skills-eval --help
```

Comando rápido (ejemplo del README):

```bash
npx agent-skills-eval ./skills \
  --target gpt-4o-mini \
  --judge gpt-4o-mini \
  --baseline \
  --strict
```

Flags relevantes: `--config <yaml>`, `--workspace <dir>` (default
`./agent-skills-workspace`), `--baseline`, `--target <model>`, `--judge <model>`,
`--base-url <endpoint>` (default OpenAI), `--api-key-env <ENVVAR>`,
`--include`/`--exclude` (globs de carpetas de skill), `--concurrency <n>`,
`--layout iteration|flat`, `--strict`, `--log-format pretty|jsonl|silent`,
`--report`.

### Config YAML (`agent-skills-eval.yaml`)

```yaml
root: ./skills
workspace: ./agent-skills-workspace
baseline: true
target: gpt-4o-mini
judge: gpt-4o-mini
baseUrl: https://api.openai.com/v1
apiKeyEnv: OPENAI_API_KEY
concurrency: 4
strict: true
report:
  enabled: true
  title: Agent Skills Report
logging:
  format: pretty
targetParams: { temperature: 0 }
judgeParams: { temperature: 0 }
```

### Estructura de skill que **espera** la herramienta

```
my-skill/
├── SKILL.md                 # frontmatter: name (lowercase-hyphen), description (corta), license, compatibility
├── evals/
│   ├── evals.json           # definiciones de eval (ver abajo)
│   └── files/               # datos de prueba opcionales
├── references/
├── scripts/
└── assets/
```

`evals/evals.json`:

```json
{
  "skill_name": "my-skill",
  "evals": [
    {
      "id": "basic",
      "name": "basic behavior",
      "prompt": "Use the attached data to summarize revenue.",
      "files": ["evals/files/input.csv"],
      "expected_output": "The response identifies the highest revenue month.",
      "assertions": ["The output identifies the highest revenue month."]
    }
  ]
}
```

Si se omiten `assertions`, `expected_output` se auto-promueve a assertion de juez.

### Backends soportados

- OpenAI (default).
- Cualquier API OpenAI-compatible (Together, Groq, etc.) vía `--base-url`.
- Anthropic vía capa OpenAI-compat.
- Servidores Llama locales (Ollama, vLLM, llama.cpp).
- Custom: implementar la interfaz `Provider` (`name`, `model`, `async complete(prompt)`).

### SDK (TypeScript)

```typescript
import { OpenAICompatibleProvider, consoleReporter, evaluateSkills } from "agent-skills-eval";
const provider = new OpenAICompatibleProvider({ baseUrl: "...", apiKey: "...", model: "...", providerName: "openai" });
await evaluateSkills({ root: "./skills", workspace: "./agent-skills-workspace", baseline: true, concurrency: 4,
  workspaceLayout: "iteration", strict: true, target: { model: provider.model, provider }, judge: { ... }, onEvent: consoleReporter() });
```

### Output del workspace

```
iteration-1/
├── meta.json                # metadata del run
├── benchmark.json           # pass/fail por skill
├── eval-{name}/
│   ├── with_skill/          # output target + timing + grading del juez
│   └── without_skill/       # baseline + timing + grading
└── report/index.html
```

## 3. Entorno verificado (2026-05-11)

- **Node**: v22.19.0 · **npm/npx**: 9.2.0 → `npx agent-skills-eval` es viable.
- **Ollama**: corriendo, endpoint OpenAI-compat OK (`GET http://localhost:11434/v1/models` → 200).
  Modelos disponibles (selección):
  - Targets candidatos: `llama3.1:8b` (4.9GB), `qwen2.5:7b-instruct-q4_K_M` (4.7GB),
    `qwen2.5:14b-instruct` (9.0GB), `qwen3.6:27b` (17.4GB), `gemma3:27b` (17.4GB).
  - Jueces candidatos: `qwen3.6:27b`, `llama3.3:70b-instruct-q4_K_M` (42.5GB),
    `gpt-oss:120b-cloud` (modelo **cloud** de Ollama — implica llamadas a la nube de Ollama, no API key propia).
  - Embeddings: `nomic-embed-text` (no necesario aquí).
- **API keys**: NINGUNA detectada en env (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, Groq, Together, VRAIN — todas ausentes).
  → El backend **tiene que ser Ollama local** (vía `--base-url http://localhost:11434/v1`), salvo que Vicente aporte un endpoint que yo no veo.

> Nota de contexto APEX: la filosofía del proyecto es "sin API keys, Claude Code + MAX es el cerebro".
> Esta auditoría rompe esa regla **por necesidad de la herramienta** (necesita un endpoint OpenAI-compat con `complete(prompt)`).
> Ollama local lo satisface sin coste ni keys; `gpt-oss:120b-cloud` saldría por la cuenta de Ollama del usuario.

## 4. Fricciones / por qué no es plug-and-play

1. **APEX no tiene `evals/evals.json` en ninguna skill.** Las skills son solo
   `skills/<name>/SKILL.md` (markdown). Para correr `agent-skills-eval` hay que
   **redactar los `evals.json`** (prompt + assertions + ficheros opcionales) por
   cada skill que queramos probar. Eso lo escribiría yo (Claude) → es **mi
   interpretación de qué *debería* provocar cada skill**; conviene que Vicente
   los revise antes del run definitivo.
2. **Muchas skills de APEX no encajan en el modelo "one-shot prompt → respuesta".**
   El estándar de Anthropic asume skill = inyección de conocimiento que cambia
   una respuesta puntual. APEX tiene dos familias:
   - **Inyección de conocimiento/comportamiento** (sí medible así):
     `tdd`, `code-review`, `diagnose`, `improve-architecture`, `grill-with-docs`,
     `socratic`, `architect`, `security-audit`. (~8)
   - **Workflow / CLI agéntico** (ruido con este método): `flow-guardian`,
     `grader`, `apex-goal`, `devops`, `monitor`, `second-brain`,
     `portfolio-publisher`, `onboard-existing`, `reverse-engineer`, `iterate`,
     `tools-integration`, `prototype`, `design-system`, `design-research`,
     `brand-identity`, `brainstorming`. (~16) — se consumen dentro del bucle
     agéntico con MCP/hooks/multi-turno; un prompt aislado no captura su valor.
3. **El target real de APEX es Claude (Opus/Sonnet), no `gpt-4o-mini` ni un
   7B local.** Correr con Ollama mide *un* contraste real, pero es un proxy
   débil del consumidor real. Modelo target débil = más headroom = efecto del
   skill más visible; modelo fuerte = más cercano a Claude pero quizá ya lo
   hace bien sin skill.
4. **Algunas skills de APEX no llevan frontmatter YAML** (p.ej. `architect`,
   `code-review`, `iterate`, `monitor`, `second-brain`, `design-*`,
   `brand-identity`, `brainstorming`, `onboard-existing`, `reverse-engineer`,
   `portfolio-publisher`, `tools-integration` empiezan directo con `# Título`).
   La herramienta exige frontmatter (`name`, `description`) y que el nombre de
   carpeta coincida con `name`. → Para el harness habría que **copiar las skills
   a un workspace scratch y añadirles frontmatter mínimo** (no tocar las
   originales), o las skills sin frontmatter fallarán la validación (`--strict`).

## 5. Diseño de la auditoría (borrador, sujeto a §6)

1. Crear workspace scratch fuera del repo o en `docs/skill-eval-audit/workspace/`
   (gitignored). **No** correr la herramienta sobre `skills/` directamente.
2. Copiar ahí las skills a evaluar; normalizar frontmatter (`name` = carpeta,
   `description` ≤ límite, `license: MIT`, `compatibility: ...`).
3. Por skill, escribir `evals/evals.json` con 2-3 evals:
   - Un prompt realista que dispare el dominio del skill.
   - `assertions` concretas y verificables ("la salida hace X", "no hace Y",
     "menciona Z", "el plan tiene checkpoints", "no usa emojis", etc.).
   - `files/` cuando aplique (p.ej. un fragmento de código con un bug para
     `diagnose`/`code-review`).
4. `agent-skills-eval.yaml`:
   - `baseUrl: http://localhost:11434/v1`, `apiKeyEnv: OLLAMA_API_KEY` (Ollama
     ignora la key pero la herramienta puede exigir la env var → exportar
     `OLLAMA_API_KEY=ollama`).
   - `target`: (decisión §6) — p.ej. `qwen2.5:14b-instruct`.
   - `judge`: (decisión §6) — p.ej. `gpt-oss:120b-cloud` o `qwen3.6:27b`.
   - `baseline: true`, `strict: true`, `report.enabled: true`, `concurrency: 2-4`
     (ojo: Ollama serializa; concurrency alta no ayuda y puede OOM).
   - `targetParams.temperature: 0`, `judgeParams.temperature: 0`.
5. Correr (probablemente en background; 8 skills × ~3 evals × 2 runs + juez
   ≈ 50-100 llamadas LLM locales; las 24 ≈ 250-350).
6. Abrir `iteration-1/report/index.html` + parsear `benchmark.json`.
7. **Informe de hallazgos** en `docs/skill-eval-audit/RESULTS.md`:
   - Por skill: ¿`with_skill` > `without_skill`? ¿por cuánto? ¿en qué assertions?
   - Skills que NO mueven la aguja → candidatas a reescritura o borrado.
   - Caveats de metodología (proxy de modelo, one-shot vs agéntico, evals
     escritos por Claude).
   - Veredicto agregado: ¿los SKILL.md de APEX "sirven de algo" medible?

## 6. Preguntas abiertas para Vicente (RESPONDER AL RETOMAR)

1. **Alcance de skills**:
   - (a) Subset ~8 de inyección de conocimiento [recomendado: resultados
     interpretables, ~1 sesión]. Las otras se reportan como "no medibles con
     este harness" con justificación.
   - (b) Las 24, exhaustivo [más cobertura pero ~16 dan señal baja/nula por
     construcción; el informe separa trigo de paja; más lento].
   - (c) Subset ~8 ahora + extender después con un harness adaptado para las CLI.
2. **¿Vicente tiene algún endpoint OpenAI-compat que yo no detecto** (VRAIN,
   OpenRouter, Groq, etc.)? Si no, backend = Ollama local, fijo.
3. **Modelo target** (agente bajo test): `llama3.1:8b` (más headroom) /
   `qwen2.5:14b-instruct` (medio, recomendado) / `qwen3.6:27b` (cercano a Claude,
   menos headroom).
4. **Modelo juez**: `gpt-oss:120b-cloud` (cloud Ollama, más fiable, va por su
   cuenta) / `qwen3.6:27b` local / `llama3.3:70b` local (lento).
5. **¿Qué le preocupa más del resultado?**: ¿probar que las skills buenas
   funcionan? ¿cazar skills que no aportan nada (candidatas a borrar)? ¿validar
   la metodología del repo en sí? — afecta a cómo escribo las assertions.
6. **¿Quiere revisar los `evals/evals.json` antes del run definitivo**, o tiro
   con mi criterio y los enseño en el informe?
7. **Presupuesto de tiempo/coste**: ¿OK quemar 30-90 min de Ollama local? ¿OK
   llamadas a la nube de Ollama si el juez es `gpt-oss:120b-cloud`?

## 7. Checklist de ejecución (cuando se decidan las §6)

- [ ] `npx agent-skills-eval --help` para confirmar versión y flags reales.
- [ ] Leer `examples/basic-skill/` y `examples/agent-skills-eval.yaml` del repo
      (clonar a `/tmp/agent-skills-eval` o `npm view`) para fijar el schema exacto
      de `evals.json` (puede haber campos no documentados en el README).
- [ ] Crear `docs/skill-eval-audit/workspace/skills/<skill>/` por cada skill
      elegida: `SKILL.md` (con frontmatter normalizado) + `evals/evals.json`
      (+ `evals/files/` si aplica).
- [ ] Añadir `docs/skill-eval-audit/workspace/` a `.gitignore`.
- [ ] Crear `docs/skill-eval-audit/agent-skills-eval.yaml`.
- [ ] `export OLLAMA_API_KEY=ollama` (placeholder; Ollama lo ignora).
- [ ] Correr (background): `npx agent-skills-eval --config docs/skill-eval-audit/agent-skills-eval.yaml --report`.
- [ ] Revisar `iteration-1/report/index.html` + `benchmark.json` + cada
      `eval-*/with_skill/` vs `without_skill/`.
- [ ] Escribir `docs/skill-eval-audit/RESULTS.md` con hallazgos + caveats + veredicto.
- [ ] (Opcional) Si los resultados son útiles, abrir issue/sprint para
      institucionalizar evals por skill en APEX (cada skill nueva ⇒ su `evals.json`).

## 8. Notas sueltas

- `agent-skills-eval` es **Node/TS** (`npx`), no Python. No requiere instalar
  nada global si se usa `npx`. (Distinto del caso bug-hunter, donde la
  preferencia era portar a Python; aquí Vicente pidió explícitamente usar este
  repo tal cual.)
- Ollama OpenAI-compat: `base_url = http://localhost:11434/v1`, cualquier string
  como API key. Modelos cloud (`*-cloud`) requieren cuenta Ollama logueada
  (`ollama signin`) — verificar antes de elegir `gpt-oss:120b-cloud` como juez.
- El repo dice "fully implements agentskills.io spec" — vale la pena mirar si la
  spec define un formato de `evals.json` más rico (rúbricas, pesos) que el README
  resume.
