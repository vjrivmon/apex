# ASE 2026 — Tools & Datasets Track — submission checklist (APEX)

> Track page: <https://conf.researchr.org/track/ase-2026/ase-2026-tools-and-data-sets>
> HotCRP: <https://ase26-tools-datasets.hotcrp.com>

## The deadline (do the math)
- **11 May 2026, AoE (UTC−12).** "Anywhere on Earth" = the deadline passes only when
  it is past 11 May *everywhere*. So the absolute cut-off is **12 May 2026, 11:59 UTC**
  → **12 May 2026, 13:59 in Spain (CEST)**. Treat noon Spain time on the 12th as the wall.
- Author notification: **17 June 2026**.

## Hard requirements (from the CFP)
- [ ] Paper: **≤ 4 pages**, everything included (text, references, figures). ACM
      Proceedings Template, `\documentclass[sigconf,review]{acmart}`. PDF. English.
      → our `main.tex` compiles to **exactly 4 pages** with the bibliography. Any
      content you add, trim something else.
- [ ] **Not double-blind** — author names + affiliations stay in. (Nothing to anonymise.)
- [ ] **Screencast video ≤ 5 min**, voice-over + annotations, uploaded to **YouTube**.
      → storyboard in `VIDEO-SCRIPT.md`. Set the video to *Unlisted*.
- [ ] **Code/dataset links** in the abstract (open source strongly encouraged).
      → repo `apex-harness` (see below) + Zenodo DOI.
- [ ] Abstract on HotCRP **must end with**: the video URL and the code/dataset link(s).
- [ ] Not previously published as a demo; not under review elsewhere simultaneously. ✔ (true)
- [ ] Datasets in a long-term archive (Zenodo). → mint a Zenodo DOI from the repo.

## Content the reviewers expect to see in the paper (CFP checklist) — status
- [x] Intended users & usage context — Intro + §"Using APEX"
- [x] The SE problem addressed — Intro
- [x] Artifact description (tool, repo, test suite, MCP server, skills, hooks) — §3, §"Availability"
- [x] Usage methodology & requirements — §"Using APEX", §"Limitations" (needs Claude Code + subscription)
- [x] Evidence of utility & quality — §"Evidence" (620 tests, ~20 projects, hub totals, caught-error examples)
- [x] Availability, reusability, licensing, reproducibility — §"Limitations and availability" (MIT, Zenodo, `pytest`)

## 0. Co-author consent (DO THIS FIRST — today)
- [ ] Vicente Rivas Monferrer — that's you.
- [ ] Juan Miguel Alberola — ping him; you already collaborate. Confirm he's OK being on it.
- [ ] Víctor Sánchez-Anguix — confirm.
- [ ] Vicente Julián — confirm (catedrático; do not submit without his explicit OK).
- [ ] Get their **correct UPV emails** and fix the `TODO@upv.es` / `verify` placeholders in `main.tex`.
- [ ] Confirm any **grant/project numbers** to put in `\begin{acks}`.
- If anyone can't confirm in time → remove them from the author block before submitting; add for camera-ready.

## 1. The paper (`main.tex`)
- [x] Draft compiles to 4 pages (latexmk, acmart present locally).
- [ ] Decide the **title** (current: *"APEX: A Self-Improving Harness for LLM Coding Agents Across the Software Lifecycle"*; two alternates commented in `main.tex`).
- [ ] Fill real emails, grant numbers.
- [ ] Replace the three `XXXX` placeholders in §Availability with the real GitHub URL, Zenodo DOI, YouTube URL (do this **last**, once those exist).
- [ ] Read it once more for the 4-page limit after edits. If tight: the Related-Work
      paragraph on autonomous-agent frameworks is the first thing to cut.
- [ ] (Optional) export Figure 1 as a standalone PDF into `fig/` and `\includegraphics`
      it instead of the inline TikZ if you tweak it in a vector editor — not required.
- [ ] Generate the final PDF: `cd docs/paper-ase2026 && latexmk -pdf main.tex`.
- Note on `printacmref`: we keep it `false` for the review PDF (saves ~half a column;
  standard for review versions). The acmart warning about it is expected and harmless.

## 2. Open-source artifact — the `apex-harness` repo
The reviewers will open the repo. We ship a **clean subset** of the current `apex`
repo (no `backend/` legacy, no root-level screenshots / audit dumps). Plan:

