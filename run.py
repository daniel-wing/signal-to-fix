"""Signal-to-Fix entry point.

  python3 run.py check            config, Ollama, API key, one tiny API call
  python3 run.py                  run every case in cases_raw.json, save results/latest.json
  python3 run.py --only C001      run one case and print every stage
  python3 run.py serve            open the page at http://localhost:8000
"""
import json
import sys
from datetime import datetime

from classify import ClassificationUnavailable, call_llm, classify
from common import api_key, load_config, ollama_models, path
from mask import case_text, leak_check, mask, save_vault
from route import route


def check():
    ok = True
    try:
        cfg = load_config()
        print("config:   OK")
    except Exception as e:
        print(f"config:   FAIL ({e})")
        return False

    try:
        models = ollama_models(cfg)
        want = cfg["ollama"]["model"]
        if want in models:
            print(f"ollama:   OK ({want})")
        else:
            print(f"ollama:   FAIL (model {want} not pulled)")
            ok = False
    except Exception as e:
        print(f"ollama:   FAIL (not reachable at {cfg['ollama']['url']}: {e})")
        ok = False

    present = bool(api_key(cfg))
    print(f"api key:  {'yes' if present else 'no'}")
    if not present:
        return False

    try:
        text, model = call_llm(cfg, "Reply with the single word OK.", "ping")
        print(f"api call: OK ({model} replied {text.strip()[:20]!r})")
    except ClassificationUnavailable as e:
        print(f"api call: FAIL ({e})")
        ok = False
    return ok


def load_cases(cfg):
    cases = json.loads(path(cfg, "cases").read_text(encoding="utf-8"))
    return cases.get("cases", []) if isinstance(cases, dict) else cases


def process(cfg, case_id, raw, meta=None):
    """One case through every stage. Only masked text that passed the leak check is sent."""
    rec = {"id": case_id, "meta": meta or {}, "raw": raw, "masked": None, "masked_tokens": [],
           "mask_problem": None, "sent": None, "classification": None, "model": None,
           "attempts": 0, "error": None, "route": None}
    try:
        masked, mapping = mask(cfg, raw)
        rec["masked"] = masked
        rec["masked_tokens"] = sorted(mapping)  # token names only; values stay in vault.json
        save_vault(cfg, case_id, mapping)
        leaks = leak_check(masked, mapping)
        if leaks:
            rec["mask_problem"] = f"leak check found {len(leaks)} item(s): " + "; ".join(
                l.split(":")[0] for l in leaks)
    except Exception as e:
        rec["mask_problem"] = f"masking failed ({type(e).__name__})"

    cls = None
    if not rec["mask_problem"]:
        cls = classify(cfg, rec["masked"])
        rec.update(sent=cls["sent"] and cls["sent"]["user"], classification=cls["result"], model=cls["model"],
                   attempts=cls["attempts"], error=cls["error"])
    rec["route"] = route(cfg, rec["masked"] or "", rec["mask_problem"], cls)
    return rec


def show(rec):
    c = rec["classification"]
    print(f"===== {rec['id']} =====")
    print("--- 1. raw (stays on this machine) ---\n" + rec["raw"])
    print("--- 2. masked locally ---\n" + (rec["masked"] or "(masking failed)"))
    print(f"    tokens: {', '.join(rec['masked_tokens']) or 'none'}")
    print("--- 3. leak check ---\n" + (rec["mask_problem"] or "passed"))
    print("--- 4. sent to the API ---\n" + (rec["sent"] or "(nothing sent)"))
    print("--- 5. classification ---")
    if c:
        print(f"reason: {c['contact_reason']} / {c['sub_reason']}  ambiguous_with: {c['ambiguous_with']}")
        print(f"confidence: {c['confidence']:.2f}  defect: {c['is_defect']}  repeat: {c['is_repeat']}")
        for p, v in c["four_p"].items():
            print(f"  {p:8s} {v['score']:.2f} {'#' * round(v['score'] * 20):20s} {v['quote']}")
        print(f"rationale: {c['rationale']}")
        print(f"model: {rec['model']}  attempts: {rec['attempts']}")
    else:
        print("Classification unavailable. Nothing auto-tagged." + (f" ({rec['error']})" if rec["error"] else ""))
    r = rec["route"]
    print(f"--- 6. route ---\n{r['route']}: {r['why']}")
    for o in r["owners"]:
        print(f"  owner: {o['owner']} ({o['p']} {o['score']:.2f})")
    print()


def run_all(cfg, only=None):
    cases = load_cases(cfg)
    if only:
        cases = [c for c in cases if (c.get("id") or c.get("case_id")) == only]
        if not cases:
            sys.exit(f"No case {only} in {cfg['paths']['cases']}")
    records = []
    for i, case in enumerate(cases, 1):
        cid = case.get("id") or case.get("case_id")
        meta = {k: v for k, v in case.items() if k not in ("conversation", "text")}
        rec = process(cfg, cid, case_text(case), meta)
        records.append(rec)
        if only:
            show(rec)
        else:
            c = rec["classification"]
            reason = c["contact_reason"] if c else "-"
            print(f"[{i}/{len(cases)}] {cid}: {reason:24s} {rec['route']['route']:12s} {rec['route']['why']}")
    if not only:
        out = path(cfg, "results")
        out.parent.mkdir(exist_ok=True)
        out.write_text(json.dumps({"run_at": datetime.now().isoformat(timespec="seconds"),
                                   "model": cfg["llm"]["model"], "records": records},
                                  ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nSaved {len(records)} results to {out.relative_to(out.parent.parent)}")
    return records


def main(argv):
    if argv[:1] == ["check"]:
        sys.exit(0 if check() else 1)
    if argv[:1] == ["serve"]:
        import server
        server.serve(load_config())
        return
    if argv and argv[0] not in ("--only",):
        print(__doc__)
        return
    cfg = load_config()
    run_all(cfg, argv[1] if argv[:1] == ["--only"] else None)


if __name__ == "__main__":
    main(sys.argv[1:])
