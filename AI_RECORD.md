# AI record

How AI was used to build and check this prototype. All data is synthetic.

## What was delegated to AI

| Work | Tool | How it was checked |
|---|---|---|
| Implementation plan (v1 to v3, cut to about 5 hours) | Claude | Read and cut by hand against the case brief and the evidence pack (to confirm) |
| The 60 synthetic cases and their expected labels (`cases_raw.json`) | Claude, in a separate session | Reviewed by hand (to confirm); reasons and sub-reasons follow the pack's tag table and journey audits, including activation vs decline traps and a late-month lockout spike |
| Code: masking, classifier, routing, alert, page, eval | Claude Code | Each step run and checked before committing (see git history); results below |
| Classification of each case | `claude-sonnet-5-5` via Claude Code | The eval below |
| Name and address detection | `qwen2.5:3b`, local | `mask.py --all` against the planted PII in every case |

**The cases and labels were written with AI help.** The eval therefore measures agreement with reviewed labels, not real-world accuracy.

## Checked against the evidence pack

- Contact reasons and sub-reasons match the pack's tag table and the three journey audits (activation: processor delay, status refresh, wrong phone; decline: hidden limits, admin category blocks, processor timeouts; invoice: tax fields, timing, export format).
- The activation vs decline rule in `prompt.txt` targets the confusion the pack reports (6 of 50 audited cases).
- Privacy follows the pack: classification and routing on pseudonymized fields are approved; no customer-facing generation, no raw text to the cloud.
- Thresholds (0.60, 0.85), the alert rule and the 4P definitions are labeled assumptions, not pack facts.

## Weak or failed attempts, and what changed

1. **Masking, first pass on the 60 cases: 9 planted PII values still visible.** Card endings written as bare digits ("cartao 5561", a reply of just "7716") and five names the 3B model missed. The leak check did block 2 other cases where a card ending reappeared. Fix: a bare 4-digit rule (years excluded) and name cues ("Hola Débora Vieira", "Cliente: Larissa Duarte, [ACCOUNT_1]"). Result: 0 visible, 0 blocked, and every masked value is a planted value (no over-masking).
2. **Eval run 1 failed: 4 of 6 risk cases (account lockouts) were auto-tagged.** The risk words listed "cuenta bloqueada" but customers wrote "cuenta está bloqueada", "se bloqueó", "sigue bloqueada", "conta ta bloqueada". Matching was also by substring, so "robaron" fired inside "aprobaron" (right result, wrong reason). Fix: whole-word matching and the lockout phrasings in Spanish and WhatsApp Portuguese. Eval run 2: 0 missed.
3. **Offline simulation found masking depended on proxy settings.** With the model call routed to a dead proxy, the local Ollama call went through the proxy too and masking failed (safely: human-led, nothing sent). Fix: Ollama calls never use a proxy. The model call then failed safe, but only after 90 seconds; the timeout is now 30.
4. **A phone with a country code was masked as a card number** (`+55 21 98888-0177` became `+[CARD_1]`). Still masked, wrong label. Fix: a number after "+" is a phone.
5. **Earlier, the classifier could fall back to a different model on a refusal.** Removed: a refusal now goes to a human like any other failure.

Both fixes were tuned on the same 60 cases they are scored on, so the passing numbers are in-sample. The honest next step is a fresh held-out set, and a model-side risk flag as a second net behind the word list.

## Evaluation results (real model, committed in `eval_runs/`)

| Check | Run 1 | Run 2 | Run 4 (latest) | Target |
|---|---|---|---|---|
| Reason accuracy | 98% (59/60) | 98% (59/60) | 98% (59/60) | at least 85% |
| Activation vs decline confusions | 0 | 0 | 0 | as few as possible |
| PII found in what was sent | 0 | 0 | 0 | 0 |
| Risk cases not sent to a human | 4 | 0 | 0 | 0 |
| Top P agreement (tracked, not gated) | 57% | 53% | 52% | none |
| Human-human agreement | Not measured | Not measured | Not measured | needed for Gate 0 |
| Gate 0 offline checks | FAIL | PASS | PASS | |

Run 3 added the repeat-contact rule (route agreement with the labels went from 50 to 55 of 60). Run 4 re-ran after the phone masking fix.

The one reason miss: C041, a new tax field after a regulatory change, labeled `unknown`; the model said `invoice_reconciliation` at 0.80, so it went to the review queue rather than being auto-tagged.

Top P agreement is about half. Most misses are process vs product (for example a stale card status: the agent's manual refresh, or the app not syncing), and 10 of 28 are within 0.15 of the label. The 4P score is the weakest output, which is why owners are shown as proposals a person confirms. The tool supports the people writing the VOC proposal; it does not make the recommendation.

Route labels: two cases labeled auto-tag (C008, C047) are repeat contacts, so the repeat rule now sends them to review. The rule is applied consistently; the labels are not.

## Hours

Build and test of this prototype with Claude Code: about 2 hours. Whole case (plan, cases, deliverables 1 to 3, this prototype): fill in.
