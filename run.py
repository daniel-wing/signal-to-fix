"""UpstreamW entry point (v0.1).

  python3 run.py check            config, Ollama, model access, one tiny model call
  python3 run.py                  run every case in cases_raw.json, save results/latest.json
  python3 run.py --only C001      run one case and print every stage
  python3 run.py serve            the page at http://localhost:8000 (upload a case file there)
  python3 run.py serve --port N   same, on another port
"""
import json
import os
import re
import sys
import time
from datetime import datetime

from classify import ClassificationUnavailable, available, call_llm, classify
from common import ROOT, api_key, load_config, load_env, ollama_models, path
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

    backend = cfg["llm"]["backend"]
    if backend == "api":
        present = bool(api_key(cfg))
        print(f"api key:  {'yes' if present else 'no'}")
    else:
        present = available(cfg)
        print(f"backend:  Claude Code CLI ({cfg['llm']['cli']}) {'found' if present else 'NOT FOUND'}")
    if not present:
        return False

    try:
        text, model = call_llm(cfg, "Reply with the single word OK.", "ping")
        print(f"llm call: OK ({model} replied {text.strip()[:20]!r})")
    except ClassificationUnavailable as e:
        print(f"llm call: FAIL ({e})")
        ok = False
    return ok


def load_cases(cfg):
    cases = json.loads(path(cfg, "cases").read_text(encoding="utf-8"))
    return cases.get("cases", []) if isinstance(cases, dict) else cases


def raw_spans(raw, mapping):
    """Where each masked value sits in the raw text: [[start, end, type], ...] for highlighting."""
    targets = []
    for tok, value in mapping.items():
        label = tok.strip("[]").rsplit("_", 1)[0]
        targets.append((value, label))
        if label == "NAME":  # first names or surnames alone get the same token
            targets += [(part, label) for part in value.split() if len(part) >= 3]
    spans = []
    for value, label in targets:
        for m in re.finditer(r"(?<!\w)" + re.escape(value) + r"(?!\w)", raw, re.IGNORECASE):
            spans.append([m.start(), m.end(), label])
    spans.sort(key=lambda x: (x[0], -(x[1] - x[0])))
    merged = []
    for sp in spans:
        if merged and sp[0] < merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], sp[1])
        else:
            merged.append(sp)
    return merged


def mask_step(cfg, case_id, raw, meta=None):
    """Stage 1-2: mask locally and run the leak check. Nothing leaves the machine here."""
    rec = {"id": case_id, "meta": meta or {}, "raw": raw, "masked": None, "masked_tokens": [],
           "mask_problem": None, "sent": None, "classification": None, "model": None,
           "attempts": 0, "error": None, "route": None}
    try:
        masked, mapping = mask(cfg, raw)
        rec["masked"] = masked
        rec["masked_tokens"] = sorted(mapping)  # token names only; values stay in vault.json
        rec["raw_spans"] = raw_spans(raw, mapping)
        save_vault(cfg, case_id, mapping)
        leaks = leak_check(masked, mapping)
        if leaks:
            rec["mask_problem"] = f"leak check found {len(leaks)} item(s): " + "; ".join(
                l.split(":")[0] for l in leaks)
    except Exception as e:
        rec["mask_problem"] = f"masking failed ({type(e).__name__})"
    return rec


def classify_step(cfg, rec):
    """Stage 3-4: send the masked text only if the leak check passed, then route."""
    cls = None
    if not rec["mask_problem"]:
        cls = classify(cfg, rec["masked"])
        rec.update(sent=cls["sent"] and cls["sent"]["user"], classification=cls["result"], model=cls["model"],
                   attempts=cls["attempts"], error=cls["error"])
    rec["route"] = route(cfg, rec["masked"] or "", rec["mask_problem"], cls)
    return rec


def process(cfg, case_id, raw, meta=None):
    """One case through every stage. Only masked text that passed the leak check is sent."""
    return classify_step(cfg, mask_step(cfg, case_id, raw, meta))


def show(rec):
    c = rec["classification"]
    print(f"===== {rec['id']} =====")
    print("--- 1. raw (stays on this machine) ---\n" + rec["raw"])
    print("--- 2. masked locally ---\n" + (rec["masked"] or "(masking failed)"))
    print(f"    tokens: {', '.join(rec['masked_tokens']) or 'none'}")
    print("--- 3. leak check ---\n" + (rec["mask_problem"] or "passed"))
    print("--- 4. sent to the model ---\n" + (rec["sent"] or "(nothing sent)"))
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


