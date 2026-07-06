# CLAUDE.md — APEX

This repository **is** APEX: a self-improving harness for LLM coding agents. If you
are Claude Code working on it, you are working on your own substrate. Be careful.

## Where things are

- `lib/` — the harness modules (flat directory; not an installable package).
- `mcp/apex_server.py` — the MCP server (53 tools).
- `skills/` — 24 skills (`SKILL.md` each).
- `commands/` — the `/apex` command and the 14 phase playbooks (`commands/phases/`).
- `.claude/hooks/` — 11 lifecycle hooks; `.claude/settings.json` wires them.
- `templates/` — DevOps + security scaffolding templates.
- `tests/` — 620 tests. `docs/paper-ase2026/` — the paper describing all of this.

## Running tests

```bash
pip install -e ".[dev]"   # once
pytest                    # lib/ is on the path via pyproject's pytest config
```

Always run `pytest` before and after a change. It must stay green (620 passed).

## House rules (non-negotiable)

- **No emoji.** Anywhere. Code, comments, docs, commit messages, skill text.
- **Conventional commits** (`feat(...)`, `fix(...)`, `test(...)`, `docs(...)`, …).
- **Comments explain WHY, not WHAT.** Type hints on new Python. Keep deps minimal.
- Prose may be Spanish or English; technical terms in English; match the file.
- Hooks must be fast and must never hard-fail the agent — degrade to a stderr note.
- If you change a phase gate, a hook, or the grader, say so loudly — load-bearing.

## Personal-convention debt (PRs welcome)

Some defaults assume one developer's setup: project layout `~/RoadToDevOps/<project>/`,
hub DB at `~/RoadToDevOps/apex-hub/data/hub.db`, the `portfolio-publisher` skill
targets a specific website. These are overridable defaults, not core. Generalising
them is a good contribution. Do not add new hardcoded personal paths.
