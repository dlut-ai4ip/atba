# `demo.html` — a static, offline walkthrough of the real interface

[`demo.html`](demo.html) is a single self-contained file (~5.4 MB, no external requests, no build
step, no API keys) that renders the *actual* frontend — same React components, same styling, same
routing — driven by one real, complete run of the six-step pipeline instead of a live backend. Just
download it and open it in a browser.

## What run it shows

A genuine end-to-end run (DeepSeek + live Scopus retrieval, 2026-09-12) on the phenomenon: a large
technology company shifted its entire workforce to full-time remote work, and its employees'
collaboration networks became more static and siloed — fewer distinct coworkers, less cross-group
communication, a shift from real-time calls to email — even though total hours worked and time in
meetings barely changed. Step 3 characterized this as an **anomalous reversal**: the structural-holes
tradition in social capital theory predicts the *opposite* direction (co-location loss should, if
anything, make lean electronic media the substrate for preserving cross-group bridging), not the
closure this case actually shows. Steps 4–6 carry that anomaly through to a full candidate theory,
adversarial interrogation, and a theory-section report — nothing in the demo is scripted or
hand-edited; it's the model's real output, unedited except for language (see below).

All six `runs/<run_id>/stepN.json` files backing this demo are bundled at
[`frontend/src/demo-data/`](frontend/src/demo-data) — read the raw structured output directly if you'd
rather not open the rendered page.

## How it's built (and how to regenerate it with your own case)

1. Run the six CLI steps for real against your own phenomenon (see [`atba/README.md`](atba/README.md)
   "安装与运行"), reusing one `--run-id` throughout so a single `runs/<run_id>/` accumulates all six
   `stepN.json` files.
2. Copy those seven files (`manifest.json` + `step1.json` … `step6.json`) into
   `frontend/src/demo-data/`, replacing the ones there, and update `DEMO_RUN_ID`/the
   `phenomenon_preview` string in [`frontend/src/demo-data/index.ts`](frontend/src/demo-data/index.ts)
   to match.
3. `cd frontend && npm install && npm run build:demo` — this runs a dedicated Vite config
   ([`vite.demo.config.ts`](frontend/vite.demo.config.ts)) that bakes `VITE_DEMO_MODE=true` into the
   build, inlines all JS/CSS/the favicon into one file via `vite-plugin-singlefile`, and writes
   `frontend/dist-demo/demo.html`.
4. Copy that file to the repo root as `demo.html`.

## How the "no backend" trick works

`src/api.ts`'s `request()` function normally does a real `fetch()` against the FastAPI backend. When
`VITE_DEMO_MODE` is set, read-only GET calls (`getRunStepN`, `getRunManifest`, `listRuns`, `getHealth`)
are instead resolved directly from the bundled JSON in `src/demo-data/` — the six `Step*RunPage`
components never know the difference, because visiting `/runs/:runId/stepN` directly (not arriving via
a fresh submission) already only ever calls the GET variant, never the streaming POST one. `main.tsx`
switches to a `HashRouter` (so the file works when opened via `file://`, where there's no server to
handle a deep link on refresh) and seeds a fake auth token so the login page is skipped. Writes (new
runs, login, saving a step-2 selection) are not supported in demo mode and are not reachable from a
normal click-through of the six step pages.

## Known limitation

Steps 3–5's narrative content came back in Chinese on the first attempt despite requesting
`lang="en"` — DeepSeek was apparently treating "the task instructions are in English" as a formatting
cue rather than an instruction to answer in English. Fixed in
[`atba/prompts.py`](atba/prompts.py)'s `_wrap_thinking_language()`, which previously only emitted a
hard language directive for `lang="zh"` (on the assumption that English needed no reinforcement — true
for the model's internal thinking, not for its final structured output). The run bundled here was
generated *after* that fix, using the corrected prompt.