def case_list(data):
    """Accept a list of cases or {"cases": [...]}; each needs text or conversation."""
    cases = data.get("cases", []) if isinstance(data, dict) else data
    if not isinstance(cases, list) or not cases:
        raise ValueError("The file has no cases. Expected a list of cases.")
    out = []
    for i, case in enumerate(cases, 1):
        if not isinstance(case, dict):
            raise ValueError(f"Case {i} is not an object.")
        text = case_text(case).strip()
        if not text:
            raise ValueError(f"Case {i} has no text or conversation.")
        cid = str(case.get("id") or case.get("case_id") or f"R{i:03d}")
        meta = {k: v for k, v in case.items() if k not in ("conversation", "text")}
        out.append((cid, text, meta))
    return out


class Stopped(Exception):
    """The person pressed Stop analysis."""


def analyze(cfg, cases, progress=None, stop=lambda: False):
    """Bulk run: mask every case locally, then classify the masked ones in parallel.

    cases: list of (id, text, meta). progress(phase, done, total, records) is called as work completes.
    stop() is checked before each case starts; when it returns True, cases not yet started are dropped
    and Stopped is raised. Model calls already under way finish on their own (up to the timeout).
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    n = len(cases)
    records = [None] * n
    def guarded(fn):
        def run(i):
            if stop():
                raise Stopped()
            return fn(i)
        return run

    for phase, workers, fn in (
            ("masking", 2, lambda i: mask_step(cfg, *cases[i])),
            ("classifying", cfg["llm"].get("parallel_requests", 4), lambda i: classify_step(cfg, records[i]))):
        done = 0
        pool = ThreadPoolExecutor(max_workers=workers)
        try:
            futures = {pool.submit(guarded(fn), i): i for i in range(n)}
            for fut in as_completed(futures):
                records[futures[fut]] = fut.result()
                done += 1
                if progress:
                    progress(phase, done, n, records)
        finally:
            pool.shutdown(wait=not stop(), cancel_futures=True)
    return records


def save_results(cfg, records, source):
    out = path(cfg, "results")
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"run_at": datetime.now().isoformat(timespec="seconds"), "source": source,
                               "model": cfg["llm"]["model"], "records": records},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def run_all(cfg, only=None):
    cases = case_list(load_cases(cfg))
    if only:
        cases = [c for c in cases if c[0] == only]
        if not cases:
            sys.exit(f"No case {only} in {cfg['paths']['cases']}")
        rec = process(cfg, *cases[0])
        show(rec)
        return [rec]

    def progress(phase, done, total, records):
        print(f"\r{phase}: {done}/{total}   ", end="", flush=True)
        if phase == "classifying" and done == total:
            print()
    records = analyze(cfg, cases, progress)
    for rec in records:
        c = rec["classification"]
        reason = c["contact_reason"] if c else "-"
        print(f"{rec['id']}: {reason:24s} {rec['route']['route']:12s} {rec['route']['why']}")
    out = save_results(cfg, records, cfg["paths"]["cases"])
    print(f"\nSaved {len(records)} results to {out.relative_to(out.parent.parent)}")
    return records


def page_state():
    """Everything the page shows from saved files. Config is re-read so live edits appear."""
    from alerts import compute
    cfg = load_config()
    state = {"config": {"model": cfg["llm"]["model"], "routing": cfg["routing"], "alerts": cfg["alerts"]},
             "results": None, "alerts": None, "eval": None}
    res = path(cfg, "results")
    if res.exists():
        state["results"] = json.loads(res.read_text(encoding="utf-8"))
        state["alerts"] = compute(cfg, state["results"]["records"])
    evals = sorted(path(cfg, "eval_runs").glob("*.json")) if path(cfg, "eval_runs").exists() else []
    if evals:
        state["eval"] = json.loads(evals[-1].read_text(encoding="utf-8"))
    return state


def serve(port=None):
    import webbrowser
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from itertools import count

    import threading
    jobs = {}
    job_ids = count(1)

    def run_job(job, cases):
        cfg = load_config()  # fresh: live edits to config.yaml and prompt.txt apply to each upload

        def progress(phase, done, total, records):
            job.update(phase=phase, done=done, total=total, records=records)
        try:
            records = analyze(cfg, cases, progress, stop=lambda: job["stop"])
            save_results(cfg, records, job["name"])
            job.update(phase="done", records=records, seconds=round(time.time() - job["started"]))
        except Stopped:
            job.update(phase="stopped")  # nothing saved: the last analysis stays as it was
        except Exception as e:
            job.update(phase="failed", error=f"{type(e).__name__}: {e}")

    # Shared password for test users (UPSTREAMW_PASSWORD in .env). Without it the page is open,
    # which is fine on 127.0.0.1 but not once the page is published with Tailscale Funnel.
    load_env()
    password = os.environ.get("UPSTREAMW_PASSWORD", "")

    class Handler(BaseHTTPRequestHandler):
        def allowed(self):
            """Browser login box: any user name, the shared password."""
            if not password:
                return True
            import base64
            import hmac
            given = self.headers.get("Authorization", "")
            try:
                _, _, pw = base64.b64decode(given.removeprefix("Basic ")).decode().partition(":")
            except ValueError:
                pw = ""
            if given.startswith("Basic ") and hmac.compare_digest(pw.encode(), password.encode()):
                return True
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="UpstreamW", charset="UTF-8"')
            self.send_header("Content-Length", "0")
            self.end_headers()
            return False

        def send(self, code, body, ctype="application/json"):
            data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype + "; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")  # coming back to the page must show the live state
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if not self.allowed():
                return
            route_path, _, query = self.path.partition("?")
            if route_path in ("/", "/index.html"):
                self.send(200, (ROOT / "app.html").read_bytes(), "text/html")
            elif route_path == "/how":
                self.send(200, (ROOT / "how.html").read_bytes(), "text/html")
            elif route_path == "/api/state":
                state = page_state()
                # a page opened mid-run (for example after visiting How it works) reconnects to it
                running = [j for j in jobs.values() if j["phase"] in ("masking", "classifying", "starting")]
                state["running"] = {"id": running[0]["id"], "total": running[0]["total"]} if running else None
                self.send(200, state)
            elif route_path == "/api/job":
                job = jobs.get(query.removeprefix("id="))
                if not job:
                    return self.send(404, {"error": "Unknown analysis."})
                self.send(200, {k: v for k, v in job.items()})
            else:
                self.send(404, {"error": "not found"})

        def do_POST(self):
            if not self.allowed():
                return
            route_path, _, query = self.path.partition("?")
            if route_path == "/api/stop":
                job = jobs.get(query.removeprefix("id="))
                if not job:
                    return self.send(404, {"error": "Unknown analysis."})
                job["stop"] = True
                return self.send(200, {"ok": True})
            if route_path != "/api/upload":
                return self.send(404, {"error": "not found"})
            if any(j["phase"] in ("masking", "classifying", "starting") for j in jobs.values()):
                return self.send(409, {"error": "An analysis is already running. Wait for it to finish."})
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                cases = case_list(body.get("data"))
            except (ValueError, json.JSONDecodeError) as e:
                return self.send(400, {"error": str(e)})
            jid = str(next(job_ids))
            job = {"id": jid, "name": str(body.get("name") or "uploaded file"), "phase": "starting",
                   "done": 0, "total": len(cases), "records": [], "error": None, "stop": False, "started": time.time()}
            jobs[jid] = job
            threading.Thread(target=run_job, args=(job, cases), daemon=True).start()
            self.send(200, {"id": jid, "total": len(cases)})

        def log_message(self, fmt, *args):
            pass

    cfg = load_config()
    host, port = cfg["server"]["host"], port or cfg["server"]["port"]
    url = f"http://localhost:{port}"
    print(f"UpstreamW v0.1. Serving {url}  (Ctrl+C to stop)")
    print("Password: on (UPSTREAMW_PASSWORD in .env)" if password else "Password: off (set UPSTREAMW_PASSWORD in .env before publishing)")
    if os.environ.get("DISPLAY") or sys.platform == "darwin":
        try:
            webbrowser.open(url)
        except Exception:
            pass
    else:
        print(f"Headless machine. From your laptop: ssh -L 47321:localhost:{port} <this-host>, "
              "then open http://localhost:47321 (any free laptop port works)")
    ThreadingHTTPServer((host, port), Handler).serve_forever()


def main(argv):
    if argv[:1] == ["check"]:
        sys.exit(0 if check() else 1)
    if argv[:1] == ["serve"]:
        serve(int(argv[2]) if argv[1:2] == ["--port"] else None)
        return
    if argv and argv[0] not in ("--only",):
        print(__doc__)
        return
    cfg = load_config()
    run_all(cfg, argv[1] if argv[:1] == ["--only"] else None)


if __name__ == "__main__":
    main(sys.argv[1:])
