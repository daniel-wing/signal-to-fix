"""Shared helpers: config, .env, text normalization, Ollama call (standard library only)."""
import json
import os
import unicodedata
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent


def load_config():
    """Read config.yaml fresh every time, so live edits take effect on the next run."""
    with open(ROOT / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def path(cfg, key):
    return ROOT / cfg["paths"][key]


def load_env():
    """Load .env into the environment. Values are never printed."""
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def api_key(cfg):
    load_env()
    return os.environ.get(cfg["llm"]["api_key_env"], "").strip()


def normalize(text):
    """Lowercase and strip accents, for word matching."""
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def ollama_generate(cfg, prompt, json_format=True):
    """Call the local Ollama model. Returns the response text."""
    body = {"model": cfg["ollama"]["model"], "prompt": prompt, "stream": False,
            "options": {"temperature": 0}}
    if json_format:
        body["format"] = "json"
    req = urllib.request.Request(
        cfg["ollama"]["url"].rstrip("/") + "/api/generate",
        data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=cfg["ollama"]["timeout_seconds"]) as r:
        return json.loads(r.read())["response"]


def ollama_models(cfg):
    req = urllib.request.Request(cfg["ollama"]["url"].rstrip("/") + "/api/tags")
    with urllib.request.urlopen(req, timeout=5) as r:
        return [m["name"] for m in json.loads(r.read())["models"]]
