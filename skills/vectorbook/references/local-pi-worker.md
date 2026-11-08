# Local Pi worker

Pi (`@earendil-works/pi-coding-agent`, `pi` on PATH, config in `~/.pi/agent/models.json`) runs
on a local model server (Strata, OpenAI-compatible, `http://127.0.0.1:8081/v1`). It is the
cheapest worker (EUR 0.10 per hour). Use it for transcription and simple fixes. Always start it
through `scripts/pi_transcribe.py`, never by hand.

## Problem 1: Pi hung with an idle GPU (the main delay)

Symptom: a Pi call ran for many minutes; the GPU stayed at 0 %; no output. It happened only
sometimes, so it looked random. The orchestrator waited instead of checking the GPU.

Cause: in `-p` mode Pi reads piped stdin as extra input and waits for end-of-file. The driver
started Pi without a `stdin` argument, so Pi inherited the shell's stdin. When that stdin was an
open pipe, Pi waited forever before it called the model. Test that proved it:
`sleep 60 | pi -p "Reply PONG"` hangs; `pi -p "Reply PONG" < /dev/null` answers at once.

Solution:
1. Start Pi with a closed stdin (`stdin=subprocess.DEVNULL`; `< /dev/null` in a shell).
2. GPU watchdog: sample `nvidia-smi` every 3 s. GPU idle (< 10 %) for 90 s while the server
   reports the model as loaded = stalled. Kill the Pi process tree (`taskkill /T /F`).
   An idle GPU while the model is unloaded or loading is normal: do not count it.
3. Retry once when the GPU was never active (Pi never reached the model).
4. Log every run in `work/pi-runs.jsonl`: seconds, GPU-active seconds, status. The electricity
   cost comes from these records.
5. The orchestrator checks GPU activity (or the log) instead of waiting. A Pi call normally
   takes 10–90 s.

## Problem 2: Pi's answer had no usable output section

Symptom: with thinking off, Pi wrote its analysis ("Looking at the source images ...") and
stopped before the `=====BODY=====` section.
Solution: every Pi prompt says "start your reply with the line =====BODY=====; write no analysis
before it; give reasons only in NOTES". The driver refuses an answer without a body and keeps the
old body.

## Problem 3: large images lose detail

The local model's image reader downsizes large images (about 1600 image tokens). A full 300 dpi
page loses sub- and superscripts. Solution: send the page as two overlapping halves (80 px
overlap) and say that overlapping lines appear twice.

## Problem 4: tasks beyond the local model

Pi (Q2 quantised model) failed at: counting cells in wide tables, "replace every X with Y",
applying a contract notation that differs from the scan's letter form. Send those to
openai/gpt-6.1-terra and verify by script or diff.

## Practical facts

- First request after the server unloaded the model: about 55 s load time.
- Generation: about 75 tokens/s with speculative drafting; prompt reading about 2000 tokens/s.
- Pi CLI flags used: `--no-session --no-tools --no-context-files --no-skills --no-extensions
  --thinking off -p @prompt.txt @half1.png @half2.png "<instruction>"`.
- Other local clients (other agents, image tools) can share the server; a long run by another
  client looks like a slow Pi run but shows GPU activity.
