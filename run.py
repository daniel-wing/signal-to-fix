"""Signal-to-Fix entry point.

  python3 run.py check            config, Ollama, API key, one tiny API call
"""
import sys

from classify import ClassificationUnavailable, call_llm
from common import api_key, load_config, ollama_models


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


def main(argv):
    if argv[:1] == ["check"]:
        sys.exit(0 if check() else 1)
    print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
