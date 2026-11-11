# Acadza Report → Fix

A triage engine that turns student "Report error" comments into safe, surgical fixes, and a review console a tired faculty member can clear at 10 PM.

- **`results.json`**: 44 reports triaged (verdict, repair, edit, route, confidence, evidence, student reply)
- **`findings_unreported.json`**: 18 defects no student reported, across 15 questions (bonus)
- **`console/`**: the faculty review console (static; deploys as-is)
- **[PROMPTS.md](PROMPTS.md)**: every product prompt verbatim, the orchestration, AI mistakes, decision log
- **[PRODUCT.md](PRODUCT.md)**: who loses most, what never auto-applies, week-1 metric, one pitch
- **[BRIEF.md](BRIEF.md)**: the original assignment brief

> **Honesty note.** No API key was available while building, so the two LLM stages were answered by Claude (my coding assistant) using the exact production prompts, and stored as hash-checked recordings. Everything else ran as real code: detectors, guards, routing, apply, export. Running with `--live --record` replaces every recording with real API output. Details: [PROMPTS.md §0](PROMPTS.md#0-how-resultsjson-was-produced-read-this-first).

## Results at a glance

| | |
|---|---|
| Reports | 44 on 39 questions (+4 unreported questions swept) |
| Routes | **19 auto_apply** · **8 faculty_review** · **17 no_change** |
| Verdicts | 27 defect · 11 no_error · 2 display · 1 app · 1 language · 1 already_fixed · 1 not_actionable |
| Wrong answer keys fixed | LCR 130 V → 50 V (3 reports), gas pressure A → D, flux n 2 → 1, malformed mcq key `["A, B, D"]` |
| Traps handled | prompt injection (R027) ignored and blocked; student right that the key is wrong but wrong about the value (R004); unsound A/R question sent to faculty, not re-keyed (R034); already-fixed typo (R017); invented distractor refused (R009/R010) |

## How it works

```
report ─► screen comment (code) ─┐
record ─► detectors (code) ──────┼─► blind solve (LLM: stem+options only) ─► judge (LLM: 1 call per question)
                                 │                                                │
                                 └──────────────────────────────► guards (code) ◄─┘
                                                                     │
                                         auto_apply · faculty_review · no_change
```

The LLM proposes; code decides. An edit auto-applies only if it is in the repair's field scope, anchors to exactly one place in the stored HTML, preserves what that repair must not change (digits for spelling and markup, stem for options, only insertions for units), agrees with the blind solve when it touches the key, and clears the confidence bar. Anything else goes to faculty with the failed check spelled out. Full table: [PROMPTS.md §1](PROMPTS.md#1-orchestration-what-runs-in-what-order-and-why).

## Run it

Python 3.10+, standard library only (the `anthropic` SDK is needed only for live runs).

```bash
python3 -m engine.run
```

Replays recorded LLM outputs and rewrites `results.json`, `findings_unreported.json`, `console/data.json` and `data/questions.patched.json` (the DB after auto-fixes).

```bash
python3 -m unittest discover -s tests -t .
```

Runs the guard and detector tests.

```bash
python3 -m http.server 8765 --directory console
```

Serves the console at http://127.0.0.1:8765.

Live run with real API calls (Claude Opus 5.5, structured outputs, prompt caching):

```bash
pip install -r requirements.txt && export ANTHROPIC_API_KEY=sk-ant-... && python3 -m engine.run --live --record
```

## Deploy the console

It's a static folder. With Vercel or Netlify, import the repo and the included `vercel.json` / `netlify.toml` publish `console/`. With GitHub Pages, publish the `console/` folder. The console loads precomputed results from `console/data.json` and makes no LLM calls in the browser.

## Console

- **Queue grouped by question,** in four lanes: *Needs your decision* → *Auto-applied · spot-check* → *Found by sweep* → *Replies only*. Within a lane, cases are ordered by harm (wrong grading → unanswerable → wrong teaching → mis-filed → cosmetic), then by number of reporters.
- **Each case shows** the change in one line ("Key C → A", "plexux → plexus"), rendered before/after with MathML and only the changed span highlighted (or the raw HTML diff), the blind solve, the evidence, the guard checks, every student comment, and the reply each will get.
- **Approve / Edit (live preview) / Reject or Revert,** each written to an append-only, exportable audit log with undo. Keyboard: `j` `k` `a` `e` `r` `s` `u` `/` `?`.

## Layout

```
engine/      records.py · linearize.py (HTML+MathML → text) · detectors.py · comments.py
             prompts.py · llm.py (live/replay) · guards.py · run.py (pipeline)
engine/replay/   recorded LLM outputs (hash-checked)
tools/record_offline.py   how those recordings were produced
tests/       guard + detector tests
console/     index.html · app.js · app.css · data.json
```
