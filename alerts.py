"""Early warning: is any contact reason growing much faster than usual?

Per reason, compare its share of cases in the last few days with its share in the
weeks before. Windows and thresholds come from config.yaml (alerts section).

  python3 alerts.py               print the table for results/latest.json
"""
import json
from datetime import date, timedelta

from common import load_config, path

DATE_KEYS = ("date", "created_at", "opened_at", "closed_at")


def case_date(rec):
    for k in DATE_KEYS:
        v = rec["meta"].get(k)
        if v:
            return date.fromisoformat(str(v)[:10])
    return None


def window_counts(records, key):
    counts = {}
    for r in records:
        k = key(r)
        counts[k] = counts.get(k, 0) + 1
    return counts


def compute(cfg, records):
    a = cfg["alerts"]
    dated = [(case_date(r), r) for r in records]
    dated = [(d, r) for d, r in dated if d]
    if not dated:
        return {"error": "no dates in the case file", "rows": [], "risk": None}
    as_of = max(d for d, _ in dated)
    recent_start = as_of - timedelta(days=a["recent_days"] - 1)
    base_start = recent_start - timedelta(days=a["baseline_days"])
    recent = [r for d, r in dated if recent_start <= d <= as_of]
    base = [r for d, r in dated if base_start <= d < recent_start]

    def reason(r):
        c = r["classification"]
        return c["contact_reason"] if c else "not_classified"

    def compare(rc, bc, n_recent, n_base):
        rs = rc / n_recent if n_recent else 0
        bs = bc / n_base if n_base else 0
        ratio = rs / bs if bs else (float("inf") if rs else 0)
        alert = rc >= a["min_recent_cases"] and ratio >= a["min_ratio"]
        return {"recent": rc, "recent_share": round(rs, 3), "baseline": bc,
                "baseline_share": round(bs, 3),
                "ratio": None if ratio == float("inf") else round(ratio, 2), "alert": alert}

    rc, bc = window_counts(recent, reason), window_counts(base, reason)
    rows = [{"reason": k, **compare(rc.get(k, 0), bc.get(k, 0), len(recent), len(base))}
            for k in sorted(set(rc) | set(bc))]
    rows.sort(key=lambda x: (not x["alert"], -x["recent"]))

    def is_risk(r):
        return r["route"]["why"].startswith("Risk words")
    risk = compare(sum(map(is_risk, recent)), sum(map(is_risk, base)), len(recent), len(base))

    return {"as_of": as_of.isoformat(),
            "recent_window": f"{recent_start} to {as_of} ({len(recent)} cases)",
            "baseline_window": f"{base_start} to {recent_start - timedelta(days=1)} ({len(base)} cases)",
            "rule": f"share at least {a['min_ratio']}x baseline and at least {a['min_recent_cases']} cases",
            "rows": rows, "risk": risk}


def main():
    cfg = load_config()
    records = json.loads(path(cfg, "results").read_text(encoding="utf-8"))["records"]
    out = compute(cfg, records)
    if out.get("error"):
        print(out["error"])
        return
    print(f"Recent:   {out['recent_window']}\nBaseline: {out['baseline_window']}\nRule:     {out['rule']}\n")
    print(f"{'reason':24s} {'recent':>6s} {'share':>6s} {'base':>5s} {'share':>6s} {'ratio':>6s}  alert")
    for r in out["rows"]:
        ratio = "new" if r["ratio"] is None else f"{r['ratio']:.2f}"
        print(f"{r['reason']:24s} {r['recent']:6d} {r['recent_share']:6.0%} {r['baseline']:5d} "
              f"{r['baseline_share']:6.0%} {ratio:>6s}  {'ALERT' if r['alert'] else ''}")
    k = out["risk"]
    print(f"\nRisk cases: {k['recent']} recent vs {k['baseline']} baseline {'ALERT' if k['alert'] else ''}")


if __name__ == "__main__":
    main()
