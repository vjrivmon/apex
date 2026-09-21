# Deep-read con citas textuales de los 4 refutadores (11 jul 2026)

> Los 4 vecinos mas peligrosos leidos a TEXTO COMPLETO (could_fetch_full_text=true en los 4).
> Cada celda de la tabla comparativa esta respaldada por cita verbatim del paper/repo rival.

This is a pure writing task from data already provided. No tools needed — all four neighbors have `could_fetch_full_text: true`, so the Caveats section will note that nothing was missing.

## Deep-read evidence for the comparison table

Legend: **a** = phase gates over an explicit lifecycle · **b** = deterministic pre-LLM blocking · **c** = outcome-driven self-improvement loop · **d** = cross-project memory transfer · **e** = runs on an unmodified agent.

| System | a (phase gates) | b (det. blocking) | c (self-improve) | d (cross-project) | e (unmodified agent) |
|---|---|---|---|---|---|
| **APEX** | yes | yes | yes | yes | yes |
| Rel(AI)Build | yes | yes | partial | no | yes |
| ProjectMem | no | partial | no | yes | yes |
| RHO | no | partial | yes | no | partial |
| OpenCastle | partial | yes | partial | no | yes |

### Verified verdicts

**Rel(AI)Build — the phase-gate + blocking threat.** It genuinely scores **yes on both (a) and (b)**: work is "structured into a bounded, sequential pipeline with mandatory human-in-the-loop (HITL) gates and a hard 3-iteration cap," and blocking is real and pre-LLM — "a deterministic pre-execution guardrail system enforces tier-based permissions... enforced prior to LLM invocation... deployed as IDE runtime hooks (Claude Code PreToolUse, Cursor beforeShellExecution)." But (c) is only **partial**: its drift detection is self-described as "a detection mechanism, not a validated behavioural predictor," and (d) is a **no** — it explicitly laments that multi-tool orgs "must re-author and re-maintain the same expertise multiple times." It never learns from outcomes.

**ProjectMem — the cross-project threat.** Clean **yes on (d)**: "A library-level lesson learned in one project can be surfaced in a later project that uses the same dependency, without cloud synchronization" — this is exactly APEX's pillar (d), delivered on an unmodified MCP agent ("a native MCP server (14 typed tools) that serves identical memory to multiple MCP-capable clients," → (e) yes). But its gate is **advisory only**, so (b) is **partial** by its own words — "The warning is advisory by default" — and it has neither lifecycle phase gates (a: no) nor an outcome loop (c: no, "reads only memory, never file contents, and is a deterministic lookup").

**RHO — the self-improvement threat.** The only neighbor with a real **yes on (c)**: "The agent then uses contrastive signals within the group to formulate instructions for optimizing the harness." That is a genuine outcome-driven loop — but it is *offline, self-supervised, and self-preferring*: its acceptance test "accept this update only if its score is strictly greater than zero (Sj>0)" is downstream of LLM self-preference, not a fail-closed deterministic pre-LLM gate (hence (b) partial, not yes). No lifecycle phase gates (a: no), no cross-project memory (d: no, evaluated "across three agent domains"), and (e) is only partial (pinned to "the Codex agent... GPT-5.5").

**OpenCastle — the full-stack lookalike.** Strong **yes on (b)**: it fail-closes on secrets before anything else — "Scan every diff **before** any other gate... `gitleaks detect` ... — fail on findings matching secrets rules." But its gates fire per *delegation*, not over a software lifecycle, so (a) is only **partial** (Gate 1/2/3 "Runs When: Every delegation"). Its improvement loop is **partial** — a failure-clustering threshold ("3+ different convoys, OR same agent 2+ failures...") that produces *human-applied* refinement proposals, and its "self-improving" claim ("Agents capture lessons and graduate them into permanent instructions") is confined project-locally — all memory lives in `.opencastle/AGENT-EXPERTISE.md`, so (d) is a **no**.

## Novelty after deep-read

**Pillar (b) does not survive as APEX's exclusive — three neighbors do deterministic pre-LLM blocking.** Rel(AI)Build ("enforced prior to LLM invocation... Claude Code PreToolUse") and OpenCastle ("Scan every diff **before** any other gate... fail on findings") are both clean **yes**; ProjectMem and RHO are partial. So (b) alone is *not* a defensible novelty claim and the paper should stop framing it as one.

**The novelty is the full conjunction, and specifically the intersection (a)∩(b)∩(c)∩(d) — which remains empty for every neighbor.** No neighbor is yes on more than three of the five columns, and critically:

- **(a)∩(b) is non-empty but rare:** only Rel(AI)Build pairs lifecycle phase gates *with* deterministic blocking (OpenCastle blocks but only partial on lifecycle phases). So even the phase-gate + blocking combination is nearly exclusive.
- **(a)∩(b)∩(c) is empty:** Rel(AI)Build has (a)+(b) but only partial (c); RHO has (c) but no (a); OpenCastle has (b) but partial on both (a) and (c). No neighbor closes a real outcome loop *on top of* gated lifecycle phases with deterministic blocking.
- **(c)∩(d) is empty:** RHO self-improves but has no cross-project memory; ProjectMem has cross-project memory but no self-improvement loop. APEX is the only system that both learns from outcomes *and* carries those lessons across projects.

**Recommended framing:** drop the single-pillar novelty claim. APEX's defensible contribution is the *composition* — a fail-closed grader verdict that blocks lifecycle **phase** transitions (not just per-task delegations or supply-chain permissions), sitting on top of the outcome-clustering self-improvement loop (skill-forge / apex-doctor), with lessons and errors transferred across separate repos. The empty cells to cite as the wedge are **(a)∩(b)∩(c)** and **(c)∩(d)**.

## Caveats

All four neighbors were deep-read with `could_fetch_full_text: true`; no cells rest on abstract-only or unread text. **No manual re-reading is required** for this batch. Residual precision risks the author should still sanity-check by hand:

- **RHO (e) = partial** rests on its harness being pinned to "the Codex agent... GPT-5.5" — confirm whether RHO's method is agent-agnostic in principle (which would upgrade toward yes) or hard-bound to Codex (keeps it partial).
- **OpenCastle (a) = partial** and **(c) = partial** are both judgment calls: (a) because its gates run per-delegation rather than over named lifecycle phases, and (c) because clustering produces *human-applied* proposals rather than an autonomous loop. If a reviewer reads "every delegation" as a de-facto lifecycle, (a) could be contested upward — worth a defensive sentence in related work.
- **Rel(AI)Build (c) = partial** hinges on the authors' own hedge ("a detection mechanism, not a validated behavioural predictor"); this is their disclaimer, not our inference, so it is safe to quote directly against any reviewer who claims Rel(AI)Build self-improves.