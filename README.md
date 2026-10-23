# Signal-to-Fix

A small working prototype of one internal AI workflow for LumenPay (a synthetic company; business case Deliverable 4). It turns closed support conversations into classified, routed signals for Operations and Product, without sending personal data to the cloud.

**All data is synthetic.** No real customer, company or system is involved.

## What it does

Trigger: a closed support conversation (from the case file, or pasted into the page).

1. **Mask on this machine.** Regular expressions replace emails, phones, card numbers, "termina en 1234", account IDs, RFC, NIT, CPF, CNPJ and amounts. A small local model (`qwen2.5:3b` via Ollama) finds names and addresses; Python replaces them. Tokens look like `[NAME_1]`; the token map is kept in `vault.json`, which never leaves the machine.
2. **Leak check.** Before any API call, the regular expressions run again and every original value from the token map is searched for. If anything remains, the call is blocked and the case goes to a human.
3. **Classify.** Only the masked text goes to the cloud model (`claude-sonnet-5-5`). It returns a contact reason, sub-reason, possible ambiguity, a 4P root-cause score (People, Process, Policy, Product) with quotes, defect and repeat flags, a self-reported confidence and a one-sentence rationale. Invalid JSON gets one retry, then a human.
4. **Route** (in this order):
   1. Masking problem or a risk word (fraud, unrecognized charge, account takeover, lockout, legal): **human-led**.
   2. Reason unknown: **emerging** list, for a human to name. Never forced into "other".
   3. Confidence below 0.60: **human-led**.
   4. Confidence 0.60 to below 0.85, or activation vs decline ambiguity: **review queue**.
   5. Confidence 0.85 and above: **auto-tag**.

   Owner by the top P, plus any other P above 0.50: People = team lead coaching; Process = process owner; Policy = cost-benefit review; Product = bug draft if it is a defect, otherwise a user-story candidate for the PM weekly review.
5. **Spike alert.** Per reason, the share of cases in the last 3 days vs the 27 days before. Alert at 2x or more with at least 3 cases. Risk cases are tracked separately.

The page shows every step side by side: raw, masked, exactly what was sent, then the classification, 4P bars, route and owner.

## Setup

Needs Python 3.10+, [Ollama](https://ollama.com) and an Anthropic API key.

```bash
git clone https://github.com/daniel-wing/signal-to-fix.git && cd signal-to-fix
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
ollama pull qwen2.5:3b
cp .env.example .env        # then put your key in .env
# put cases_raw.json in this folder
python3 run.py check        # config, Ollama, key present (yes/no), one tiny API call
```

## The one command

```bash
python3 run.py serve        # opens http://localhost:8000
```

Other commands:

| Command | What it does |
|---|---|
| `python3 run.py` | Run every case, save `results/latest.json` |
| `python3 run.py --only C001` | Run one case and print every stage |
| `python3 mask.py --all` | Masking only: planted PII still visible per case (target 0) |
| `python3 alerts.py` | Spike alert table for the saved run |
| `python3 run_eval.py` | Real-model evaluation, saved to `eval_runs/` |
| `python3 run_eval.py --saved` | Score the saved run without calling the API |

## Changing things live

`config.yaml` and `prompt.txt` are read again on every run, including every "Run live" click on the page. No restart needed.

- **Threshold:** in `config.yaml`, change `auto_tag_min_confidence: 0.85` to `0.90`. Run a case again.
- **Risk word:** add a line under `risk_words`. Matching ignores case and accents.
- **Prompt:** edit `prompt.txt`. The exact text sent is saved with each result and with each eval run.
- **Alert rule:** `alerts` section (window lengths, ratio, minimum cases).
- **Ollama on another machine:** `ollama.url`.

## Privacy claim

Masking runs on this machine and the API call is blocked if detectable PII remains. Tested on synthetic cases only. Like any detector it can miss an unusual name or address, which is why production needs Gate 0 and a Legal review.

Notes: the evidence pack says classification and routing on pseudonymized fields are already approved; generative responses using card status, phone or transaction details are not, and this prototype does not generate any customer response. `vault.json`, `.env` and `results/` are git-ignored.

## Evaluation

`run_eval.py` compares the model with the expected labels in the case file and reports reason accuracy, activation vs decline confusions, PII found in what was sent (must be 0) and risk cases not sent to a human (must be 0). Each run is saved as `eval_runs/<timestamp>.md` with the config and prompt used, and committed.

The cases and labels were written with AI help and reviewed, so the eval measures agreement with reviewed labels, not real-world accuracy.

## Assumptions

| # | Assumption |
|---|---|
| A1 | Classification model: Anthropic API, `claude-sonnet-5-5`. |
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
| API outage | "Classification unavailable. Nothing auto-tagged." Case goes to a human. |
| Drift after a product release | Spike alert per reason; re-run the eval after each release. |

## Out of scope

Portuguese, a review UI for the queues, public hosting, account context data (needs Legal), real-time processing.

## Files

| File | Purpose |
|---|---|
| `config.yaml` | Thresholds, risk words, alert rule, models, paths |
| `prompt.txt` | Classification prompt |
| `mask.py` | Local masking and leak check |
| `classify.py` | API call, JSON validation, one retry |
| `route.py` | Routing rules and owners |
| `alerts.py` | Spike alert |
| `run.py` | Setup check, pipeline, page server |
| `run_eval.py` | Evaluation |
| `common.py` | Config, `.env`, Ollama helpers |
| `app.html` | The page |
| `AI_RECORD.md` | What was delegated to AI and how it was checked |
