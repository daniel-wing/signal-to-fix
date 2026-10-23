# UpstreamW (formerly Signal-to-Fix): what is built today

Status as of 2026-10-23, read from the code, `config.yaml`, `README.md` and `eval_runs/` in this repo. All data is synthetic (LumenPay business case, Deliverable 4).

## 1. In one paragraph

UpstreamW is a working prototype that turns a batch of closed customer support conversations into a picture leaders can act on. A Customer Experience or Operations lead uploads a file of conversations to a web page. The tool hides personal data on the local machine, has an AI model sort every case into a fixed customer pain category and score its root cause across the 4Ps (People, Process, Policy, Product), sends risky or unclear cases to a person, and summarizes what customers are saying, with numbers, spike alerts and customer quotes. It solves a real gap: today the reasons customers contact support are tagged by hand, inconsistently and too late to steer fixes upstream. UpstreamW gives that view in about two minutes for 60 cases, without personal data leaving the machine. It supports human decisions; it does not write recommendations or reply to customers.

## 2. From a closed case to the final output

| # | Step | Where it runs | Model |
|---|---|---|---|
| 1 | **Upload.** A JSON file of cases (each needs a `text`; `id`, `market`, `channel`, `date` are used when present) is uploaded on the page. | Local | None |
| 2 | **Mask by pattern.** Emails, phone numbers, card numbers and card endings, account numbers, tax IDs (RFC, NIT, CPF, CNPJ), amounts and other long ID numbers are replaced with labels such as `[CARD_LAST4_1]`. | Local | None |
| 3 | **Mask names and addresses.** A small model on the same machine lists the names and addresses; Python replaces them with labels such as `[NAME_1]`. The label-to-value map is saved in `vault.json`. | Local | `qwen2.5:3b` via Ollama |
| 4 | **Leak check.** Before anything is sent, the patterns run again and every original value in the map is searched for. If anything is found, or masking failed, nothing is sent and the case goes to a person. | Local | None |
| 5 | **Classify.** Only the masked conversation, plus the instructions in `prompt.txt`, is sent out. The model returns the pain category, a detail (sub-reason), a possible mix-up with another category, a 0 to 1 score for each of the 4Ps with a supporting quote, defect and repeat-contact flags, its confidence and a one-sentence reason. Invalid replies get one retry; a failure or a 30 second timeout sends the case to a person. Six cases are sent at a time. | **External** | `claude-sonnet-5-5` (effort low), called through the Claude Code command line on this machine |
| 6 | **Route.** Fixed rules from `config.yaml` decide the next step (section 5) and propose an owner from the leading P. | Local | None |
| 7 | **Spike alert.** For each category, the share of cases in the last 3 days is compared with the 27 days before. Sensitive cases are tracked separately. | Local | None |
| 8 | **Show.** The page fills in three steps as the work runs, with progress bars and live commentary: Step 1 before and after masking, Step 2 every case sorted, Step 3 the summary at a glance plus the deeper analysis. The result is saved and stays on screen until someone starts a new analysis. | Local | None |

Time measured on the 60 test cases: about 1 minute 45 seconds (masking about 1 minute, classification about 45 seconds).

## 3. Map of the flow and the files

```
  cases file (JSON)
        |
        v
  [ Page: app.html ] --upload--> [ run.py: page server, 127.0.0.1:8000 ]
                                          |
  ON THIS MACHINE                         v
  ------------------------------------------------------------------------
    mask.py   patterns ----------------> labels like [EMAIL_1]
              local model (Ollama) ----> labels like [NAME_1]      vault.json
              leak check -- found something? --> STOP, to a person
                     | clean
  ===================|====================================================
  OUTSIDE            v
    classify.py  masked text + prompt.txt --> Claude Code --> claude-sonnet-5-5
                     |  category, 4P scores, flags, confidence
  ===================|====================================================
  ON THIS MACHINE    v
    route.py   rules + thresholds from config.yaml --> next step and owner
    alerts.py  last 3 days vs 27 days before --> spike alert
    run.py     saves results/latest.json --> page Steps 1, 2, 3
    run_eval.py  compares with expected labels --> eval_runs/<date>.md
```

