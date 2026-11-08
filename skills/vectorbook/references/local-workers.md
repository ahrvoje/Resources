# Local workers: direct calls, Pi, mini-swe-agent

The local model (an OpenAI-compatible server, `local_model.url` in vectorbook.json) is the cheapest
worker (first project: EUR 0.10 per hour). Three routes reach it. Choose by task shape: the harness
matters less than the task shape and the model.

## Which route for which task

| Task shape | Route | Why |
|---|---|---|
| Single shot: prompt + images in, structured answer out (transcription, body fixes from an issue list, pre-review) | **direct call** (`transcribe_local.py`, default `--via direct`; `common.local_chat`) | No harness, no stdin, no tool calls: fewest ways to fail. Images go in directly. |
| Exact, minimal edits of LaTeX in place; image-attached agent tasks | **Pi** (`transcribe_local.py --via pi`, or Pi with its edit tool) | Pi's edit tool replaces exact strings, so diffs stay minimal; `@file.png` attaches images. |
| Iterative loops with tools: build -> read log -> fix -> rebuild; run a check script and act on it | **mini-swe-agent** (`mini_task.py`) | Text-based actions need no function calling (weak local models); linear, auditable trajectory; step and time limits. |
| Counting, global replacement, contract notation the model resists | none of the local routes: **gpt-6.1-terra** or a deterministic script | The local model fails these regardless of harness. |

Measured in tests: direct transcription of a page 31 s; mini-swe-agent fixed a TeX build error
(`$\qedmark$` in math mode) in 43–116 s with a correct 3-line change; Pi transcription about 50 s.

## Shared guarantees (all routes)
- GPU lease (`common.GpuLease`, `gpu_lease`): one GPU owner at a time, shared with the other
  local GPU apps of the machine. Windows: a named mutex; other systems: an exclusive lock file.
  The name is `gpu_mutex` in vectorbook.json (default from the environment variable
  `VECTORBOOK_GPU_MUTEX`, else `Local\vectorbook-gpu`); set it to the name the machine's other
  GPU apps use, or the lease protects nothing. Direct calls and Pi hold it for the whole
  request; mini-swe-agent holds it per model query only, so its shell commands do not block other
  apps. Waiting time is logged (`lease_wait_s`) and is not work time; the watchdog ignores an idle
  GPU while the worker waits (flag file). A mutex abandoned by a crashed owner counts as free.
  The wait ends after `gpu_lease_max_wait_s` (default 1800 s) with a clear error: some apps keep
  the lease until their process exits, so a long wait means another app owns the GPU.
- Closed stdin for every subprocess.
- GPU watchdog (`common.watch`): GPU idle (< 10 %) for 90 s while the model is loaded = stalled;
  kill the process tree; an idle GPU while the model is unloaded or loading is normal.
- Every run is logged in `work/local-runs.jsonl` (route, seconds, GPU-active seconds, status);
  `costs.py` turns wall time into electricity and shows usage per route.
- The orchestrator checks GPU activity or the log instead of waiting on a silent process.
- Outputs are verified by the build and by diff; an answer without the required section changes
  nothing.

## Direct calls
- One HTTP request to `/chat/completions` with the prompt and base64 images; thinking off
  (`reasoning_effort: none`). Timeout 15 min. A `finish: length` answer is rejected.
- The prompt must make the model start with the output section (`=====BODY=====`).

## Pi: problems seen and solutions
1. **Hang with an idle GPU (the main delay).** In `-p` mode Pi reads piped stdin as extra input
   and waits for end-of-file. Started without a `stdin` argument, Pi inherited the shell's stdin;
   when that was an open pipe, Pi waited forever before calling the model. Proof:
   `sleep 60 | pi -p "Reply PONG"` hangs, `pi -p "Reply PONG" < /dev/null` answers at once.
   Solution: closed stdin; GPU watchdog; one retry when the GPU was never active.
2. **No output section.** With thinking off, Pi wrote analysis and stopped before the body.
   Solution: the prompt demands the output section first; the driver rejects answers without it.
3. **Large images lose detail.** The local image reader downsizes big images. Solution: two
   overlapping half-page images (80 px overlap).
4. **Tasks beyond the model:** counting cells in wide tables, "replace every X", contract notation.
   Send them elsewhere (see the table).
- Flags: `--no-session --no-tools --no-context-files --no-skills --no-extensions --thinking off
  -p @prompt.txt @half1.png @half2.png "<instruction>"`.

## mini-swe-agent: how the skill runs it
- Through its Python API, not the interactive `mini` command (the interactive UI needs a real
  console and crashes in a non-interactive shell on Windows).
- Text-based model class (`LitellmTextbasedModel`, packaged `mini_textbased.yaml`): the model
  writes the shell command in a fenced block; no function calling. Model `openai/<local id>` with
  `api_base` = local server; `cost_tracking="ignore_errors"` (local models have no price entry);
  LiteLLM notices suppressed.
- mini-swe-agent has its own Python environment; `mini_task.py` restarts itself under that
  interpreter (`mini_python` in vectorbook.json, `MINI_SWE_PYTHON`, or `uv tool dir`).
- Guarantees of `mini_task.py`: only the `--edit` files may change (others are restored); edit
  files are backed up as `<name>.pre-miniK`; the page is rebuilt afterwards and the backups are
  restored when a page that built before fails now; trajectory in `work/mini/`.
- Task rules (prompts/mini-task.txt): edit LaTeX with small Python scripts using exact string
  replacement and raw strings, never sed, echo or heredocs (backslashes break); rebuild after each
  change and read checks.json.

## Practical facts (first project)
- First request after the server unloaded the model: about 55 s load time.
- Generation about 75 tokens/s with speculative drafting; prompt reading about 2000 tokens/s.
- A single-GPU server serves one request at a time: local workers queue, they do not run in parallel.
