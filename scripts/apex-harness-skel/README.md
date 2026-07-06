# APEX — a self-improving harness for LLM coding agents

APEX is a **harness** that gives an LLM coding agent (it is built on
[Claude Code](https://docs.anthropic.com/en/docs/claude-code)) a persistent,
self-correcting cognitive substrate so it does not lose the thread over long,
multi-project software work. It layers entirely on the agent's own extension
points — tool servers (MCP), lifecycle hooks, declarative skills, sub-agents —
and adds three things:

1. **A phase-gated software lifecycle** — a `/apex` command that runs 14 phases
   (0 *Socratic intake* → 14 *maintenance*, with a security gate at 10.5) whose
   phase **transitions are blocked by a `PreToolUse` hook** that runs deterministic
   checks (git initialised? tests passing? OS matches the stack's assumptions? no
   emoji in user-facing strings? integration points resolve to real code, not
   mocks?) *before* any LLM judgement is consulted.
2. **A context substrate** — a per-project SQLite database (`.apex/context.db`,
   FTS5) with temporal facts (`valid_from`/`invalid_from`, Graphiti-style),
   a bidirectional error memory (`recurrence_count` + links to the decision that
   should prevent the error), a Markdown wiki, and progressive disclosure
   (compact ≈200 tokens / timeline ≈800 / full ≈2000) — plus a **cross-project
   hub** that re-injects past lessons at the start of every new session in any
   APEX project.
3. **A self-improvement loop** — an outcome-based **grader**, an **advisor**
   sub-agent under a strict token/rate budget, a host-introspective
   **apex-doctor**, and a **skill-forge** that mines repeated patterns into
   proposed new skills — all of which propose changes back to the harness itself.

It also installs a **virtual office**: five role sub-agents (architect,
implementer, reviewer, QA, devops) mapped to phases and dispatched via the agent's
own `Task` mechanism.

> The full design, the evidence of utility, and the related work are in the paper:
> [`docs/paper-ase2026/main.pdf`](docs/paper-ase2026/main.pdf) — *"APEX: A
> Self-Improving Harness for LLM Coding Agents Across the Software Lifecycle"*
> (under submission, ASE 2026 Tools & Datasets track).

```
            /apex  — 14-phase SDLC (0 Socratic … 14 maintenance), gate 10.5 = security
                                   │
            LLM coding agent  (model loop)  +  MCP tools  +  hooks  +  skills  +  sub-agents
                                   │
            PreToolUse "phase-gate" hook:  deterministic checks → grader → allow / block
                                   │  ▲
                                   ▼  │ reads / writes
            Context substrate:  per-project context.db  +  cross-project hub
            (temporal facts, error memory, FTS5 wiki, components; hub re-injects at SessionStart)
                                   │
            Self-improvement loop:  grader → advisor sub-agent (budgeted)
                                    → apex-doctor → skill-forge       ──"proposes changes"──┐
                                   │                                                        │
            Virtual office:  5 role sub-agents (architect, implementer, reviewer, QA, devops) ◄┘
```

## What's in here

| Path | What |
|---|---|
| `lib/` | The harness itself — 32 Python modules: context DB & hybrid retrieval, grader, goal loop, advisor + reasoning traces + skill-handoff, apex-doctor, skill-forge, library ingest, browser trace (CDP), DESIGN.md scaffolder, competitor research, reverse-engineering, the 5-role registry, the prototype (Textual TUI) scaffolder, security gate, DevOps scaffolder, wiki scaffold, ingest/lint/synthesis. |
| `mcp/apex_server.py` | The MCP server exposing **53 tool endpoints** (`apex_init_project`, `apex_get_context`, `apex_set_phase`, `apex_grader_evaluate`, `apex_advisor_review`, `apex_doctor_run`, `apex_skill_forge_scan`, …). |
| `skills/` | **24 skills** (`SKILL.md` each) — the development procedures: `socratic`, `architect`, `flow-guardian`, `iterate`, `tdd`, `diagnose`, `improve-architecture`, `grill-with-docs`, `code-review`, `security-audit`, `design-system`, `design-research`, `brand-identity`, `grader`, `apex-goal`, `prototype`, `devops`, `monitor`, `second-brain`, `brainstorming`, `portfolio-publisher`, `onboard-existing`, `reverse-engineer`, `tools-integration`. |
| `commands/` | The `/apex`, `/apex-goal`, `/apex-reverse` slash commands and the 14 phase playbooks (`commands/phases/00-socratic.md` … `14-maintenance.md`, plus `10.5-agentarmor-gate.md`) and the rules files. |
| `.claude/hooks/` | **11 hooks** — `session-start.py` (cross-project lesson injection), `phase-gate.py` (PreToolUse gate), `context-watch.py`, `post-tool-archive.py`, `skill-forge-watch.py`, `end-of-day-doctor.py`, `advisor-trigger.py`, `advice-injector.py`, `trace-prompt.py`, `advisor-outcome-watch.py`, `weekly-design-lint.py`. |
| `.claude/settings.json` | Reference wiring of the hooks (uses `$CLAUDE_PROJECT_DIR`). |
| `templates/` | Scaffolding templates: `apex-security/` (8-layer agent-security checklists, L1–L8), `docker/` (Dockerfile multi-stage, compose, GitHub Actions ci/deploy/release), `monitor/` (Prometheus + Grafana + Loki + alerts). |
| `tests/` | **620 tests** (pytest) covering the context schema & retrieval, grader & goal loop, hand-off & token-budget, the doctor's analysers, the skill-forge's detectors, the role registry, the prototype scaffolder, the advisor, browser trace, DESIGN.md, research, library ingest, … |
| `scripts/paper_metrics.py` | Reproduces the usage metrics reported in the paper. |
| `docs/paper-ase2026/` | The paper (LaTeX source + PDF), its metrics, video storyboard, and submission checklist. |

## Requirements & honest caveats — read this first

- **Running an agentic session end to end requires [Claude Code](https://docs.anthropic.com/en/docs/claude-code)** (the harness is built on its MCP/hooks/skills/sub-agents surface) **and its paid subscription** (the agent's own model is the only LLM APEX uses; the advisor sub-agent runs on Opus, also under that subscription). The design is generic — it uses only primitives a modern coding agent exposes — but this implementation targets Claude Code.
- **The harness code and the 620-test suite are fully standalone.** You can clone this repo and run the tests with no Claude Code, no API keys, no network (a couple of integration tests launch a local Chrome / HTTP server; they skip cleanly if unavailable).
- **Personal conventions baked in.** This harness grew as one developer's daily driver, so: (a) some prose and some skill text is in **Spanish** (technical terms in English); (b) several skills enforce that developer's house rules (no emoji in UI; tildes in Spanish); (c) the default project layout is `~/RoadToDevOps/<project>/` and the cross-project hub defaults to `~/RoadToDevOps/apex-hub/data/hub.db` (the hub itself is a separate small dashboard project, not in this repo) — these are defaults, overridable, but you'll see them in the code; (d) the `portfolio-publisher` skill / `lib/portfolio_publish.py` target a specific personal website's content schema. None of this is load-bearing for the core; it's documented so you're not surprised. PRs to generalise any of it are welcome.

## Quick start

### 1. Verify the harness (no Claude Code needed)

```bash
git clone https://github.com/vjrivmon/apex-harness
cd apex-harness
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest          # 620 passed   (lib/ is on the path via pyproject's pytest config)
```

### 2. Wire it into Claude Code

```bash
# Register the MCP server (adjust the path):
claude mcp add apex -- "$(pwd)/.venv/bin/python3" "$(pwd)/mcp/apex_server.py"

# Install the skills and the role sub-agents into your Claude Code config:
cp -r skills/*            ~/.claude/skills/
# (the 5 role sub-agents are written by the `apex_install_roles` MCP tool —
#  call it once from inside Claude Code, or copy them from skills/ if present)

# Use the hook wiring from .claude/settings.json as a starting point for your
# project's .claude/settings.json (it expects a `.venv/bin/python3` in the
# project and the hooks under `.claude/hooks/`).
```

### 3. Use it

In a project directory, inside Claude Code:

```
/apex
```

On a fresh idea APEX runs the Socratic intake, then proposes an architecture and a
checkpointed spec; phase 4 forces an edge-case list before any code; phases 5–7
implement test-first (git initialised at the very first sub-step); phase 8 reviews
the integration; phase 9 enforces a coverage floor and Playwright E2E against the
**real** backend; phase 10 + gate 10.5 do the security pass and block deployment
until clean; phases 11–14 ship and maintain it. On an **existing** codebase, run
`/apex-reverse` first — it scans the repo and back-fills the substrate before the
lifecycle resumes.

## Contributing

APEX is MIT-licensed and open to contributions — see [`CONTRIBUTING.md`](CONTRIBUTING.md).
Good first areas: generalising the personal-convention defaults noted above;
porting the harness to other coding agents that expose tool servers + hooks;
new phase playbooks; new skills; widening test coverage of the self-improvement loop.

## Citing APEX

If you use APEX in academic work, please cite the paper — see [`CITATION.cff`](CITATION.cff).
A Zenodo DOI for the archived snapshot will be added on the first tagged release.

## License

[MIT](LICENSE) © 2026 Vicente Rivas Monferrer and the APEX contributors.