| File | What it does | Reads | Writes |
|---|---|---|---|
| `run.py` | Setup check, runs the whole pipeline (all cases or one), page server with upload, progress and saved state | `config.yaml`, `cases_raw.json` or the uploaded file, `app.html`, `how.html` | `results/latest.json` |
| `mask.py` | Masking by pattern and by local model, leak check, saving the label map | Case text, Ollama | `vault.json` |
| `classify.py` | Calls the external model (Claude Code command line, or the Anthropic API when switched), checks the reply, one retry | `prompt.txt`, `config.yaml` (`llm`), masked text | Nothing on disk; returns the result and exactly what was sent |
| `route.py` | Routing rules and proposed owners | `config.yaml` (`routing`) | Nothing |
| `alerts.py` | Spike alert per category, plus sensitive cases | `config.yaml` (`alerts`), results | Nothing |
| `run_eval.py` | Scores results against the expected labels; fresh run or `--saved` | `cases_raw.json`, `results/latest.json`, `config.yaml`, `prompt.txt` | `eval_runs/<timestamp>.md` and `.json` |
| `common.py` | Shared helpers: config, `.env`, calls to Ollama (bypassing any proxy), text normalizing | `config.yaml`, `.env` | Nothing |
| `config.yaml` | Every setting a person may change live: models, thresholds, risk words, alert rule, paths | | |
| `prompt.txt` | The instructions sent to the external model: categories, activation vs decline rule, sub-reasons, 4P definitions, output format | | |
| `app.html` | The page: upload, three steps, how far to trust it | `/api/state`, `/api/job` | |
| `how.html` | Plain-language explanation with a diagram, for non-technical readers | | |
| `cases_raw.json` | 60 synthetic Spanish cases with planted personal data and expected labels | | |
| `README.md`, `AI_RECORD.md`, `TODO.md`, `demo_cases.md` | Setup and use, what was delegated to AI and how it was checked, later work, paste-ready demo cases | | |
| `eval_runs/` | Every evaluation, with the config and prompt used, committed | | |

## 4. Data boundaries

**Never leaves the machine**
- The original conversation text.
- `vault.json`, the map from each label back to the real value (git-ignored).
- `results/latest.json`, which holds the originals for the before and after view (git-ignored).
- Everything sent to the masking model: Ollama runs on this machine, and the code calls it without any proxy.
- The page itself: the server listens only on 127.0.0.1 and is reached through an SSH tunnel.

**Sent out, per case**
- The masked conversation, wrapped in `<conversation>` tags, and the text of `prompt.txt`. Exactly what was sent is kept with each result.
- It goes to Anthropic through the Claude Code command line, with no tools, no saved settings, no extra connectors and no saved session.

**How the leak check blocks a send**
1. After masking, the labels are removed from the text and every pattern runs again on what is left.
2. Every original value in the label map is searched for in the text, ignoring case and accents.
3. If either finds anything, or masking itself failed, the case is marked "Stopped", the model is never called, and the case is routed to a person ("Masking problem, nothing sent").

**Limit:** the check catches known formats and values the masker already found. A name the local model missed has no fixed shape, so the check cannot see it. That is why production needs the Gate 0 checks and a Legal review.

## 5. Routing rules as configured today

Applied in this order; the first match wins.

| Order | Condition | Next step |
|---|---|---|
| 1 | Masking problem or leak found | Human-led (nothing sent) |
| 2 | A risk word appears (35 words and phrases: fraud, unrecognized charge, account takeover, account lockout in Spanish and Portuguese, legal). Matched as whole words, ignoring case and accents | Human-led |
| 3 | The model did not answer or gave an invalid reply twice | Human-led ("Nothing auto-tagged") |
| 4 | Category is unknown | Emerging (a person names it) |
| 5 | Confidence below **0.60** | Human-led |
| 6 | Card activation vs payment declined is ambiguous | Review queue |
| 7 | Repeat contact (`repeat_to_review: true`) | Review queue |
| 8 | Confidence below **0.85** | Review queue |
| 9 | Everything else | Auto-tag |

**Proposed owner:** the leading P always gets one, plus any other P scoring above **0.50**.

