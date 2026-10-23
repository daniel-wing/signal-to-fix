"""Cloud classification. Receives masked text only; the caller must run the leak check first."""
import anthropic

from common import api_key


class ClassificationUnavailable(Exception):
    """The API could not be reached or refused. Nothing gets auto-tagged."""


def call_llm(cfg, system, user):
    """One Messages API call. Returns (text, model that served it)."""
    key = api_key(cfg)
    if not key:
        raise ClassificationUnavailable("API key missing")
    client = anthropic.Anthropic(api_key=key, timeout=cfg["llm"]["timeout_seconds"], max_retries=1)
    try:
        resp = client.beta.messages.create(
            model=cfg["llm"]["model"],
            max_tokens=cfg["llm"]["max_tokens"],
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={"effort": cfg["llm"]["effort"]},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except anthropic.APIError as e:
        raise ClassificationUnavailable(type(e).__name__) from None
    if resp.stop_reason == "refusal":
        raise ClassificationUnavailable("model refused")
    text = "".join(b.text for b in resp.content if b.type == "text")
    return text, resp.model
