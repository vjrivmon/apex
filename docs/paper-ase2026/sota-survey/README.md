# Barrido estado del arte — APEX paper (ASE 2026 Tools track)

Investigación cerrada el 11 jul 2026. Fundamento empírico (Consensus) + competidores
directos (workflow multi-agente 31 agentes) + verificación de fuentes + deep-read con citas.
**18/18 fuentes verificadas como reales. Cero alucinaciones.**

## Veredicto en 3 líneas

1. **La pierna (b) [gates deterministas pre-LLM] NO es novedad exclusiva** — Rel(AI)Build y
   OpenCastle la hacen (cita textual: "enforced prior to LLM invocation... Claude Code PreToolUse").
2. **La novedad es la CONJUNCIÓN**: las intersecciones **(a)∩(b)∩(c)** y **(c)∩(d)** están
   genuinamente **vacías** en todos los rivales. APEX es el único que cierra un bucle de
   auto-mejora *encima de* fases gateadas Y transfiere lecciones entre proyectos.
3. **Somete pronto** — Rel(AI)Build (jun 2026) reproduce la pierna (a) con un mes de antigüedad.
   El campo "harness engineering" se pobló entero en H1 2026.

## Documentos

| Doc | Contenido |
|---|---|
| `00-VERIFICATION.md` | 18/18 fuentes reales; títulos+autores exactos para references.bib |
| `01-consensus-foundation.md` | Fundamento empírico Q1 (CSVs Consensus): gates, TDD, checklists, ADRs + contraevidencia |
| `02-consensus-deepsearch.md` | Deep Search reports: LLM-as-judge (blindaje del grader), RAG, security checklists |
| `03-competitors-workflow.md` | Competidores por eje + tabla comparativa + frase de novedad reescrita (§1) |
| `04-deepread-evidence.md` | Tabla comparativa respaldada con cita verbatim de los 4 refutadores (texto completo) |

## Trabajo pendiente (sesión nueva)

1. **Reescribir `\section{Related work}`** en `../main.tex` con la frase de novedad pivotada
   (ver `03-...md` §1 y `04-...md` "Recommended framing"). Conceder (a) y (c) como concurrent
   art; anclar en la conjunción + intersecciones vacías.
2. **Poblar `../references.bib`**: +7 fundamento Consensus (Fagan, Harter, Santos-TDD-meta,
   Nagappan, Borchard, de-Souza, Zheng-LLMjudge, Wang-LLMjudge-SE) + competidores verificados
   (Rel(AI)Build 2606.26924, ProjectMem 2606.12329, RHO 2606.05922, Meta-Harness 2603.28052,
   MetaGPT 2308.00352, ChatDev 2307.07924, AgentSpec 2503.18666, Code-as-Agent-Harness
   2605.18747, SWE-Context-Bench 2602.08316).
3. **Anticipar en Threats-to-Validity**: SWE Context Bench (2602.08316) es el yardstick de
   reuse cross-project que los reviewers esperarán.
4. **Sanity-check manual** (de `04-...md` Caveats): RHO (e)=partial, OpenCastle (a)/(c)=partial
   son judgment calls a defender con una frase.