| P | Owner |
|---|---|
| People | Team lead: coaching |
| Process | Process owner |
| Policy | Policy: cost-benefit review |
| Product | A bug draft for engineering if it is a defect, otherwise a user-story candidate for the PM weekly review |

**Spike alert:** last **3** days vs the **27** before; it fires when a category's share is at least **2x** and has at least **3** cases.

**Where to change them:** all in `config.yaml`, read again on every analysis, no restart needed.
- `routing`: `auto_tag_min_confidence`, `review_min_confidence`, `secondary_owner_min_score`, `repeat_to_review`, `risk_words`.
- `alerts`: `recent_days`, `baseline_days`, `min_ratio`, `min_recent_cases`.
- Categories and 4P definitions live in `prompt.txt`.

## 6. How to run it

On the zbook server directly:

```bash
cd ~/projects/signal-to-fix && .venv/bin/python run.py serve
```

Then open http://localhost:8000. The server runs on port 8000 and listens only on this machine.

From the MBP16 (the zbook is headless), one command starts the server and opens a tunnel; Ctrl+C stops both:

```bash
ssh -t -L 47321:localhost:8000 wing@zbook-server 'cd ~/projects/signal-to-fix && .venv/bin/python run.py serve'
```

Then open **http://localhost:47321** on the MBP: port 47321 on the laptop maps to 8000 on the server.

Other commands: `python3 run.py check` (setup check with one tiny model call), `python3 run.py --only C001` (one case, every stage printed), `python3 run_eval.py` (fresh evaluation), `python3 run_eval.py --saved` (score the last analysis without calling the model).

Needs Ollama with `qwen2.5:3b` and Claude Code logged in on the machine.

## 7. Current status

**Works end to end, tested on the 60 cases**
- Upload, local masking, leak check, classification, routing, spike alert and the three-step page.
- Progress bars and live commentary while it runs.
- The analysis stays on screen across page visits, and the page reconnects to a run in progress. "New analysis" starts over.
- Evaluation that writes a committed report.
- Live edits to `config.yaml` and `prompt.txt` take effect on the next analysis.
- Breaking the model call on purpose (for example a wrong `llm.cli`) sends every case to a person with "Classification unavailable".

**Partial**
- **Offline behavior:** tested by sending the model call to a dead proxy, not by switching Wi-Fi off. Turning off Wi-Fi needs admin rights and would cut the server's only connection.
- **Anthropic API backend:** coded and selectable with `llm.backend: api`, but never run. There is no `.env` key; every recorded run used Claude Code.
- **4P root cause:** the leading P matches the expected label only 52% to 57% of the time, mostly Process vs Product. It is tracked but not gated, and owners are proposals a person confirms.
- **Repeat contacts:** the case file still labels C008 and C047 as auto-tag, but the rule now sends them to review.
- **Brazil:** cases are in Spanish for this demo, with some Portuguese lockout phrases in the risk list.

**Missing**
- A fresh held-out test set: masking and risk words were tuned on the same 60 cases they are scored on.
- Human-human agreement, so the full Gate 0 cannot pass yet.
- A model-side risk flag as a second net behind the word list.
- Governance for adding categories.
- Portuguese conversations.
- A screen for working the review queue.
- History: only the latest analysis is kept.
- Hosting beyond one machine.

**Known bugs and rough edges**
- `README.md` still describes the earlier page:
  - pasting a single case and a "Run live" button
  - a "Show the last analysis" button

  The page is upload-only now; for a single case, use a one-case file or `run.py --only`.
- Eval reports from fresh runs say "Source: fresh run against the API" even though the call goes through Claude Code.
- `vault.json` is keyed by case id. Two uploads that reuse an id (or files without ids, which get R001, R002 and so on) overwrite each other's map. The map is not used for display, so the visible effect is none today.
- One analysis at a time; a second upload is refused until the first finishes. A server restart forgets a run in progress.
- Changes to Python files need a server restart. The page server running since 00:24 on 2026-10-23 predates the latest server change (reconnecting during a run). Restart it once.

## 8. Latest evaluation numbers

