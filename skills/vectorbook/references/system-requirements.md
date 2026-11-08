# System requirements

What must be available for this skill to work on any machine and operating system. This file
does not describe installation or configuration.

## Required
| Need | Tool used | Role |
|---|---|---|
| Agent orchestrator | Claude Code or another agent that runs shell commands, reads and writes files, and views images | plans, runs scripts, verifies |
| Python 3.12 or newer | packages pymupdf, pillow, numpy, scipy, scikit-image, opencv (headless) | all scripts |
| TeX with XeLaTeX | LaTeX packages fontspec, unicode-math, geometry, microtype, xcolor, tikz (libraries arrows.meta, calc, decorations, patterns, shapes, cd), amsmath, mathtools, etoolbox, xparse; LaTeX kernel with filecontents | page builds, figure checks, final book |
| OpenType fonts | Libertinus Serif and Libertinus Math (or the fonts the project style names) | typesetting |
| Remote models | OpenRouter account, API key, internet access | review, label reading, precise fixes, code, design |
| Local model | an OpenAI-compatible server with a vision-capable model that reads a half page (first project: Strata serving Qwen3.8-Flash-Next Q2_0) | cheap transcription and fixes |
| Local agent CLI | Pi coding agent (needs a Node.js runtime) connected to that server | runs the local model in non-interactive mode |
| GPU monitoring | a command that reports GPU utilisation (nvidia-smi for NVIDIA) | Pi watchdog |

## Source formats
- DjVu: DjVuLibre command-line tools ddjvu, djvused, djvutxt (Windows binaries are bundled in
  `tools/djvulibre`; other systems need their own).
- PDF scans: PyMuPDF only.

## Optional
- dvisvgm (SVG output checks).
- A fast file finder (Everything on Windows) to locate tools and files.
- Wolfram or another computer-algebra system to check suspected errors in the original.

## Operating-system specific points in the scripts
- The Python launcher is `py` on Windows; use `python3` elsewhere.
- `pi_transcribe.py` starts Pi through the shell (Windows needs it for `pi.cmd`) and stops a
  stalled run with `taskkill /T /F`; on Linux or macOS use a process group and kill the group.
- The watchdog reads GPU load with nvidia-smi; for other GPUs replace `gpu_busy()`. Without a
  GPU query the watchdog cannot detect a stall and only the hard time limit applies.
- Paths inside scripts use pathlib; no drive letters are assumed.

## Capacity seen in the first project (for planning, not a minimum)
RTX 4080 16 GB, 64 GB RAM, about 66 GB of local model files; about 50 s per page transcription,
75 tokens/s generation. A smaller local model works if it reads half-page images accurately;
test it on 2–3 pages with known content first.
