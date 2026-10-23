# UpstreamW v0.1 (formerly Signal-to-Fix): what is built

Version 0.1, 2026-10-23. Written from the code, `config.yaml`, `README.md` and `eval_runs/` in this repo. All data is synthetic (LumenPay business case, Deliverable 4). Private repo: https://github.com/daniel-wing/signal-to-fix

## 1. In one paragraph

UpstreamW turns a batch of closed customer support conversations into a picture leaders can act on. A Customer Experience or Operations lead uploads a file of conversations to a web page, protected by a password. The tool hides personal data on the local machine, has an AI model sort every case into a fixed customer pain category and score its root cause across the 4Ps (People, Process, Policy, Product), and sends risky or unclear cases to a person. It then summarizes what customers are saying, with headline numbers, key findings, spike alerts and customer quotes.

It solves a real gap: today, contact reasons are tagged by hand, inconsistently, and too late to steer fixes upstream. UpstreamW gives that view in about two minutes for 60 cases, and no personal data leaves the machine. It supports human decisions; it does not write recommendations or reply to customers.

## 2. From a closed case to the final output

| # | Step | Where it runs | Model |
|---|---|---|---|
| 1 | **Upload.** A tester logs in with the shared password and uploads a JSON file of cases. Each case needs a `text`; `id`, `market`, `channel` and `date` are used when present. | Local | None |
| 2 | **Mask by pattern.** Emails, phone numbers, card numbers and card endings, account numbers, tax IDs (RFC, NIT, CPF, CNPJ), amounts and other long ID numbers become labels such as `[CARD_LAST4_1]`. | Local | None |
| 3 | **Mask names and addresses.** A small model on the same machine lists names and addresses; Python replaces them with labels such as `[NAME_1]`. The label-to-value map is saved in `vault.json`. | Local | `qwen2.5:3b` via Ollama |
| 4 | **Leak check.** Before anything is sent, the patterns run again and every original value in the map is searched for. If anything is found, or masking failed, nothing is sent and the case goes to a person. | Local | None |
| 5 | **Classify.** Only the masked conversation, plus the instructions in `prompt.txt`, is sent out. See below for what comes back. | **External** | `claude-sonnet-5-5` (effort low), through the Claude Code command line on this machine |
| 6 | **Route.** Fixed rules from `config.yaml` decide the next step (section 5) and propose an owner from the leading P. | Local | None |
| 7 | **Spike alert.** For each category, the share of cases in the last 3 days is compared with the 27 days before. Sensitive cases are tracked separately. | Local | None |
| 8 | **Show.** The page fills in three steps as the work runs. See below. | Local | None |

**What the model returns in step 5:**
- the pain category and a detail (sub-reason)
- a possible mix-up with another category
- a 0 to 1 score for each of the 4Ps, with a supporting quote
- defect and repeat-contact flags
- its confidence and a one-sentence reason

Invalid replies get one retry. A failure, or a 30 second timeout, sends the case to a person. Six cases are sent at a time.

**What the page shows in step 8:**
- **While running:** progress bars, live commentary and a Stop analysis button.
- **Step 1:** before and after masking.
- **Step 2:** every case sorted.
- **Step 3:** the summary at a glance, every case that fits no category, then the deeper analysis.

The result is saved, and the finished progress stays on screen with a Done line and the time taken.

Measured on the 60 test cases: about 1 minute 45 seconds in total (masking about 1 minute, classification about 45 seconds).

## 3. Map of the flow and the files

