# Markup contract (template)

`init_project.py` copies this file to `design/contract.md`. Edit only the project copy: add the
book's notation macros, remove what the book does not need. The project style must implement
every command listed here; transcribers and figure tools use only these commands.

## Page
- `\vbhead{<printed page>}{<head text>}` is written by `build_page.py`; never in the body. The
  number sets the folio and the parity (even = verso). Head text in normal case.

- `\vbendpage{fill|<dim>}` closes every page; written by the scripts (vertical.py), never in the body.

## Errata (additions; the original stays unchanged)
- `\vberr{<original text or math>}` marks a verified error of the author in red. The content
  inside stays character for character the same.
- `\vberrnote{<what is wrong>; <what is correct>.}` adds a red note mark (e1, e2, ...) and a small
  red footnote. Text mode only: after a display, not inside it.
- Only for logical or technical errors confirmed by an independent check; `errata.py check`
  proves that removing the markup gives back the original body.

## Paragraphs and sections
- `\mcont` starts a paragraph that continues from the previous page (no indent).
- `\mpar` is a plain paragraph break (or a blank line).
- `\msection{<title>}` is a mid-page section title; the next paragraph is unindented.
- No blank line after a display unless the source starts a new indented paragraph there.

## Statements and proofs
- `\begin{mstatement}{Lemma}{1.2} ... \end{mstatement}`: small-caps label, italic body. Number
  without the final period. Named results: `\begin{mstatement}{Gauss–Bonnet Theorem}{}`.
- `\begin{mdefinition}{Definition}{} ... \end{mdefinition}`: same label, upright body. Also for
  Remark, Example, Problem.
- `\begin{mproof} ... \end{mproof}` prints "*Proof.*"; `\begin{mproof}[Proof of 1.2]` for another label.
- `\qedmark` is the end-of-proof mark, typed exactly where the source prints it. In text it goes
  flush right; at the end of a top-level display it becomes a tag. Never inside `aligned`.

## Figures and diagrams
- `\mfigure{\input{figK}}{Figure 2.}`: centred figure, caption label as printed. Empty label `{}`
  for an uncaptioned figure (no caption space).
- `\mfigurecap{\input{figK}}{Figure 2.}{<caption text>}` with descriptive caption text.
- figK.tex is produced by `trace_figure.py` (or the fallback prompt), never by the transcriber.
- Commutative diagrams of typeset symbols are typeset in the body with `tikzcd`.
- TikZ styles: `mm main`, `mm thin`, `mm hatch`, `mm hidden`, `mm arrow`, `mm vec`, `mm dot`,
  `mm label`, `mm plane`, `mm surface`. Colours `mmink`, `mmaccent` and their tints.

## Displays
- `\[...\]`, `align*`, `\begin{aligned}` inside `\[...\]`; punctuation after a display stays inside it.
- `\begin{mbracesys}[<row gap>] a &= b \\ c &= d \end{mbracesys}`: left brace + aligned rows.
- `\begin{mbracetable}[<arraystretch>]{<colspec>} ... \end{mbracetable}`: left brace + array.

## Text commands
- `\emph{...}` for italic words and sentences in upright text. `\mcite{Author, 1953}` for citations.

## Notation (general)
- `\R \C \Z \Q`: blackboard bold number systems.
- `\dd`: upright differential d (`\dd x`, `\dd p/\dd* t`; starred form directly after a slash).
- `\op{name}`: upright operator name. Maps: `f\colon X\to Y`.

## Notation (this book) — fill in per project
- One line per macro: the command, what it typesets, an example, and the source form it replaces.
  These macros modernise notation on purpose; a reviewer or fixer must use them even where the
  scan shows the old letter form.
