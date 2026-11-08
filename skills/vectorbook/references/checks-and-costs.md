# Checks and costs

## Hard checks (build_page.py; any failure = not done)
XeLaTeX return code 0; exactly one page; paper size equal to the project style; no raster
images; all fonts embedded; no "Missing character"; no TeX error lines; no overfull boxes.
With `--svg`: no `<image>` in either SVG, no `<text>` in the outlined SVG.

## Figure checks (trace.json)
`ok` = chamfer p95 <= 1.2 pt both ways, every label >= 2.0 pt from lines and >= 2 pt from other
labels, >= 95 % of the skeleton drawn. Then look at the figure beside the source: labels next to
the elements they name, on the same side, nothing between label and element.

## Content checks
- Two review rounds with google/gemini-4-argon (prompts/review-page.txt): one after transcription,
  one after the fixes. Verify each claim against the source before you send it to a fixer.
- Script checks for structured content whenever the content follows a rule (tables of numbers,
  sequences, matrices). Example: a mod-2 binomial table checked against C(r, i) mod 2 and the
  expected stagger found a missing digit.
- Every fix is integrated by diff: only the intended lines may change.

## Final checks (book level)
- vertical.py: every page one page; short/full as in the source; no figure top shift > 0.15;
  flagged full pages with > 3 empty lines are reviewed (page size or figure size).
- make_book.py: page count; each book page has the same text as its validated single page;
  paper size; fonts embedded; no raster images; no overfull boxes.
- errata.py check on every page with errata: removing the markup gives the original body exactly.

## Cost measuring (do it while working, not at the end)
Baseline: **$0.05 per page**, all-in except one-time setup. It is hard; work towards it.
- Every OpenRouter call goes through `scripts/worker.py` with `--page pNNN --role ROLE` (no page =
  one-time work). Every Pi run goes through `scripts/pi_transcribe.py`. Both log to `work/`.
- Run `py scripts/costs.py` after every page or batch. It prints cost per page (OpenRouter + Pi
  electricity) against the baseline, by role and by model, and lists failed or wasted calls.
- Record the orchestrator's own cost with `py scripts/costs.py --orchestrator USD --note TEXT`
  (from `/cost` or the account console) at each milestone. Mark estimates as estimates.
- When a page goes over the baseline, find the role that caused it before the next page.

## Budget per page that met the target (first project, steady state)
| step | worker | cost |
|---|---|---|
| transcription + about 2 fixes | local Pi | about EUR 0.002 |
| 2 reviews | gemini-4-argon | about $0.034 |
| labels | gemini-4-argon | about $0.006 per figure |
| occasional precise fix | gpt-6.1-terra | about $0.01 when needed |
| total | | about $0.04–0.05 |

First project totals for 10 pages: OpenRouter $1.10 (one-time $0.54 of which $0.25 wasted,
calibration $0.07, page work $0.49); Pi about EUR 0.05; orchestrator about $25 (estimate).
The orchestrator cost dominates a pilot; a production run must not need orchestrator turns per page.