```
  Tester's browser (no Tailscale needed)
        |  https://zbook-server.tail8311fb.ts.net:10000  (Tailscale Funnel, password)
        v
  [ run.py page server, 127.0.0.1:8000, running in tmux on the zbook ]
        |  serves app.html and how.html, takes the upload
  ON THIS MACHINE
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
| `run.py` | Setup check; whole pipeline (all cases or one); page server with password, upload, progress, stop and saved state | `config.yaml`, `.env` (password), `cases_raw.json` or the upload, `app.html`, `how.html` | `results/latest.json` |
| `mask.py` | Masking by pattern and by local model, leak check, saving the label map | Case text, Ollama | `vault.json` |
| `classify.py` | Calls the external model (Claude Code, or the Anthropic API when switched), checks the reply, one retry | `prompt.txt`, `config.yaml` (`llm`), masked text | Nothing on disk; returns the result and exactly what was sent |
| `route.py` | Routing rules and proposed owners | `config.yaml` (`routing`) | Nothing |
| `alerts.py` | Spike alert per category, plus sensitive cases | `config.yaml` (`alerts`), results | Nothing |
| `run_eval.py` | Scores results against the expected labels; fresh run or `--saved` | `cases_raw.json`, `results/latest.json`, `config.yaml`, `prompt.txt` | `eval_runs/<timestamp>.md` and `.json` |
| `common.py` | Shared helpers: config, `.env`, calls to Ollama (no proxy), text normalizing | `config.yaml`, `.env` | Nothing |
| `config.yaml` | Every setting a person may change live: models, thresholds, risk words, alert rule, paths | | |
| `prompt.txt` | The instructions sent to the external model: categories, activation vs decline rule, sub-reasons, 4P definitions, output format | | |
| `.env` | Shared tester password (`UPSTREAMW_PASSWORD`); git-ignored, never committed | | |
| `app.html` | The page: upload, progress and stop, three steps, how far to trust it, footer with version and repo link | `/api/state`, `/api/job` | |
| `how.html` | Plain-language explanation with a diagram, for non-technical readers | | |
| `cases_raw.json` | 60 synthetic Spanish cases with planted personal data and expected labels | | |
| `README.md`, `AI_RECORD.md`, `TODO.md`, `demo_cases.md` | Setup and use; what was delegated to AI and how it was checked; later work; paste-ready demo cases | | |
| `eval_runs/` | Every evaluation, with the config and prompt used, committed | | |

## 4. Data boundaries

**Never leaves the machine for an AI service**
- The original conversation text.
- `vault.json`, the map from each label back to the real value (git-ignored).
- `results/latest.json`, which holds the originals for the before and after view (git-ignored).
- Everything sent to the masking model: Ollama runs on this machine, called without any proxy.

**Sent to an AI service, per case**
- The masked conversation, wrapped in `<conversation>` tags, plus the text of `prompt.txt`.
- It goes to Anthropic through the Claude Code command line, with no tools, no saved settings, no extra connectors and no saved session.
- Exactly what was sent is kept with each result.

**Shown to logged-in testers**
- Through the Funnel link, logged-in testers see the page. That includes Step 1's original text next to the masked text. This is acceptable only because every case is synthetic. Real data would need per-user accounts and must not show originals.

**How the leak check blocks a send**
1. After masking, the labels are removed and every pattern runs again on what is left.
2. Every original value in the label map is searched for in the text, ignoring case and accents.
3. If either finds anything, or masking failed, the case is marked "Stopped" and the model is never called. The case goes to a person ("Masking problem, nothing sent").

**Limit:** the check catches known formats and values the masker already found. A name the local model missed has no fixed shape, so the check cannot see it. Production needs the Gate 0 checks and a Legal review.

## 5. Routing rules as configured

Applied in this order; the first match wins.

| Order | Condition | Next step |
|---|---|---|
| 1 | Masking problem or leak found | Human-led (nothing sent) |
| 2 | A risk word appears, matched as whole words, ignoring case and accents (see the list below) | Human-led |
| 3 | The model did not answer, or gave an invalid reply twice | Human-led ("Nothing auto-tagged") |
| 4 | Category is unknown | Emerging (a person names it) |
| 5 | Confidence below **0.60** | Human-led |
| 6 | Card activation vs payment declined is ambiguous | Review queue |
| 7 | Repeat contact (`repeat_to_review: true`) | Review queue |
| 8 | Confidence below **0.85** | Review queue |
| 9 | Everything else | Auto-tag |

**Risk words:** 35 words and phrases covering fraud, unrecognized charges, account takeover, account lockout (in Spanish and Portuguese) and legal threats.

**Proposed owner:** the leading P always gets one, plus any other P scoring above **0.50**.

| P | Owner |
|---|---|
| People | Team lead: coaching |
| Process | Process owner |
| Policy | Policy: cost-benefit review |
| Product | A bug draft if it is a defect, otherwise a user-story candidate for the PM weekly review |

**Spike alert:** last **3** days vs the **27** before. It fires when a category's share is at least **2x** and it has at least **3** cases.

**Where to change them:** all in `config.yaml`, read again on every analysis, so no restart is needed.
- `routing`: `auto_tag_min_confidence`, `review_min_confidence`, `secondary_owner_min_score`, `repeat_to_review`, `risk_words`.
- `alerts`: `recent_days`, `baseline_days`, `min_ratio`, `min_recent_cases`.
- Categories and 4P definitions live in `prompt.txt`.

## 6. How to run it

**For testers (no Tailscale needed):**
1. Open https://zbook-server.tail8311fb.ts.net:10000.
2. Log in with any user name and the shared password.

**Start the page on the zbook so it keeps running after SSH closes.** From the Mac:

```bash
ssh wing@zbook-server "tmux new -d -s upstreamw 'cd ~/projects/signal-to-fix && .venv/bin/python run.py serve'"
```

**Publish it, if Funnel is not already on:**

```bash
ssh wing@zbook-server 'tailscale funnel --bg --https=10000 http://127.0.0.1:8000'
```

**Owner access from the Mac through a tunnel.** Then open http://localhost:47321:

```bash
ssh -N -L 47321:localhost:8000 wing@zbook-server
```

**See the password:**

```bash
ssh wing@zbook-server 'grep UPSTREAMW_PASSWORD ~/projects/signal-to-fix/.env'
```

**Take it all down:**

```bash
ssh wing@zbook-server 'tailscale funnel --https=10000 off; tmux kill-session -t upstreamw'
```

**Ports:**
- The page server listens on 127.0.0.1:8000.
- Funnel uses 10000, because 443 and 8443 are taken by other services on the zbook.
- 47321 is the Mac side of the tunnel, because 8000 and 8765 are taken on the Mac.

**Needs on the server:** Ollama with `qwen2.5:3b`, and Claude Code logged in.

**Command-line tools:**
- `python3 run.py check`
- `python3 run.py --only C001`
- `python3 run_eval.py`
- `python3 run_eval.py --saved`

## 7. Current status (v0.1)

**Works end to end, tested**
- The pipeline on 60 cases: upload, local masking, leak check, classification, routing, spike alert and the three-step page.
- Page behavior:
  - A new visit starts clean, with "Open the last analysis".
  - "New analysis" clears the page.
  - While running: progress bars, live commentary and Stop analysis. Nothing from a stopped run is saved.
  - When finished: the filled bars stay with a Done line and the time taken.
  - Reloading keeps your place.
  - "How it works" opens in a new tab.
- Step 3:
  - the summary at a glance: headline numbers, key findings written by fixed rules, the table per category, root cause overall, cases by market
  - the spike alert
  - every case that fits no category, in full
  - the deeper analysis
- Public test access through Tailscale Funnel with a shared password. Checked from a device without Tailscale on 2026-10-23.
- Evaluation that writes a committed report.
- Live edits to `config.yaml` and `prompt.txt` apply on the next analysis.
- A broken model call sends every case to a person.

**Partial**
- **Offline behavior:** tested by sending the model call to a dead proxy, not by switching Wi-Fi off. Switching it off needs admin rights and would cut the server's only connection.
- **Anthropic API backend:** coded and selectable with `llm.backend: api`, but never run; every recorded run used Claude Code.
- **4P root cause:** the leading P matches the expected label 52% to 57% of the time, mostly Process vs Product. It is tracked, not gated, and owners are proposals a person confirms.
- **Repeat contacts:** the case file still labels C008 and C047 as auto-tag, while the rule sends them to review.
- **Brazil:** cases are in Spanish, with some Portuguese lockout phrases in the risk list.

**Missing**
- A fresh held-out test set: masking and risk words were tuned on the same 60 cases they are scored on.
- Human-human agreement, so the full Gate 0 cannot pass yet.
- A model-side risk flag behind the word list.
- Governance for adding categories.
- Portuguese conversations.
- A screen for working the review queue.
- History of past analyses: only the latest is kept.
- Per-user accounts.
- Restarting by itself after a reboot.

**Known issues**
- **One shared app.** All testers see the same last analysis, and only one analysis runs at a time. A server restart forgets a run in progress.
- **Reboots.** After a reboot of the zbook, the page must be started again with the tmux command. The Funnel setting stays.
- **Funnel's public name.** The name did not appear on the public internet for over 10 minutes. Switching Funnel off and on fixed it within 2 minutes. Testers should not use the link right after a restart until it has been checked.
- **Label map overwrites.** `vault.json` is keyed by case id. Two uploads that reuse an id (or files without ids, which get R001, R002 and so on) overwrite each other's map. There is no visible effect today.
- **Subscription terms.** The analyses run on the owner's Claude subscription. Check its terms before wider use; the Anthropic API is a one-line switch.
- **Restarts for code changes.** Changes to Python files need a server restart; page and config changes do not.

## 8. Latest evaluation numbers

No evaluation has run since 2026-10-23 00:17. The two most recent are below:
- **Fresh run:** the latest run that called the model.
- **Saved scoring:** a re-score of the page's analysis at that time, without calling the model again.

| Check | Fresh run, 2026-10-22 23:00 (`eval_runs/2026-10-22_230015`) | Saved scoring, 2026-10-23 00:17 (`eval_runs/2026-10-23_001734`) | Target |
|---|---|---|---|
| Category (reason) accuracy | 98% (59 of 60) | 98% (59 of 60) | at least 85% |
| Activation vs decline confusions | 0 | 0 | as few as possible |
| Personal data found in what was sent | 0 | 0 | 0 |
| Risk cases not sent to a person | 0 | 0 | 0 |
| Leading P agreement (tracked, not gated) | 57% (34 of 60) | 52% (31 of 60) | none |
| Human-human agreement | Not measured | Not measured | needed for Gate 0 |
| Gate 0 offline checks | PASS | PASS | |

**Routes on the 60 cases:**

| Route | Cases |
|---|---|
| Auto-tag | 40 |
| Review | 11 |
| Human-led | 6 |
| Emerging | 3 |

**The one miss:** C041. Expected unknown, it came back as invoice reconciliation at 0.80 confidence, so it went to review and no one acted on the wrong label.

**History:** the first run (2026-10-22 21:39) failed: 4 lockout cases were not sent to a person. The risk words were fixed, and every run since has passed.

**Caveat:** these are in-sample numbers on AI-assisted, reviewed labels, not real-world accuracy.

## 9. Changes vs the original plan (v3), and why

| Plan | v0.1 | Why |
|---|---|---|
| Anthropic API with a key in `.env` | Claude Code command line on the existing subscription; the API remains a config switch | The owner's decision for the MVP: no separate key or billing. |
| A page to paste one case and run it live, plus a summary | A bulk upload in three steps, with a plain-language "How it works" page | The goal is analysis of a whole batch for a VOC proposal, not case-by-case handling. The panel is non-technical. |
| A summary of counts | An executive summary in Step 3, plus every case that fits no category in full | Leaders need an at-a-glance view; a person must read the new kinds of problems to name them. |
| Review queue for mid confidence or activation vs decline ambiguity | Also repeat contacts (switchable) | A repeat means the first contact failed; the owner chose to review them. |
| Leading P metric cut | Tracked, not gated | The tool supports decisions; owners are proposals a person confirms. |
| Risk words matched as text | Whole words, accents ignored, lockout phrases added | Eval run 1 missed 4 lockouts, and "robaron" matched inside "aprobaron". |
| Cases processed in order | 2 masking workers and 6 parallel model calls; progress, live commentary, Stop | The sequential run took 4 minutes 25 seconds, now about 1 minute 45 seconds. A long run needs to be visible and stoppable. |
| No timeout specified | 30 second model timeout | Offline, the call took 90 seconds to fail. |
| Rehearsal: switch Wi-Fi off | Simulated outage | Switching Wi-Fi off needs admin rights and would cut the server's only connection. |
| Local page on port 8000, no public hosting | Tailscale Funnel on port 10000 with a shared password; owner tunnel on 47321 | Testers must reach it without installing Tailscale. The password is needed because the link is public and analyses run on the owner's subscription. |
| Name: Signal-to-Fix | UpstreamW v0.1 | The owner's choice. The folder and repo keep the old name so commands do not change. |

## 10. Three screens worth showing

| Screen | What to show | What it proves |
|---|---|---|
| **Step 1: Protect personal data** | The before and after table with hidden items highlighted, and "0 personal data items sent" | Privacy is designed in. Personal data is removed on this machine, and a final check stops any case that still has some. |
| **Step 2: Sort each case** | Open a risk case (human-led) and a repeat contact (review) to show the reason, quotes and proposed owner. Optional live change: raise `auto_tag_min_confidence` to 0.90 in `config.yaml` and run a small file again. | Every case gets a consistent category and root cause with evidence, and sensitive or unsure cases go to a person. The rules are plain settings a business owner can change in the room. |
| **Step 3: Summary at a glance** | The key findings, the spike alert, the summary by category with customer quotes, and the cases that fit no category | The output is something leaders can act on: where volume sits, what is behind it, what is changing, and what is new, in customers' own words. The trust numbers sit right below. |