Reported in pairs (fresh, saved): the latest fresh run called the model; the latest saved scoring re-scored the page's last analysis without calling it again.

| Check | Latest fresh run, 2026-10-22 23:00 (`eval_runs/2026-10-22_230015`) | Latest saved scoring, 2026-10-23 00:17 (`eval_runs/2026-10-23_001734`) | Target |
|---|---|---|---|
| Category (reason) accuracy | 98% (59 of 60) | 98% (59 of 60) | at least 85% |
| Activation vs decline confusions | 0 | 0 | as few as possible |
| Personal data found in what was sent | 0 | 0 | 0 |
| Risk cases not sent to a person | 0 | 0 | 0 |
| Leading P agreement (tracked, not gated) | 57% (34 of 60) | 52% (31 of 60) | none |
| Human-human agreement | Not measured | Not measured | needed for Gate 0 |
| Gate 0 offline checks | PASS | PASS | |

- **Routes on the 60 cases:** auto-tag 40, review 11, human-led 6, emerging 3.
- **The one miss:** C041, expected unknown, got invoice reconciliation at 0.80 confidence. It went to review, so no one acted on the wrong label.
- **History:** the first run, 2026-10-22 21:39, failed with 4 lockout cases not sent to a person. The risk words were fixed and every run since has passed.
- **Caveat:** these are in-sample numbers on AI-assisted, reviewed labels, not real-world accuracy.

## 9. Changes vs the original plan (v3), and why

| Plan | Built | Why |
|---|---|---|
| Anthropic API with a key in `.env` | Claude Code command line on the existing subscription; the API remains a config switch | The owner's decision for the MVP: no separate key or billing needed. |
| A page to paste one case and run it live, plus a summary | A bulk upload analyzed in three steps, plus a separate plain-language "How it works" page | The goal is analysis of a whole batch for a VOC proposal, not case-by-case handling. The panel is non-technical. |
| Review queue for mid confidence or activation vs decline ambiguity | Also repeat contacts (switchable) | A repeat means the first contact failed; the owner chose to send them to review. |
| Leading P metric cut | Tracked, not gated | The tool supports decisions; owners are proposals a person confirms. |
| Risk words matched as text | Whole-word matching, accents ignored, lockout phrases added | Eval run 1 missed 4 lockouts, and "robaron" matched inside "aprobaron". |
| Cases processed in order | 2 masking workers and 6 parallel model calls, with progress bars and live commentary | The sequential run took 4 minutes 25 seconds; it now takes about 1 minute 45 seconds. |
| No timeout specified | 30 second model timeout | Offline, the call took 90 seconds to fail. |
| Rehearsal: switch Wi-Fi off | Simulated outage | Switching Wi-Fi off needs admin rights and would cut the server's only connection. |
| Open the page locally on port 8000 | SSH tunnel from the MBP on port 47321 | The server is headless; ports 8000 and 8765 are taken on the MBP. |
| Summary of counts | An executive summary in Step 3: headline numbers, findings written by fixed rules, a table per category, root cause overall, cases by market | Leaders need an at-a-glance view before the detail. |
| Name: Signal-to-Fix | UpstreamW | The owner's choice. The folder and GitHub repo keep the old name so commands do not change. |

## 10. Three screens worth showing

| Screen | What to show | What it proves |
|---|---|---|
| **Step 1: Protect personal data** | The before and after table, with hidden items highlighted, and the "0 personal data items sent" number | Privacy is designed in: personal data is removed on this machine, and a final check stops any case that still has some. |
| **Step 2: Sort each case** | Click a risk case (human-led) and a repeat contact (review) to open the reason, quotes and proposed owner. Optional live change: raise `auto_tag_min_confidence` to 0.90 in `config.yaml` and run a small file again | Every case gets a consistent category and root cause with evidence. Sensitive and unsure cases go to a person. The rules are plain settings a business owner can change in the room. |
| **Step 3: Summary at a glance** | The key findings, the spike alert (account access 27.5x its usual share in the last days), and the summary by category with customer quotes | The output is something leaders can act on: where volume sits, what is behind it, what is changing, in customers' own words. The "How far to trust it" numbers sit right below. |
