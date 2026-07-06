# Screencast — APEX (ASE 2026 Tools & Datasets) — ≤ 5:00

**Hard rules from the CFP:** ≤ 5 minutes, uploaded to YouTube (set to *Unlisted*),
voice-over + on-screen annotations, the URL goes at the end of the HotCRP abstract.
Record at 1080p, system font, dark terminal theme. **No emojis on screen.** English
voice-over (the paper is in English; keep it consistent). A Spanish voice-over is
acceptable too if your English VO would slow you down — but pick one and be crisp.

Tooling: OBS Studio (or `wf-recorder` on Wayland) for capture; record VO live or
dub afterwards over the screen capture. Keep cursor movements slow and deliberate.

---

## Shot list (target timings — leave ~10 s of slack)

### 0:00 – 0:30 — The problem (talking over a title card + one terminal)
- **Screen:** a slide/title card: *"APEX — a self-improving harness for LLM coding
  agents"*, your name + VRAIN/UPV. Then cut to a terminal.
- **Say:** "LLM coding agents like Claude Code now run whole projects over days.
  But the harness around the model has no memory and no discipline: decisions get
  re-litigated, custom tools go unused, the same mistake reappears in the next
  project, phases get skipped, and integration phases get marked done against mock
  data. APEX is a harness that fixes that — it sits on top of the agent, using only
  its own extension points."

### 0:30 – 1:00 — What APEX is (architecture figure)
- **Screen:** show Figure 1 from the paper (export `main.pdf` page with the
  diagram, or a clean PNG of it).
- **Say:** "APEX adds three things on top of any agent that has tool servers,
  hooks, skills and sub-agents: a 14-phase software lifecycle whose transitions are
  gated by deterministic checks before any LLM judgement; a context store that's
  both per-project and cross-project; and a self-improvement loop that proposes
  changes back to the harness. It's open source, 620 tests, 53 tools, 24 skills,
  and it's been my working harness for about twenty real projects."

### 1:00 – 1:35 — SessionStart: cross-project memory in action
- **Screen:** open a real APEX project; show the session start banner where
  `session-start.py` injects the critical cross-project lessons (the SwiftUI/Linux
  one, "never emojis as icons", "no mock data in integration", "git init first").
- **Say:** "When I open any APEX project, this is the first thing the agent sees —
  the critical errors I made in *other* projects, pulled from the cross-project
  hub. The SwiftUI-on-Linux mistake from one project is now a guardrail in all of
  them. There are 24 projects feeding this hub: 322 decisions, 184 errors with
  recurrence tracking, 160 wiki pages."

### 1:35 – 2:25 — The phase gate refuses a premature transition
- **Screen:** run `/apex` (or just call the MCP tool) and try to jump to an
  implementation phase with no git repo / failing tests. Show the `phase-gate.py`
  hook **blocking** `apex_set_phase` with the actionable message. Then fix the
  precondition (e.g. `git init` + commit) and show the transition going through.
- **Say:** "Here I try to move into implementation. The PreToolUse hook intercepts
  it, runs deterministic checks — is git initialised? do the tests pass? is the OS
  what the stack assumed? any emojis in user-facing strings? — and refuses, with an
  actionable reason. Only after those pass does it consult the outcome-based
  grader. Deterministic checks first; the LLM judge only for what needs judgement."

### 2:25 – 3:10 — Context substrate + progressive disclosure
- **Screen:** call `apex_get_context` at compact / timeline / full depth; show the
  size difference. Show a `context.db` decision with `valid_from`/`invalid_from`
  (a superseded decision kept but marked stale), and an error row with
  `recurrence_count`. Briefly show a wiki page with front-matter + FTS5 search.
- **Say:** "The agent re-grounds itself at the cheapest sufficient depth — compact
  is about 200 tokens, full about 2000. Decisions and components are bi-temporal:
  superseded choices are retained but flagged, not deleted. Errors carry a
  recurrence count and link to the decision that should prevent them."

### 3:10 – 4:05 — Self-improvement loop
- **Screen:** show an advisor advice card surfacing (forgotten-tool or phase-drift),
  then `apex_doctor_run` producing proposals, then `.apex/skill-proposals/` with a
  drafted `SKILL.md`, and `apex_skill_forge_approve`. Show `pytest tests/` running
  green (620 passed) in a corner or as a quick cut.
- **Say:** "APEX critiques itself. The advisor — a budgeted Opus sub-agent — drops
  short advice cards: 'you have a tool for this', 'you've drifted off-phase'.
  apex-doctor runs analysers over the context store and writes deduplicated
  proposals. The skill forge watches for repeated patterns and drafts a new skill
  for me to approve. All of this is wired and unit-tested — 620 tests — though I'm
  honest in the paper that the optimiser layer has only just started running in the
  field."

### 4:05 – 4:35 — The virtual office (brief)
- **Screen:** `apex_recommend_role` for a phase → it suggests `apex-implementer`;
  show the agent dispatching it via `Task`.
- **Say:** "Each phase has a role sub-agent — architect, implementer, reviewer, QA,
  devops — with its own tool whitelist and an APEX-aligned prompt. They run under my
  own subscription, so the office costs nothing extra."

### 4:35 – 5:00 — Availability + close
- **Screen:** the GitHub repo page (`apex-harness`), the LICENSE, the test badge /
  `pytest` green; the Zenodo DOI page; a final card with the three links.
- **Say:** "APEX is MIT-licensed on GitHub, archived on Zenodo, 620 passing tests
  you can run standalone. It needs Claude Code and its subscription to run an agentic
  session end to end — that's a real reproducibility limit, and it's in the paper.
  Thanks for watching."

---

## Pre-record checklist
- [ ] A real APEX project ready with a populated `context.db` and a SessionStart
      banner that actually shows the cross-project lessons (use `vr-web` or
      `corporate-web` — they have the most decisions).
- [ ] A scratch project where you can deliberately trigger a phase-gate block
      (no git repo / failing test) and then fix it on camera.
- [ ] `pytest tests/` passing (620) — capture this fresh, don't reuse old footage.
- [ ] Terminal: large font (≥ 16pt), high contrast, no personal info in prompt.
- [ ] Figure 1 exported as PNG (`pdftoppm -png -r 200 main.pdf fig1` then crop, or
      screenshot the PDF page).
- [ ] Close Slack/email/notifications. Do-not-disturb on.
- [ ] Record a 20-second test clip first; check audio levels.
- [ ] After upload: set to **Unlisted**, copy the `https://youtu.be/...` link into
      `SUBMISSION-CHECKLIST.md` and the paper's Availability paragraph.