- [ ] Create `~/RoadToDevOps/apex-harness/` containing only:
      `lib/  mcp/  skills/  commands/  .claude/hooks/  .claude/settings.json (sanitised)
       tests/  templates/  docs/  scripts/paper_metrics.py  pyproject.toml`
- [ ] Add **LICENSE** (MIT — confirm; the Matt-Pocock-derived skills are MIT, so MIT is consistent).
- [ ] Add **README.md**: what APEX is, the architecture figure, install steps
      (register MCP server + hooks with Claude Code), `pytest tests/` to verify,
      link to the paper, the "needs Claude Code + subscription" caveat up front.
- [ ] Add **CONTRIBUTING.md** (short) and **CITATION.cff** (point at the ASE paper / Zenodo DOI).
- [ ] `pyproject.toml` so `pip install -e .` + `pytest` works for a reviewer.
- [ ] Strip anything machine-specific: absolute paths, the `.env`, any tokens, the
      `~/RoadToDevOps/...` assumptions in hooks (make them relative to `$CLAUDE_PROJECT_DIR`).
- [ ] `git init`, conventional first commit, push to **public** `github.com/vjrivmon/apex-harness`.
- [ ] Verify a fresh clone: `pip install -e . && PYTHONPATH=lib pytest tests/` → 620 green.
- → I (Claude) can generate this skeleton + the LICENSE/README/CONTRIBUTING/pyproject and a
  `make-public.sh` that builds it from the current repo; you review and push. Say the word.

## 3. Zenodo DOI
- [ ] Connect Zenodo to GitHub, enable archiving for `apex-harness`.
- [ ] Cut a `v0.1.0` GitHub release → Zenodo mints a DOI automatically.
- [ ] Put the DOI in `main.tex` (§Availability) and `CITATION.cff`.
- (If GitHub↔Zenodo is fiddly: manual upload of a release `.zip` to Zenodo also works.)

## 4. The video
- [ ] Record per `VIDEO-SCRIPT.md` (≤ 5:00). Capture `pytest` green fresh.
- [ ] Upload to YouTube, set **Unlisted**.
- [ ] Put the `https://youtu.be/...` URL in the paper and in the HotCRP abstract.

## 5. HotCRP submission (do ~6 h before the wall, not at the last minute)
- [ ] Create an account on <https://ase26-tools-datasets.hotcrp.com>.
- [ ] New submission. Title, authors (all 4, with affiliations + emails), topics/CCS.
- [ ] Abstract: the paper abstract, then **append at the end**: `Video: <youtube url>`
      and `Code & dataset: <github url> ; archived: <zenodo doi>`.
- [ ] Upload `main.pdf`.
- [ ] Double-check page count (≤ 4) in the uploaded PDF.
- [ ] Submit. Then re-open the submission and confirm everything saved.
- [ ] Screenshot the confirmation.

## Status snapshot (2026-05-10)
- [x] CFP read & summarised; deadline math done.
- [x] Real metrics extracted (`scripts/paper_metrics.py`, `METRICS.md`): 620 tests,
      53 MCP tools, 24 skills, 11 hooks, ~12.3k LOC; 24 projects / 20 active;
      hub: 322 decisions, 184 errors, 279 components, 160 wiki pages.
- [x] References verified on arXiv (Zhou 2604.08224, Liu 2604.14228, Fang 2508.07407,
      Banerjee/SEVerA 2603.25111, Nechepurenko 2605.03310). `references.bib` written.
- [x] Paper draft `main.tex` → compiles to 4 pages.
- [x] Video storyboard `VIDEO-SCRIPT.md`.
- [ ] Co-author consent + real emails.  ← **your move, today**
- [ ] `apex-harness` public repo + LICENSE/README/etc.  ← I can start this next.
- [ ] Zenodo DOI.
- [ ] Record + upload video.
- [ ] Fill placeholders in `main.tex`, regenerate PDF.
- [ ] Submit on HotCRP before 12 May ~14:00 CEST.

## If it doesn't come together
Plan B: withdraw before the deadline (or just don't submit) and target **AIware @ FSE
2026** or **LLM4Code @ ICSE 2027** (workshops, 4–8 pp, same audience, more runway).
The arXiv preprint plan stands either way — post it once the repo is public.
