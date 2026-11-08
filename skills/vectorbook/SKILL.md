---
name: vectorbook
description: Re-set pages of a scanned book or paper (DjVu or PDF scan) as modern, exact vector PDF pages - modern typography and notation, traced figures with typeset labels, the same words and mathematics. Orchestrates a local Pi model and OpenRouter workers at a target of $0.05 per page. Use for any book, paper or page range to vectorise or modernise.
---

# vectorbook

Re-set pages of a scanned book as modern vector pages. Change the design. Never change the
words or the mathematics. Target cost: **$0.05 per page**, measured while you work.

## Orchestration (how you work)

You are the orchestrator. You plan, coordinate, give each worker the needed context, run tools
and checks, integrate results and verify the output. Workers do the substantive work.

- Do not do substantive transcription, formula, figure, layout, design, code or writing work
  yourself. Assign it to a worker: the local model (cheapest; through a direct call, Pi or
  mini-swe-agent, see the routing table below) or an OpenRouter model. If a
  result needs correction, send the correction to a worker. You may run tools and checks,
  inspect results, and report defects to workers. Small mechanical repairs of tool plumbing are
  allowed; record each one in `work/log.md` as orchestrator work.
- Before substantive work, write the plan in `work/log.md`: subtasks, assigned worker or model,
  expected outputs, expected cost per page.
- Select each model by capability, quality, availability and cost. Check the current catalog
  and prices; do not assume them. Prefer a modestly priced model that meets the quality need.
  Use a vision model for visual inspection. See references/models-and-lessons.md before you
  choose: it lists models that wasted money and time.
- Run every OpenRouter call through `scripts/worker.py` and every local-model call through
  `scripts/transcribe_local.py` (direct or Pi) or `scripts/mini_task.py` (mini-swe-agent). They
  log usage for the cost ledger.
- Route each task to the worker that fits its shape (references/local-workers.md):

  | Task shape | Worker |
  |---|---|
  | single shot, prompt + images -> structured answer (transcribe, fix from issue list) | local **direct call** |
  | exact minimal LaTeX edits in place, image-attached agent tasks | local **Pi** |
  | iterative tool loops (build -> log -> fix -> rebuild, run checks and act) | local **mini-swe-agent** |
  | counting, global replacement, contract notation the local model resists | **gpt-6.1-terra** or a script |
  | page review, label reading, suspected-error checks | **gemini-4-argon** (remote) |
  | long code, design decisions from data | **gpt-6.1-sol** (remote) |
- Record results and failures. On a failure, try a suitable alternative and change something
  (model, scope or method); never repeat an identical failed call. Report incomplete work.
  Never present local work or an unexecuted assignment as a worker result.
- API key: read it from the project file `api-key` (or `OPENROUTER_API_KEY`). Send it only to
  OpenRouter. Never print, log or save it.
- Keep your own turns per page near zero: the orchestrator's tokens are the largest cost of a
  pilot. Build and validate the per-page pipeline on a sample, then let it run.
- Do not wait on a silent process. Check GPU activity or the run log; a local call takes
  10–120 s.

## Project (no task folders)

