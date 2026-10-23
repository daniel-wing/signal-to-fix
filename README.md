# UpstreamW

A small working prototype of one internal AI workflow for LumenPay (a synthetic company; business case Deliverable 4). It turns closed support conversations into classified, routed signals for Operations and Product, without sending personal data to the cloud.

It does not make business recommendations. It gives the people who review cases faster answers, actionable items and specific cases with context, so they can write the VOC proposal from this and from their own CX work.

**All data is synthetic.** No real customer, company or system is involved.

## What it does

Trigger: a closed support conversation (from the case file, or pasted into the page).

1. **Mask on this machine.** Regular expressions replace emails, phones, card numbers, "termina en 1234", account IDs, RFC, NIT, CPF, CNPJ and amounts. A small local model (`qwen2.5:3b` via Ollama) finds names and addresses; Python replaces them. Tokens look like `[NAME_1]`; the token map is kept in `vault.json`, which never leaves the machine.
2. **Leak check.** Before any call to the cloud model, the regular expressions run again and every original value from the token map is searched for. If anything remains, the call is blocked and the case goes to a human.
3. **Classify.** Only the masked text goes to the cloud model (`claude-sonnet-5-5`), called through the Claude Code CLI installed on this machine (`claude -p` with our own system prompt, no tools, no settings, no saved session). The Anthropic API is a config switch away (`llm.backend: api`). It returns a contact reason, sub-reason, possible ambiguity, a 4P root-cause score (People, Process, Policy, Product) with quotes, defect and repeat flags, a self-reported confidence and a one-sentence rationale. Invalid JSON gets one retry, then a human.
4. **Route** (in this order):
   1. Masking problem or a risk word (fraud, unrecognized charge, account takeover, lockout, legal): **human-led**.
   2. Reason unknown: **emerging** list, for a human to name. Never forced into "other".
   3. Confidence below 0.60: **human-led**.
   4. Confidence 0.60 to below 0.85, activation vs decline ambiguity, or a repeat contact: **review queue**.
   5. Confidence 0.85 and above: **auto-tag**.

   Owner by the top P, plus any other P above 0.50: People = team lead coaching; Process = process owner; Policy = cost-benefit review; Product = bug draft if it is a defect, otherwise a user-story candidate for the PM weekly review.
5. **Spike alert.** Per reason, the share of cases in the last 3 days vs the 27 days before. Alert at 2x or more with at least 3 cases. Risk cases are tracked separately.

The page is a bulk analytics tool: upload a JSON file of cases and it shows three steps.

1. **Protect personal data:** every case before and after, with what was hidden highlighted, and counts by type.
2. **Sort each case:** customer pain category, the 4P shares (scores normalized to 100%), confidence and next step for every row.
3. **What customers are telling us:** the main pain categories, the 4P breakdown per category, spike alerts, and per-category detail with customer quotes.

A plain-language explanation for non-technical readers is at `/how`. A 60-case upload takes about 1 minute 45 seconds (masking about 1 minute, classification in parallel about 45 seconds). "Show the last analysis" opens the previous result instantly, and `/?last` opens it directly.

## Setup

