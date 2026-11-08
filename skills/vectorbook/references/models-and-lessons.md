# Models and lessons

Prices change. Check the current catalog before you choose (`https://openrouter.ai/api/v1/models`,
no key needed). The facts below come from the first project (2026-11, 10 pages of a scanned 1974
mathematics monograph). Prices are $ per million input/output tokens at that time.

## What each worker did well

| Worker | Good at | Cost seen |
|---|---|---|
| Local Pi + Qwen3.8-Flash-Next Q2 (Strata) | Page transcription from two half-page images plus OCR hint: words and mathematics nearly exact, about 50 s per page. Simple targeted body fixes (remove blank lines, add `\mcont`, change one line). | EUR 0.10 per hour, about EUR 0.002 per page |
| google/gemini-4-argon ($2/$10) | Page review (source vs render): found every known defect on the calibration page, including lost italics, wrong indents after displays, inline-vs-display changes. Label reading on numbered-mark images. | Review about $0.017 per page; labels about $0.006 per figure |
| openai/gpt-6.1-sol ($2/$10) | Long, complete code files from a precise specification (780-line tracer, $0.105). Design decisions from measured data (style file and page size, $0.04). | |
| openai/gpt-6.1-terra ($1/$5) | Precise body edits that Pi cannot do: counting cells in a 31-column table, "replace everywhere", contract notation. Writing skill text from a facts list. | About $0.01–0.02 per call |

## What failed, and what it cost

| Worker | Failure | Cost / delay | Rule |
|---|---|---|---|
| anthropic/claude-sonnet-5.5 | Reasoning is mandatory and cannot be disabled ("effort none" returns HTTP 400). At effort low it spent all 24000 output tokens on reasoning and returned no file. | $0.25 wasted, about 4 min | Do not use it for long code files. If a model returns `finish: length` with reasoning near the budget, change the model; do not raise the budget. |
| openai/gpt-6.1-terra (for code) | Wrote only the easy half of a specified tool and marked the rest "not implemented". | $0.014, one round trip | For long code use gpt-6.1-sol; say "implement every step; a partial file is useless". |
| openai/gpt-6-luna ($0.10/$0.50) | Label reading: assigned wrong marks in a dense figure. Review: missed defects and made one wrong claim. | Cheap, but cost a re-run and orchestrator time | Do not use for label assignment or review. |
| anthropic/claude-haiku-5.5 ($0.10/$0.50) | Review: found about half of the defects. | $0.003 | Acceptable only as a pre-filter. |
| Local Pi | Counting tasks (31-column staggered table): wrong twice. "Replace every X" edits: not applied. Rejected a contract notation change as "not in the source". With thinking off, wrote analysis and stopped before the requested body. | 3 wasted runs plus orchestrator turns | Send counting, global replacement and contract-notation fixes to gpt-6.1-terra. Make prompts start the reply with the output section. |
| Any model drawing figures | Cannot follow irregular hand-drawn curves (earlier projects: several paid Opus revisions per figure, still wrong shapes). Added content to a page ("(see Figure 1)"). | $0.07–0.10 per call, many rounds | Trace figures (references/figures.md). Never let a model draw an irregular figure. |

## Orchestrator lessons

- The orchestrator's own tokens are the largest cost of a pilot (about $25 estimated for 10
  pages). The per-page pipeline must run without orchestrator turns per page.
- Specifications written by the orchestrator can be wrong (ddjvu `-segment` measures Y from the
  bottom; `\ifdefined\ifX ... \fi` breaks when TeX skips it). Test every new tool on one input
  before a batch.
- Do not estimate coordinates from images shown to the orchestrator: the viewer scales them.
  Measure from the pixels (scripts/find_figures.py).
- A deterministic check beats a review for structured content: an arithmetic check of a
  binomial table found a missing digit that two reviews did not report.
- Treat reviewer claims as hypotheses. A reviewer's proposed table fix had a wrong column offset.