One project folder per book or paper. Work accumulates there; do not create task_NNN folders.
Run scripts with the system Python launcher: `py <skill>/scripts/<script>.py` (`<skill>` = this
skill's folder). Every script finds the project root through `vectorbook.json`.

```
<project>/vectorbook.json   source, title, style, contract, local model, baseline
<project>/api-key           OpenRouter key (never copied elsewhere)
<project>/design/           book-style.sty and contract.md (book-specific; edit here only)
<project>/pages/pNNN/       src300.png, ocr.txt, meta.json, body.tex, figK.tex, page.pdf, checks.json
<project>/figs/pNNN-K/      tracer work for figure K of page NNN
<project>/work/             log.md, costs.jsonl, local-runs.jsonl, orchestrator.jsonl, calls/, mini/
<project>/output/           merged PDFs
```

Start: `py <skill>/scripts/init_project.py --source BOOK.djvu --title "Title"`. Then fill the
book's notation in `design/contract.md` and the style.

## Procedure per page (NNN = source page index, three digits)

1. `py scripts/extract_page.py --page N`. Look at `src300.png`; confirm the printed number.
2. `py scripts/find_figures.py pages/pNNN`. Write short page notes: continuation, figures and
   their captions, typeset diagrams, tricky symbols, scanner noise.
3. Transcribe with the local model (direct call):
   `py scripts/transcribe_local.py pages/pNNN --printed P --notes "..."` (`--via pi` as fallback).
4. Figures (references/figures.md): segment, read labels (gemini-4-argon), trace, check
   `trace.json`, copy `fig.tex` to `pages/pNNN/figK.tex`.
5. Build: `py scripts/build_page.py pages/pNNN`. All hard checks must pass. If the build fails,
   give the error to mini-swe-agent: `py scripts/mini_task.py pages/pNNN --task-file TASK.txt`
   (it rebuilds, keeps backups, and restores them if the page gets worse).
6. Review (gemini-4-argon, prompts/review-page.txt, images src300 + render300). Verify each claim
   against the source. Write the real defects to an issues file.
7. Fix: local direct call (`transcribe_local.py --fix ISSUES`) for targeted edits; Pi when the
   edits must be minimal in place; gpt-6.1-terra for counting, global replacement and contract
   notation. Integrate by diff: only intended lines change. Script-check structured content.
8. Rebuild, review again, fix only real defects.
9. Errata (only for category D findings of the review): verify each suspected error of the
   author independently (a strong model with prompts/verify-error.txt, or a computer-algebra
   check). For confirmed errors: `py scripts/errata.py snapshot pages/pNNN`, add the markup
   (prompts/add-errata.txt), then `py scripts/errata.py check pages/pNNN` must say OK.
10. `py scripts/costs.py`. Act when a page is over the baseline.

## Book level

Before production (once per book):
1. Run the page-size optimisation on about 10 characteristic pages
   (`py scripts/pagesize.py ...`, references/design-and-layout.md). The design worker fixes the
   page size, measure and lines for the whole book in the project style (prompts/design-style.txt).

After all pages pass (final steps):
2. Vertical layout: `py scripts/vertical.py`. One rule for all pages: full pages share free space
   among their gaps in a balanced, consistent way; short pages stay ragged as in the source.
   Read work/vertical-report.json and act on flagged pages.
3. Final output: `py scripts/make_book.py NAME`. It writes the two required results:
   `output/NAME.tex` (one self-contained TeX document with all pages: style embedded, bodies and
   figures inline; binary resources such as fonts stay external) and `output/NAME.pdf`. It
   checks that every book page has the same text as its validated single page.
4. Final cost report (`py scripts/costs.py` plus the orchestrator cost).

## Core rules
- Words and mathematics exact. No added, completed, corrected or reordered content.
- Keep inline formulas inline, displays displayed, paragraph structure and italics as in the source.
- Notation changes only through contract macros; they are intentional modernisation.
- Figures are traced from the scan; labels are typeset, next to the element they name, on the
  same side as in the source, with nothing between label and element, clear of all lines.
- Reviewer claims are hypotheses. Deterministic checks beat reviews where content has a rule.
- Change the design only in `design/book-style.sty`, then rebuild every page.
- All pages have the same size. Vertical spacing follows one rule for the whole book.
- Errors of the author are never corrected in the content. A verified logical or technical error
  may be marked in red (`\vberr`) with a small red note (`\vberrnote`) saying what is wrong and
  what is correct.

## References
- [models-and-lessons.md](references/models-and-lessons.md): which model can do what; costly failures.
- [local-workers.md](references/local-workers.md): direct calls, Pi and mini-swe-agent: routing,
  problems seen and solutions.
- [figures.md](references/figures.md): tracing pipeline, rules, open label-association work.
- [design-and-layout.md](references/design-and-layout.md): design principles, page-size method.
- [checks-and-costs.md](references/checks-and-costs.md): checks, cost ledger, baseline.
- [contract-template.md](references/contract-template.md): markup contract template.
- [system-requirements.md](references/system-requirements.md): tools needed on any machine or OS.

## Machine tools (this machine)
Python launcher `py` (newest Python; needs pymupdf, pillow, numpy, scipy, scikit-image,
opencv-python-headless). MiKTeX XeLaTeX on PATH. DjVuLibre in `tools/djvulibre`. Local
OpenAI-compatible server `http://127.0.0.1:8081/v1` (direct calls). Pi on PATH
(`~/.pi/agent/models.json`). mini-swe-agent as a uv tool (its own Python; found through
`uv tool dir`). GPU lease: set `gpu_mutex` in vectorbook.json (or `VECTORBOOK_GPU_MUTEX`) to the
mutex name the machine's other local GPU apps use; all local routes honour it.

## Done when
- Every page passes the hard checks; every figure's `trace.json` is ok.
- Renders compared with the sources show no difference in words or mathematics.
- Labels sit next to their elements with no collisions.
- vertical.py ran on all pages; no unresolved flags in work/vertical-report.json.
- output/NAME.tex (one document, all pages) and output/NAME.pdf exist; make_book.py says OK.
- Every erratum passes `errata.py check`.
- `work/` holds the plan, calls, issues, diffs and the cost ledger; the cost report states
  OpenRouter, local-model electricity (per route) and orchestrator cost per page against the
  baseline, failures included.
