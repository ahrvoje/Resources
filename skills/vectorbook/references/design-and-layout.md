# Design and layout

## Principles
- One style file per project: `design/book-style.sty`. Change the design only there, then rebuild
  every page. Pages get a copy at build time; never edit the copy.
- One source page becomes one new page with the same folio. The page must hold the densest page.
- Change: typeface, page size, measure, spacing, notation style (through contract macros), heads,
  statement labels, figure style, line and page breaks.
- Never change: words, numbering, citations, formulas (symbols, indices, order, meaning),
  paragraph continuation, unfinished endings, figure topology, the position of end-of-proof marks.
- If a notation change could alter meaning, keep the source form.
- Do not stretch a page to fill it. After modernisation pages are 70–90 % full.
- Layout and design decisions are made by a design worker (prompts/design-style.txt) from
  measured data; the orchestrator measures and runs the experiments.

## Template design (assets/style-template.sty)
Libertinus Serif and Libertinus Math (one lineage; true small caps; complete double-struck and
script alphabets; extensible braces). Lining figures in text, old-style in folio and head.
Running heads in letter-spaced lowercase small caps; the folio in one accent colour. Statements:
small-caps label, italic body; definitions upright. Microtype protrusion only, `\frenchspacing`,
`\raggedbottom`. Figure strokes 0.8 / 0.5 / 0.35 pt, dashed hidden lines, labels in body italic
9.5 pt. Starting trim 5.5 x 8.5 in, 25 pc measure, 37 lines of 10.5/13 pt.

## Page-size optimisation (once per book, before production)
The page size, measure and number of lines are fixed for the whole book; every page has the same
size. Determine them from data:
1. Transcribe and build a sample of about 10 characteristic pages: the densest text, the widest
   tables and displays, the largest figures, a short page.
2. `py scripts/pagesize.py pages/pAAA pages/pBBB ...` builds every sample page at standard trims
   near the source trim (5 x 8 in to 7 x 10 in; add others with `--extra 5.6x8.6`). Type size and
   leading stay fixed; measure, margins and text height keep the style's proportions; the text
   height is a whole number of lines. Per trim it records: pages that fit, fill min/mean/max,
   overfull text lines (figure overfulls apart; figures are rescaled to the measure).
3. Ranking: all pages fit, no text overfull, max fill <= 0.97 (headroom for fixes), then the
   smallest page (the owner prefers the smaller side), then the highest mean fill.
4. The design worker confirms or adjusts with the table (prompts/design-style.txt) and writes the
   project style. If no trim is feasible, change the type size or leading, not the content.
   Fill here is natural content height / text height. A page with figures over the headroom
   can still be fitted by tracing its figures smaller; a page of pure text cannot. Weigh this
   when the only failing pages carry figures.
5. Retrace figures for the new measure; then build all pages.

## Vertical layout (final step, all pages)
One rule for every page, so pages look alike and each page is balanced in itself. Run
`py scripts/vertical.py` after all pages pass their checks and before the final book.
- Every page is flush-bottom; `\vbendpage{...}` closes it.
- Full pages (the source text reaches the normal block bottom) share their free space among the
  stretchable gaps (display, figure and statement skips) in proportion to each gap's declared
  stretch. Text lines keep their grid. Each gap grows at most `--rmax` (default 2) times its
  declared stretch, the same limit on every page; the rest stays at the bottom.
- Short pages (the source ends early: section or chapter end) stay ragged, as in the source.
- Checks in work/vertical-report.json: every page still one page; short and full pages as in the
  source; figure top position within 0.15 of the page height of the source; a full page with more
  than 3 empty lines at the bottom is flagged (a sign that the page size is too large).
- The style controls the look: declare stretch only on gaps that may grow (for example display
  skips plus 3 pt, figure skips plus 4 pt), never on the baseline skip or the paragraph skip.

First project result (6 x 9 in typewriter-set monograph, measure 321 pt, pitch 15.6 pt):
| trim | fit | fill min/mean/max | problems |
|---|---|---|---|
| 6 x 9 in, 27 pc | 10/10 | 0.69/0.76/0.86 | too empty |
| 5.5 x 8.5 in, 25 pc | 10/10 | 0.74/0.84/0.94 | none (chosen) |
| 5.25 x 8 in, 24 pc | 9/10 | 0.84/0.92/1.01 | a page overflows, the widest table too wide |
| 5 x 8 in, 23 pc | 8/10 | 0.84/0.93/1.00 | overflows, 5 pages with overfull lines |

## Style defects found and fixed (check new styles for them)
- An end-of-proof macro that sets `\parfillskip=0pt` globally justifies every later last line on
  the page. Make it local to its paragraph.
- An empty figure caption label must print no caption line and no caption space.
- Load `tikz-cd` for commutative diagrams.
- Wide arrays (for example a 31-column staggered triangle) need a smaller `\arraycolsep` to fit a
  smaller measure; the build's overfull check finds them.