Needs Python 3.10+, [Ollama](https://ollama.com) and Claude Code logged in on this machine (or an Anthropic API key with `llm.backend: api`).

```bash
git clone https://github.com/daniel-wing/signal-to-fix.git && cd signal-to-fix
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
ollama pull qwen2.5:3b
# only for llm.backend: api -> cp .env.example .env and put the key in .env
python3 run.py check        # config, Ollama, model access, one tiny model call
```

## The one command

```bash
python3 run.py serve        # opens http://localhost:8000
```

On a headless server (for example the zbook, reached by SSH from a laptop), run this on the laptop. It starts the page on the server and tunnels it; Ctrl+C stops both:

```bash
ssh -t -L 47321:localhost:8000 wing@zbook-server 'cd ~/projects/signal-to-fix && .venv/bin/python run.py serve'
# then open http://localhost:47321 on the laptop (47321 on the laptop, 8000 on the server)
```

Other commands:

| Command | What it does |
|---|---|
| `python3 run.py` | Run every case, save `results/latest.json` |
| `python3 run.py --only C001` | Run one case and print every stage |
| `python3 run.py serve --port 8010` | The page on another port |
| `python3 mask.py --all` | Masking only: planted PII still visible per case (target 0) |
| `python3 alerts.py` | Spike alert table for the saved run |
| `python3 run_eval.py` | Real-model evaluation, saved to `eval_runs/` |
| `python3 run_eval.py --saved` | Score the saved run without calling the model |

On the page, upload `cases_raw.json` (or any file in the same shape). Paste-ready single cases for `run.py --only` style demos are in `demo_cases.md`. Open questions and later work are in `TODO.md`.

## Publishing for a few test users (Tailscale Funnel)

Testers need only a link and a password, not Tailscale.

1. Put a shared password in `.env` (git-ignored): `UPSTREAMW_PASSWORD=...`. With it set, the browser asks for a login; any user name works. Without it the page is open to anyone with the link.
2. Keep the page running after SSH closes:
   `tmux new -d -s upstreamw 'cd ~/projects/signal-to-fix && .venv/bin/python run.py serve'`
3. Publish it: `tailscale funnel --bg --https=10000 http://127.0.0.1:8000`. The link is `https://zbook-server.tail8311fb.ts.net:10000`. Port 10000 because 443 and 8443 are taken on this machine. The first time, Tailscale may print a link to allow Funnel for this machine in the admin console.
4. Take it down: `tailscale funnel --https=10000 off`, and stop the page with `tmux kill-session -t upstreamw`.

All testers share one app: the same last analysis, one analysis at a time, on this machine's Claude Code login.

## Changing things live

`config.yaml` and `prompt.txt` are read again on every run, including every "Run live" click on the page. No restart needed.

- **Threshold:** in `config.yaml`, change `auto_tag_min_confidence: 0.85` to `0.90`. Run a case again.
- **Risk word:** add a line under `risk_words`. Matching ignores case and accents.
- **Prompt:** edit `prompt.txt`. The exact text sent is saved with each result and with each eval run.
- **Alert rule:** `alerts` section (window lengths, ratio, minimum cases).
- **Ollama on another machine:** `ollama.url`.
- **Break the model call on purpose:** set `llm.cli: claude-broken`; the case shows "Classification unavailable. Nothing auto-tagged." and goes to a human.
- **No network:** masking still runs locally; classification fails safe to a human after `llm.timeout_seconds` (30s); the saved run stays viewable on the page. Tested by simulation (the model call routed to a dead proxy), not by switching Wi-Fi off.
- **Repeat contacts:** `repeat_to_review: true` sends them to the review queue. In production you would sample them: about 27% of cases are repeats, more than leaders can review.

## Privacy claim

Masking runs on this machine and the call to the cloud model is blocked if detectable PII remains. Tested on synthetic cases only. Like any detector it can miss an unusual name or address, which is why production needs Gate 0 and a Legal review.

Notes: the evidence pack says classification and routing on pseudonymized fields are already approved; generative responses using card status, phone or transaction details are not, and this prototype does not generate any customer response. `vault.json`, `.env` and `results/` are git-ignored.

## Evaluation

Latest result (eval run 5, 60 cases): reason accuracy 98% (59/60), 0 activation vs decline confusions, 0 PII in what was sent, 0 risk cases missed. Top P agreement 57% (34/60) is tracked but not gated: owners are proposals a person confirms. Human-human agreement is not measured yet. The first run missed 4 lockout cases; see `AI_RECORD.md`. Masking and risk words were tuned on these same 60 cases, so these are in-sample numbers; a fresh held-out set is the next check.

`run_eval.py` compares the model with the expected labels in the case file and reports reason accuracy, activation vs decline confusions, PII found in what was sent (must be 0) and risk cases not sent to a human (must be 0). Each run is saved as `eval_runs/<timestamp>.md` with the config and prompt used, and committed.

The cases and labels were written with AI help and reviewed, so the eval measures agreement with reviewed labels, not real-world accuracy.

## Assumptions

| # | Assumption |
|---|---|
| A1 | Classification model: `claude-sonnet-5-5` via the Claude Code CLI on a subscription login (demo only; production would use the API under approved processing terms). |
| A2 | Masking model: `qwen2.5:3b` via Ollama, URL in config. |
| A3 | Built and presented on one machine; a second machine is a backup, not rehearsed. |
| A4 | Page in English, case text in Spanish. Brazil cases are in Spanish for this demo only; Portuguese is a next step. |
| A5 | Alert: last 3 days vs the 27 days before, 2x multiple, minimum 3 cases. |
| A6 | Thresholds 0.60 and 0.85 are demo policy, not validated. Confidence is self-reported by the model. |
| A7 | Accuracy gate 85%. The pack's 82% tag accuracy comes from only 50 cases (95% CI roughly 69% to 91%). |
| A8 | 4P definitions in `prompt.txt` are this prototype's working definitions, not from the evidence pack. |

## Rollout gates

- **Gate 0, offline:** PII leaks 0; risk cases to a human 100%; reason accuracy at least 85% and at least equal to human-human agreement (not yet measured).
- **Gate 1, shadow for 2 weeks:** the model labels in parallel, nothing acts on it; blind double review by agents, senior tiebreak on disagreements.
- **Gate 2, assisted:** one market and one reason; agents confirm the suggested tag and route.
- **Rollback** on an accuracy drop below the gate, any PII leak, or the review queue growing beyond what leads can clear.

## Failure modes

| Failure | What happens |
|---|---|
| Incomplete masking (an unusual name or address) | Leak check catches known formats only; Gate 0 and Legal review before production. |
| Confident wrong label | Eval tracks it; shadow mode with double review before anything is auto-tagged. |
| Activation vs decline confusion | Explicit rule in the prompt; ambiguity goes to the review queue; counted in every eval. |
| Informal WhatsApp language | Not yet measured separately; add WhatsApp-heavy cases to the eval. |
| Model or network outage | "Classification unavailable. Nothing auto-tagged." Case goes to a human. |
| Risk phrased in a way the word list does not cover | Seen in eval run 1 (4 lockouts missed); word list extended; production needs a model-side risk flag as a second net. |
| Drift after a product release | Spike alert per reason; re-run the eval after each release. |

## Out of scope

Portuguese, a review UI for the queues, public hosting, account context data (needs Legal), real-time processing.

## Files

| File | Purpose |
|---|---|
| `config.yaml` | Thresholds, risk words, alert rule, models, paths |
| `prompt.txt` | Classification prompt |
| `mask.py` | Local masking and leak check |
| `classify.py` | Model call (Claude Code CLI or API), JSON validation, one retry |
| `route.py` | Routing rules and owners |
| `alerts.py` | Spike alert |
| `run.py` | Setup check, pipeline, page server |
| `run_eval.py` | Evaluation |
| `common.py` | Config, `.env`, Ollama helpers |
| `app.html` | The page (upload, steps 1 to 3, trust) |
| `how.html` | How it works, in plain language |
| `TODO.md` | Later work, including category governance |
| `AI_RECORD.md` | What was delegated to AI and how it was checked |
| `demo_cases.md` | Three paste-ready cases for the live demo |
| `eval_runs/` | Every eval run, with the config and prompt used |
