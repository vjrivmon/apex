# Contributing to APEX

Thanks for considering a contribution. APEX is a personal harness opened up for
reuse; the bar is "does it make the harness more useful or more general without
breaking the 620-test suite".

## Setup

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest          # must be green before and after your change
```

`lib/` is a flat directory of modules (not an installable package); pytest finds
it via the `pythonpath = ["lib"]` setting in `pyproject.toml`. If you run a module
directly, do `PYTHONPATH=lib python3 ...`.

## Conventions

- **No emoji** anywhere — code, comments, docs, skill text, commit messages. Use
  words. (This is enforced by APEX's own grader, so emoji in user-facing strings
  will be flagged.)
- **Language.** Prose may be Spanish or English; technical terms stay in English.
  Match the surrounding file. New skills should have a bilingual `description:` in
  the front-matter to maximise trigger coverage.
- **Comments explain WHY, not WHAT.**
- **Conventional commits** (`feat(...)`, `fix(...)`, `docs(...)`, `refactor(...)`,
  `test(...)`, `chore(...)`).
- **Type hints** on new Python; keep modules dependency-light (stdlib + the few
  deps already in `pyproject.toml`).
- **TDD where it makes sense** — there is a `skills/tdd/` playbook describing the
  red-green-refactor loop the project follows.

## Anatomy

- **A skill** is `skills/<name>/SKILL.md` with YAML front-matter (`name`,
  `description` with trigger phrases). Optional supporting `.md` files alongside.
  No code — skills are read by Claude Code.
- **A hook** is a Python script in `.claude/hooks/` invoked by Claude Code at a
  lifecycle point (`SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse`).
  Hooks must be fast (wall-clock budgets are enforced inside them), must **never**
  hard-fail the agent (degrade to a stderr note), and read/write the project's
  `.apex/context.db`.
- **An MCP tool** is added in `mcp/apex_server.py`: declare it in the `list_tools`
  handler (name + JSON schema) and dispatch it in `call_tool`. Back it with a
  function in a `lib/` module and add tests.
- **A phase playbook** is `commands/phases/NN-name.md`, referenced from
  `commands/apex.md`.

## Pull requests

1. Branch from `main`.
2. Add/extend tests; `pytest` green.
3. One logical change per PR; describe the WHY.
4. If you touched a phase gate, a hook, or the grader, say so explicitly — those
   are load-bearing.

## Reporting issues

Open a GitHub issue. For anything that looks like a leaked secret or a path that
shouldn't be public, please email the maintainer privately first.
