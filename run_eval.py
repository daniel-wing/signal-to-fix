"""Evaluation against the expected labels in cases_raw.json, using the real model.

  python3 run_eval.py             run every case through the API, then score it
  python3 run_eval.py --saved     score results/latest.json without calling the API

Writes eval_runs/<timestamp>.md (with the config and prompt used) and a .json twin
that the page reads. Commit every run.
"""
import json
import sys
from datetime import datetime

from common import ROOT, load_config, normalize, path
from mask import leak_check, planted_values
from run import load_cases, run_all

ACT_DEC = ("card_activation", "payment_declined")


def expected(meta, field):
    """Find an expected label whatever the case file calls it."""
    for container in (meta.get("expected"), meta.get("labels"), meta.get("label"), meta):
        if isinstance(container, dict):
            for k in (field, f"expected_{field}"):
                if container.get(k) is not None:
                    return container[k]
    return None


def is_risk_case(meta):
    for v in (expected(meta, "is_risk"), expected(meta, "risk")):
        if v is not None:
            return bool(v)
    return expected(meta, "route") == "human_led" and bool(expected(meta, "risk_reason"))


def score(cfg, records, cases):
    by_id = {(c.get("id") or c.get("case_id")): c for c in cases}
    labeled = correct = unclassified = 0
    act_dec = []
    misses = []
    pii_sent = []
    risk_missed = []
    routes = {}
    for r in records:
        routes[r["route"]["route"]] = routes.get(r["route"]["route"], 0) + 1
        exp = expected(r["meta"], "contact_reason")
        got = r["classification"]["contact_reason"] if r["classification"] else None
        if exp:
            labeled += 1
            if got is None:
                unclassified += 1
            if got == exp:
                correct += 1
            else:
                conf = r["classification"]["confidence"] if r["classification"] else None
                misses.append({"id": r["id"], "expected": exp, "got": got, "confidence": conf,
                               "route": r["route"]["route"]})
                if exp in ACT_DEC and got in ACT_DEC:
                    act_dec.append(f"{r['id']}: expected {exp}, got {got}")
        if r["sent"]:
            planted = planted_values(by_id.get(r["id"], {}))
            found = [p for p in planted if p and normalize(p) in normalize(r["sent"])]
            found += leak_check(r["sent"], {})
            if found:
                pii_sent.append(f"{r['id']}: {len(found)} item(s)")
        if is_risk_case(r["meta"]) and r["route"]["route"] != "human_led":
            risk_missed.append(f"{r['id']}: routed {r['route']['route']}")
    acc = correct / labeled if labeled else 0
    gate = cfg["eval"]["accuracy_gate"]
    return {
        "cases": len(records), "labeled": labeled, "correct": correct, "accuracy": round(acc, 3),
        "unclassified": unclassified, "accuracy_gate": gate,
        "activation_decline_confusions": act_dec, "pii_in_sent": pii_sent,
        "risk_not_human_led": risk_missed, "routes": routes, "misses": misses,
        "passes": acc >= gate and not pii_sent and not risk_missed,
    }


def report_md(cfg, s, run_at, source):
    pct = lambda x: f"{x:.0%}"
    lines = [
        f"# Eval run {run_at}", "",
        f"Source: {source}. Model: `{cfg['llm']['model']}` (effort {cfg['llm']['effort']}). Synthetic data only.",
        "Labels were written with AI help and reviewed, so this measures agreement with reviewed labels, "
        "not real-world accuracy.", "",
        "| Check | Result | Target |", "|---|---|---|",
        f"| Reason accuracy | {pct(s['accuracy'])} ({s['correct']}/{s['labeled']}) | at least {pct(s['accuracy_gate'])} |",
        f"| Activation vs decline confusions | {len(s['activation_decline_confusions'])} | as few as possible |",
        f"| PII found in what was sent | {len(s['pii_in_sent'])} | 0 |",
        f"| Risk cases not sent to a human | {len(s['risk_not_human_led'])} | 0 |",
        f"| Not classified (blocked or API failure) | {s['unclassified']} | counted as wrong |", "",
        f"**Gate 0 offline checks: {'PASS' if s['passes'] else 'FAIL'}** "
        "(human-human agreement is not yet measured, so the full gate cannot pass yet).", "",
        "Routes: " + ", ".join(f"{k} {v}" for k, v in sorted(s["routes"].items())), "",
        "## Misses", "", "| Case | Expected | Got | Confidence | Route |", "|---|---|---|---|---|",
    ]
    for m in s["misses"]:
        conf = "-" if m["confidence"] is None else f"{m['confidence']:.2f}"
        lines.append(f"| {m['id']} | {m['expected']} | {m['got'] or '-'} | {conf} | {m['route']} |")
    for title, items in (("Activation vs decline", s["activation_decline_confusions"]),
                         ("PII in sent text", s["pii_in_sent"]),
                         ("Risk cases not human-led", s["risk_not_human_led"])):
        lines += ["", f"## {title}", ""] + ([f"- {i}" for i in items] or ["None."])
    lines += ["", "## Config used", "", "```yaml", (ROOT / "config.yaml").read_text(encoding="utf-8").strip(), "```",
              "", "## Prompt used", "", "```", path(cfg, "prompt").read_text(encoding="utf-8").strip(), "```", ""]
    return "\n".join(lines)


def main(argv):
    cfg = load_config()
    cases = load_cases(cfg)
    if "--saved" in argv:
        records = json.loads(path(cfg, "results").read_text(encoding="utf-8"))["records"]
        source = "saved run results/latest.json"
    else:
        records = run_all(cfg)
        source = "fresh run against the API"
    s = score(cfg, records, cases)
    run_at = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out_dir = path(cfg, "eval_runs")
    out_dir.mkdir(exist_ok=True)
    (out_dir / f"{run_at}.md").write_text(report_md(cfg, s, run_at, source), encoding="utf-8")
    (out_dir / f"{run_at}.json").write_text(json.dumps({"run_at": run_at, **s}, indent=2), encoding="utf-8")
    print(f"\nAccuracy {s['accuracy']:.0%} ({s['correct']}/{s['labeled']}), "
          f"act/dec confusions {len(s['activation_decline_confusions'])}, "
          f"PII sent {len(s['pii_in_sent'])}, risk missed {len(s['risk_not_human_led'])}: "
          f"{'PASS' if s['passes'] else 'FAIL'}")
    print(f"Saved eval_runs/{run_at}.md")


if __name__ == "__main__":
    main(sys.argv[1:])
