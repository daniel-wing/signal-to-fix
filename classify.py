"""Cloud classification. Receives masked text only; the caller must run the leak check first."""
import json
import re

import anthropic

from common import api_key, path

REASONS = ["card_activation", "payment_declined", "invoice_reconciliation",
           "account_access", "how_to_policy", "other", "unknown"]
SUB_REASONS = {
    "card_activation": ["processor_delay", "needs_status_refresh", "wrong_phone"],
    "payment_declined": ["hidden_limit", "admin_category_block", "processor_timeout"],
    "invoice_reconciliation": ["tax_fields", "timing_mismatch", "export_format"],
}
PS = ["people", "process", "policy", "product"]


class ClassificationUnavailable(Exception):
    """The API could not be reached or refused. Nothing gets auto-tagged."""


def call_llm(cfg, system, user):
    """One Messages API call. Returns (text, model that served it)."""
    key = api_key(cfg)
    if not key:
        raise ClassificationUnavailable("API key missing")
    client = anthropic.Anthropic(api_key=key, timeout=cfg["llm"]["timeout_seconds"], max_retries=1)
    try:
        resp = client.messages.create(
            model=cfg["llm"]["model"],
            max_tokens=cfg["llm"]["max_tokens"],
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={"effort": cfg["llm"]["effort"]},
        )
    except anthropic.APIError as e:
        raise ClassificationUnavailable(type(e).__name__) from None
    if resp.stop_reason == "refusal":
        raise ClassificationUnavailable("model refused")
    text = "".join(b.text for b in resp.content if b.type == "text")
    return text, resp.model


def parse(text):
    """Parse and validate the model's JSON. Raises ValueError if it is not usable."""
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    data = json.loads(text)
    if data.get("contact_reason") not in REASONS:
        raise ValueError(f"bad contact_reason {data.get('contact_reason')!r}")
    if data.get("sub_reason") not in SUB_REASONS.get(data["contact_reason"], []):
        data["sub_reason"] = None
    if data.get("ambiguous_with") not in REASONS or data.get("ambiguous_with") == data["contact_reason"]:
        data["ambiguous_with"] = None
    conf = float(data["confidence"])
    if not 0 <= conf <= 1:
        raise ValueError("confidence out of range")
    data["confidence"] = conf
    for p in PS:
        entry = data["four_p"][p]
        entry["score"] = max(0.0, min(1.0, float(entry["score"])))
        entry["quote"] = str(entry.get("quote") or "")
    data["is_defect"] = bool(data.get("is_defect"))
    data["is_repeat"] = bool(data.get("is_repeat"))
    data["rationale"] = str(data.get("rationale") or "")
    return data


def classify(cfg, masked_text):
    """Classify one masked conversation.

    Returns a dict with: sent (exactly what left the machine), attempts, model,
    result (parsed JSON or None) and error (None or a short reason).
    Invalid JSON gets one retry, then the case goes to a human.
    """
    system = path(cfg, "prompt").read_text(encoding="utf-8")  # read fresh: live prompt edits apply
    user = f"<conversation>\n{masked_text}\n</conversation>"
    out = {"sent": None, "attempts": 0, "model": None, "raw_response": None, "result": None, "error": None}
    if not api_key(cfg):
        out["error"] = "unavailable: API key missing"
        return out
    out["sent"] = {"model": cfg["llm"]["model"], "system": system, "user": user}
    for _ in range(2):
        out["attempts"] += 1
        try:
            text, out["model"] = call_llm(cfg, system, user)
        except ClassificationUnavailable as e:
            out["error"] = f"unavailable: {e}"
            return out
        out["raw_response"] = text
        try:
            out["result"] = parse(text)
            out["error"] = None
            return out
        except (ValueError, KeyError, TypeError) as e:
            out["error"] = f"invalid JSON: {e}"
    return out
