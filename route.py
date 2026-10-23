"""Routing rules, applied in order. Thresholds and risk words come from config.yaml."""
import re

from common import normalize

ACT_DEC = {"card_activation", "payment_declined"}

OWNERS = {
    "people": "Team lead: coaching",
    "process": "Process owner",
    "policy": "Policy: cost-benefit review",
}


def risk_hits(cfg, masked_text):
    """Risk words found as whole words ("robaron" must not match inside "aprobaron")."""
    text = normalize(masked_text)
    return [w for w in cfg["routing"]["risk_words"]
            if re.search(r"(?<!\w)" + re.escape(normalize(w)) + r"(?!\w)", text)]


def owners(cfg, result):
    """Top P always gets an owner; any other P above the threshold gets one too."""
    scores = {p: v["score"] for p, v in result["four_p"].items()}
    top = max(scores, key=scores.get)
    picked = [top] + [p for p, s in sorted(scores.items(), key=lambda x: -x[1])
                      if p != top and s > cfg["routing"]["secondary_owner_min_score"]]
    out = []
    for p in picked:
        if p == "product":
            owner = ("Product: bug draft for engineering" if result["is_defect"]
                     else "Product: user-story candidate for PM weekly review")
        else:
            owner = OWNERS[p]
        out.append({"p": p, "score": scores[p], "owner": owner})
    return out


def route(cfg, masked_text, mask_problem, classification):
    """Returns {"route": human_led | emerging | review_queue | auto_tag, "why": ..., "owners": [...]}.

    mask_problem: None, or why masking failed / what the leak check found.
    classification: the dict from classify.classify(), or None if nothing was sent.
    """
    r = cfg["routing"]
    result = classification and classification["result"]
    own = owners(cfg, result) if result else []

    def out(name, why):
        return {"route": name, "why": why, "owners": own}

    # 1. Masking failure or risk word.
    if mask_problem:
        return out("human_led", f"Masking problem, nothing sent: {mask_problem}")
    hits = risk_hits(cfg, masked_text)
    if hits:
        return out("human_led", f"Risk words: {', '.join(hits)}")
    if not result:
        why = classification["error"] if classification else "not classified"
        return out("human_led", f"Classification unavailable ({why}). Nothing auto-tagged.")
    # 2. Unknown reason.
    if result["contact_reason"] == "unknown":
        return out("emerging", "Reason unknown: a human names it")
    # 3-5. Confidence bands, activation vs decline ambiguity, repeat contacts.
    conf = result["confidence"]
    if conf < r["review_min_confidence"]:
        return out("human_led", f"Confidence {conf:.2f} below {r['review_min_confidence']:.2f}")
    if result["contact_reason"] in ACT_DEC and result["ambiguous_with"] in ACT_DEC:
        return out("review_queue", "Activation vs decline ambiguity")
    if r.get("repeat_to_review") and result["is_repeat"]:
        return out("review_queue", "Repeat contact: the first contact did not solve it")
    if conf < r["auto_tag_min_confidence"]:
        return out("review_queue", f"Confidence {conf:.2f} below {r['auto_tag_min_confidence']:.2f}")
    return out("auto_tag", f"Confidence {conf:.2f}")
