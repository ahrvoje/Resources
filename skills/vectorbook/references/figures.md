# Figures

Hand-drawn figures are the hardest part. Models cannot redraw irregular curves faithfully, so the
skill TRACES the strokes from the scan and only modernises the style. Models read the labels.

## Pipeline (what worked)

1. Find figures from the ink: `py scripts/find_figures.py pages/pNNN`. Tall ink bands with less
   than 25 % OCR word cover are figures (text bands had 40–44 %, figures 0–3 %). Look at each
   box. Diagrams of typeset symbols and arrows (commutative diagrams) also pass this test:
   typeset them in the body instead of tracing.
2. `py scripts/trace_figure.py segment --page N --box X0,Y0,X1,Y1 --out figs/pNNN-K`
   (box in 300 dpi page pixels, about 12 px margin). Renders the page at 600 dpi and crops. Every
   small ink component becomes ONE numbered mark in `marks.png` (no clustering).
3. Label reading (google/gemini-4-argon, prompts/read-labels.txt, images crop_half.png and
   marks.png, about $0.006): `labels.json` lists, per label, all marks that form it and its LaTeX;
   caption text inside the area goes to `erase`.
4. `py scripts/trace_figure.py trace --dir figs/pNNN-K --labels figs/pNNN-K/labels.json --width-pt W`.
   Large figures at 0.85 of source size, small ones (crop narrower than 1000 px at 600 dpi) at
   0.92. The final box, labels included, must fit the measure minus 4 pt: rescale and retrace.
5. `trace.json` must say `ok`: chamfer distance p95 at most 1.2 pt in both directions (traced
   lines lie on the source lines), every label at least 2.0 pt from lines and 2 pt from labels.
6. Copy `fig.tex` to the page folder as `figK.tex`. Look at the page render beside the source.

## Tracer rules that the first project established (each fixed a real defect)

| Rule | Defect it fixed |
|---|---|
| Render the full page, crop in memory | ddjvu `-segment` measures Y from the bottom: wrong region |
| One component = one mark; no clustering before the model decides | Clusters joined letters with a nearby dashed edge, axis end and dot; removing the label removed them |
| A mark that also contains drawing (dot, line end) is not part of the label | Same |
| Erased marks lose all ink; label marks keep solid round dots (fill >= 0.68, aspect <= 1.3) | Bold hand letters were kept as "dots"; a dot beside a letter disappeared |
| Blob (filled shape) needs a compact core, a peak thickness >= 1.15 w, and at most 3 arms | Thick pen strokes became black blobs; arrow tips (0.92–1.14 w) became dots; a line crossing (4 arms) became a dot |
| Isolated small solid component = dot even when thin (peak 0.75 w) | A pole dot vanished in skeleton pruning |
| Emit every skeleton branch; assert >= 95 % of skeleton length is drawn | One loop of a self-intersecting curve was lost |
| Clearance measured from the text box (node box minus inner sep) | 2 pt inner sep doubled the required gap and pushed labels away |
| Clearance target 2.0 pt, best-clearance fallback, label search does not stop at the old bounds | Labels in small figures were pushed off the plane they name, or did not move at all |
| Locate the picture in check renders by red rules (anti-aliased edges included) | PDF annotation was dropped by XeLaTeX; rule edges counted as figure ink |

## Open problem: label–element association (future improvement)

The tracer keeps a label near its original position and clear of lines. It does not yet know
which element the label names, so in tight figures the clearance search can move a label to a
place that is ambiguous (a point label pushed off the plane that holds the point; another line
between label and point). Needed:

1. Association. `labels.json` already has `"element"`: the mark id of the named element when it
   is a small mark (dot, arrowhead). Extend it to lines, curves and regions: let the tracer number
   its traced paths and regions in a second marks image, and let the label model name the path or
   region. Fall back to the nearest element in the source.
2. Placement constraints per element type:
   - Point: the label stays within about 1.5 label heights of the point, in the same direction
     (quadrant) as in the source. Nothing may cross the straight segment from label to point.
   - Line or curve: the label stays on the same side of the line as in the source, near the same
     arc-length position, and no other line runs between label and line.
   - Plane or region: the label centre stays inside the same region (or outside, as in the source).
   - Arrow or vector: the label stays near the same end (tip or tail) and side.
3. Search order: keep the source position if it is legal; otherwise search only positions that
   satisfy the association constraints, then maximise clearance. If none exists, keep the
   association and accept a smaller clearance (minimum 1.2 pt), and report it.
4. A check: for each label, draw the segment to its element and count crossings with other
   strokes; report any crossing and any change of side or quadrant.

## Other open points
- Arrowheads are traced as open strokes (skeleton), not replaced by modern arrow tips.
- Hand-drawn shading is traced stroke by stroke; it is faithful but not modernised.
- Very damaged figures: use prompts/draw-figure-fallback.txt only for non-irregular figures.
