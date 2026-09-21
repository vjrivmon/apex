# Verificación de fuentes del barrido (11 jul 2026)

> El informe del workflow (`03-competitors-workflow.md`) marcó 11 arXiv IDs de 2026 con ⚠
> "verificar existencia". SÍ se verificaron contra arXiv/web real. **Todos los verificados
> existen** — el campo se está poblando en tiempo real (H1 2026). No hubo alucinación de fuentes.

## Confirmados por fetch/search directo

| Paper | arXiv ID | Estado | Nota |
|---|---|---|---|
| Rel(AI)Build — A Deterministic Control Plane for LLM Coding Agents | 2606.26924 | ✅ REAL | Padmaraj Madatha. Phase state machine determinista, PreToolUse, agente sin modificar. **Refuta pierna (a).** |
| ProjectMem — Local-First Event-Sourced Memory & Judgment Layer | 2606.12329 | ✅ REAL | Malo & Qiu. Memoria cross-project MCP. **Vecino de pierna (c).** |
| RHO — Retrospective Harness Optimization | 2606.05922 | ✅ REAL | CityU HK + Microsoft Research Asia. Auto-mejora harness desde trayectorias, SWE-Bench Pro 59→78%. **Adyacente a pierna (b).** |
| Meta-Harness — End-to-End Optimization of Model Harnesses | 2603.28052 | ✅ REAL | Yoonho Lee et al. (Stanford IRIS/MIT/KRAFTON). Optimiza scaffolding sobre modelo fijo con Claude Code. |
| OpenCastle | github monkilabs/opencastle | ✅ REAL | Skills públicas `validation-gates` + `self-improvement`. Match casi full-stack, sin memoria cross-project. |

## Descubiertos en la verificación (el workflow NO los tenía) — revisar

| Paper | arXiv ID | Nota |
|---|---|---|
| Harness as an Asset: Enforcing Determinism via CAAF | 2604.17025 | Determinismo en harness. Revisar overlap con enforcement. |
| Building AI Coding Agents for the Terminal: Scaffolding, Harness, Context Engineering | 2603.05344 | Lecciones de harness/context. Posible must-cite de positioning. |
| Compiled AI: Deterministic Code Generation for LLM Workflow Automation | 2604.05150 | Determinismo en generación. Revisar. |
| Harnesses for Inference-Time Alignment over Execution Trajectories | 2605.21516 | Adyacente a RHO/Meta-Harness. |

## Los 7 ⚠ del informe — TODOS verificados como reales (títulos/autores exactos para la bib)

| Paper | arXiv | Título exacto | Autor(es) |
|---|---|---|---|
| Engram | 2606.09900 | Less Context, More Accuracy: A Bi-Temporal Memory Engine for LLM Agents Where a Lean Retrieved Context Beats the Full History | Liuyin Wang |
| TOKI | 2606.06240 | TOKI: A Bitemporal Operator Algebra for Contradiction Resolution in LLM-Agent Persistent Memory | Ziming Wang |
| TokenMizer | 2606.06337 | TokenMizer: Graph-Structured Session Memory for Long-Horizon LLM Context Management | Shweta Mishra |
| From Prompts to Contracts | 2607.08028 | From Prompts to Contracts: Harness Engineering for Auditable Enterprise LLM Agents | Joongho Ahn, Moonsoo Kim |
| TDD Governance | 2604.26615 | TDD Governance for Multi-Agent Code Generation via Prompt Engineering | Hasanli, Siddeeq, Khanal, Kotilainen, Mikkonen, Abrahamsson |
| Code as Agent Harness | 2605.18747 | Code as Agent Harness (survey) | Ning, Tieu, Fu et al. (42 autores) |
| SWE Context Bench | 2602.08316 | SWE Context Bench: A Benchmark for Context Learning in Coding | Zhu, Wu, Hu et al. |

**Resultado: 18/18 fuentes del barrido son reales. Cero alucinaciones.** El campo entero
("harness engineering") se pobló en H1 2026.

## Lección para el paper

No es "cuidado con las alucinaciones". Es: **el estado del arte de tu tesis se está
publicando ESTE semestre**. Rel(AI)Build (jun 2026) hace tu pierna (a) casi verbatim.
El paper debe (1) reconocer concurrencia explícita, (2) anclar novedad en la pierna (b) +
la integración tri-pilar, (3) someterse pronto — cada mes que pasa aparece un vecino nuevo.
