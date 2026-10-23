"""Local masking and the leak check. Nothing here talks to the internet.

  python3 mask.py --all           mask every case, show planted PII still visible (target 0)
  python3 mask.py --only C001     show one case raw vs masked
"""
import json
import re
import sys

from common import load_config, normalize, ollama_generate, path

# Order matters: specific formats first, so a CPF is not read as a phone number.
PATTERNS = [
    ("EMAIL", r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"),
    ("CNPJ", r"\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b"),
    ("CPF", r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b"),
    ("NIT", r"\bNIT\s*(?:No\.?|#|:)?\s*\d[\d.\s]{6,}\d(?:\s*-\s*\d)?|\b\d{3}\.\d{3}\.\d{3}\s*-\s*\d\b"),
    ("RFC", r"\b[A-ZÑ&]{3,4}\d{6}[A-Z\d]{3}\b"),
    ("CARD", r"(?<![+\d])\b(?:\d[ -]?){12,18}\d\b"),  # not after "+": that is a phone
    ("CARD_LAST4", r"(?:termina(?:da|do|cion|ción)?\s+(?:en\s+)?|terminación\s+|"
                   r"[uú]ltimos\s+(?:4|cuatro)\s+(?:d[ií]gitos\s+)?(?:son\s+|:\s*)?|"
                   r"final(?:iza)?\s+(?:en\s+)?|[*xX•]{2,}\s?)(\d{4})\b"),
    ("ACCOUNT", r"\b(?:LP|ACC|ACCT|CTA|CLI)[-_ ]?(?=[A-Z\d]*\d)[A-Z\d]{4,}\b"),
    ("AMOUNT", r"(?:R\$|US\$|\$|MXN|COP|BRL|USD)\s?\d[\d.,]*\d|\b\d[\d.,]*\d?\s?"
               r"(?:pesos|reales|reais|MXN|COP|BRL|USD|d[oó]lares)\b"),
    ("PHONE", r"(?<![\w\[])\+?(?:\d[\s().-]{0,2}){8,14}\d\b"),  # 9+ digits, so dates are not phones
    ("ID", r"\b\d{5,}\b"),
    # Any other standalone 4 digits ("cartao 5561", a reply of just "7716"), except years.
    ("CARD_LAST4", r"(?<![\d.,/:-])\b(?!(?:19|20)\d\d\b)(\d{4})\b(?![.,:/-]?\d)"),
]
COMPILED = [(label, re.compile(rx, 0 if label in ("RFC", "ACCOUNT") else re.IGNORECASE))
            for label, rx in PATTERNS]
TOKEN_RE = re.compile(r"\[[A-Z0-9_]+_\d+\]")
# Cues that a capitalized name follows or precedes. Names from these join the model's list.
CAP = r"[A-ZÁÉÍÓÚÑÂÊÔÃÕÇ][a-záéíóúñâêôãõç]+"
NAME_HINT_RES = [
    # "soy Jorge", "Hola Débora Vieira", "Gracias Camilo"
    re.compile(r"\b(?i:soy|me llamo|mi nombre es|le atiende|te atiende|habla|hola|gracias)\s+"
               rf"({CAP}(?:\s+{CAP}){{0,3}})"),
    # "Cliente: Larissa Duarte, [ACCOUNT_1]" (name given when the agent asks for it)
    re.compile(rf"^(?:Cliente|Agente):\s*({CAP}(?:\s+{CAP}){{1,3}})\s*,", re.MULTILINE),
]
# Greeting or intro words a name cue can pick up in front of a name ("Hola Karla Mendoza").
LEAD_WORDS = {"hola", "soy", "habla", "gracias", "buenas", "buenos", "oye", "oi", "ola", "me", "llamo"}
# A capitalized phrase starting with these is a menu path or a sentence, not a name ("En Equipo").
NOT_NAME_START = {"en", "el", "la", "los", "las", "de", "del", "por", "para", "con", "al", "un", "una"}
NEVER_PII = {"lumenpay", "cliente", "agente", "soporte", "hola", "gracias"}

LOCAL_PROMPT = """Eres un detector de datos personales. Lee la conversacion de soporte y devuelve SOLO un JSON:
{{"names": [...], "addresses": [...]}}
- names: nombres y apellidos de personas (clientes, agentes, empleados, contadores), copiados exactamente como aparecen.
- addresses: direcciones postales (calle, numero, colonia, barrio, ciudad con calle), copiadas exactamente.
No incluyas empresas, productos, paises, meses ni marcadores entre corchetes como [EMAIL_1].
Si no hay, devuelve listas vacias.

Conversacion:
{text}"""


def case_text(case):
    """The conversation as one string, whatever shape the case file uses."""
    conv = case.get("conversation", case.get("text", ""))
    if isinstance(conv, str):
        return conv
    lines = []
    for turn in conv:
        who = turn.get("role") or turn.get("speaker") or turn.get("from") or ""
        msg = turn.get("text") or turn.get("message") or turn.get("content") or ""
        lines.append(f"{who}: {msg}" if who else msg)
    return "\n".join(lines)


class Masker:
    def __init__(self):
        self.mapping = {}   # token -> original value
        self.counts = {}

    def token_for(self, label, value):
        for tok, orig in self.mapping.items():
            if tok.startswith(f"[{label}_") and normalize(orig) == normalize(value):
                return tok
        self.counts[label] = self.counts.get(label, 0) + 1
        tok = f"[{label}_{self.counts[label]}]"
        self.mapping[tok] = value
        return tok

    def apply_regex(self, text):
        for label, rx in COMPILED:
            def sub(m, label=label):
                if TOKEN_RE.fullmatch(m.group(0)):
                    return m.group(0)
                if label == "CARD_LAST4":
                    # Keep the words ("termina en"), mask only the digits.
                    digits = m.group(1)
                    return m.group(0)[: m.start(1) - m.start(0)] + self.token_for(label, digits)
                return self.token_for(label, m.group(0).strip())
            text = rx.sub(sub, text)
        return text

    def replace_literal(self, text, label, value):
        tok = self.token_for(label, value)
        return re.sub(r"(?<!\w)" + re.escape(value) + r"(?!\w)", tok, text, flags=re.IGNORECASE)

    def apply_local_model(self, cfg, text):
        raw = ollama_generate(cfg, LOCAL_PROMPT.format(text=text))
        found = json.loads(raw)  # invalid JSON raises: the caller treats it as a masking failure
        names = [n for n in found.get("names", []) if isinstance(n, str)]
        for rx in NAME_HINT_RES:
            names += rx.findall(text)
        addresses = [a for a in found.get("addresses", []) if isinstance(a, str)]
        # Only accept values that really are in the text (the small model can invent).
        for addr in sorted(addresses, key=len, reverse=True):
            if len(addr) >= 6 and normalize(addr) in normalize(text):
                text = self.replace_literal(text, "ADDRESS", addr)
        cleaned = []
        for name in names:
            parts = name.split()
            while parts and normalize(parts[0]) in LEAD_WORDS:
                parts = parts[1:]
            if parts and normalize(parts[0]) not in NOT_NAME_START:
                cleaned.append(" ".join(parts))
        for name in sorted(set(cleaned), key=len, reverse=True):
            name = name.strip()
            if len(name) < 3 or normalize(name) in NEVER_PII or normalize(name) not in normalize(text):
                continue
            text = self.replace_literal(text, "NAME", name)
            tok = self.token_for("NAME", name)
            # A first name or surname alone later in the chat gets the same token.
            for part in name.split():
                if len(part) >= 3 and normalize(part) not in NEVER_PII:
                    text = re.sub(r"(?<!\w)" + re.escape(part) + r"(?!\w)", tok, text, flags=re.IGNORECASE)
        return text


def mask(cfg, text):
    """Returns (masked_text, mapping). Raises if the local model fails."""
    m = Masker()
    text = m.apply_regex(text)
    text = m.apply_local_model(cfg, text)
    return text, m.mapping


def leak_check(masked, mapping):
    """Everything detectable that is still in the text. Empty list means safe to send."""
    leaks = []
    without_tokens = TOKEN_RE.sub(" ", masked)
    for label, rx in COMPILED:
        for m in rx.finditer(without_tokens):
            leaks.append(f"{label}: {m.group(0).strip()}")
    plain = normalize(without_tokens)
    for tok, orig in mapping.items():
        if normalize(orig) in plain:
            leaks.append(f"{tok} value still present")
    return leaks


def save_vault(cfg, case_id, mapping):
    vault_file = path(cfg, "vault")
    vault = json.loads(vault_file.read_text(encoding="utf-8")) if vault_file.exists() else {}
    vault[case_id] = mapping
    vault_file.write_text(json.dumps(vault, ensure_ascii=False, indent=2), encoding="utf-8")


def planted_values(case):
    """PII values the case author planted, if the case file lists them."""
    pii = case.get("pii_values") or case.get("planted_pii") or case.get("pii") or []
    if isinstance(pii, dict):
        pii = [v for vals in pii.values() for v in (vals if isinstance(vals, list) else [vals])]
    return [p if isinstance(p, str) else str(p.get("value", "")) for p in pii]


def main(argv):
    cfg = load_config()
    cases = json.loads(path(cfg, "cases").read_text(encoding="utf-8"))
    if isinstance(cases, dict):
        cases = cases.get("cases", [])
    only = argv[argv.index("--only") + 1] if "--only" in argv else None
    if not only and "--all" not in argv:
        print(__doc__)
        return
    total_visible = 0
    for case in cases:
        cid = case.get("id") or case.get("case_id")
        if only and cid != only:
            continue
        raw = case_text(case)
        try:
            masked, mapping = mask(cfg, raw)
        except Exception as e:
            print(f"{cid}: MASKING FAILED ({type(e).__name__}) -> human-led")
            continue
        leaks = leak_check(masked, mapping)
        visible = [p for p in planted_values(case) if p and normalize(p) in normalize(masked)]
        total_visible += len(visible)
        status = "BLOCKED" if leaks else "ok"
        print(f"{cid}: {len(mapping)} masked, planted still visible: {len(visible)}, leak check: {status}")
        for v in visible:
            print(f"    visible: {v}")
        for l in leaks:
            print(f"    leak: {l}")
        if only:
            print("\n--- raw ---\n" + raw + "\n\n--- masked ---\n" + masked)
    print(f"\nPlanted PII still visible: {total_visible} (target 0)")


if __name__ == "__main__":
    main(sys.argv[1:])
