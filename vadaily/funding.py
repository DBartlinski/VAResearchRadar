import re

from .utils import clean_text, split_multi

SERVICE_BY_CODE = {"BX": "BLR&D", "CX": "CSR&D", "HX": "HSR&D", "RX": "RR&D"}
SERVICE_ORDER = ["BLR&D", "CSR&D", "HSR&D", "RR&D", "CSP"]
UNSPECIFIED = "ORD (service not identified)"

# VA ORD award numbers: optional mechanism (I01, IK2, 1IK6...) + service code + 6-7 digits.
GRANT_CODE_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:\d?\s*(?:I01|I21|I50|IK1|IK2|IK3|IK4|IK6|IK7|IS1|IP1|IU1|I0X)[\s\-]*)?"
    r"([BCHR]X)[\s\-\u2010\u2011]?(\d{6,7})(?!\d)"
)
CSP_RE = re.compile(r"\bCSP\s*(?:#|No\.?\s*)?\d{1,4}\b|Cooperative Studies Program", re.I)
SERVICE_NAME_RES = {
    "BLR&D": re.compile(r"Biomedical Laborator(?:y|ies) Research|\bBLR&D\b|\bBLRD\b", re.I),
    "CSR&D": re.compile(r"Clinical Sciences? Research (?:and|&) Development|\bCSR&D\b|\bCSRD\b", re.I),
    "HSR&D": re.compile(
        r"Health Services Research (?:and|&) Development|Health Systems Research|\bHSR&D\b|\bHSRD\b"
        r"|\bHSR\b|\bQUERI\b|Quality Enhancement Research Initiative", re.I),
    "RR&D": re.compile(
        r"Rehabilitation Research (?:and|&) Development|Rehab(?:ilitation)?\.? ?R ?&? ?D\b|\bRR&D\b|\bRRD\b", re.I),
    "CSP": CSP_RE,
}
HSR_PROJECT_RE = re.compile(r"\b(?:IIR|SDR|QUE|PPO|RCS|CIN|HFP|PEC|SWX|C19|CDA|IIP|SDP)[\s#\-]*\d{2}-\d{3}\b")

# "VA" after a comma is usually the Virginia state abbreviation.
VA_CONTEXT_RE = re.compile(
    r"(?i:veterans?['\u2019]?\s+affairs|veterans\s+health|department\s+of\s+veterans)"
    r"|\bVHA\b|(?<!,\s)\bVA\b|\bDVA\b|\bVAMC\b|\bVISN\b"
)
VA_AFFIL_RE = re.compile(
    r"(?i:veterans\s+affairs|veterans\s+health|veterans\s+administration|department\s+of\s+veterans"
    r"|VA\s+(?:medical|health\s*care|healthcare))"
    r"|\bVAMC\b|\bVAHCS\b|\bVISN\b|\bVA\s+(?:[A-Z][\w.]+\s+){1,3}(?:Health|Medical)"
)
SUPPORT_RE = re.compile(r"\b(?:support\w*|fund\w*|award\w*|grant\w*|merit|sponsor\w*|financ\w*)\b", re.I)
DISCLAIMER_RE = re.compile(
    r"\b(?:views?|opinions?|positions?|polic(?:y|ies)|official|endorse\w*|represent\w*|reflect\w*"
    r"|disclaim\w*|employ(?:ee|ed|ment)|conflicts? of interest|competing interests?|no funding"
    r"|not receive\w*|use of (?:the )?facilities|resources and (?:the )?use)\b", re.I)
ORD_GENERIC_RE = re.compile(
    r"Office of Research (?:and|&) Development|\bORD\b|Merit Review|Career Development Award|\bCDA\b"
    r"|Research Career Scientist|\bSPiRE\b|Million Veteran Program|\bMVP\b", re.I)
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.;])\s+|\n+")


def _snippet(text, limit=240):
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "\u2026"


def classify(record):
    """Return VA/ORD funding flags, ORD services and the evidence behind them."""
    evidence, services = [], set()
    state = {"va": False, "ord": False}

    def add(label, source, snippet, service=None):
        state["va"] = True
        if service:
            services.add(service)
            state["ord"] = True
        item = {"label": label, "source": source, "snippet": _snippet(snippet)}
        if item not in evidence:
            evidence.append(item)

    for m in GRANT_CODE_RE.finditer(record.get("grant_ids") or ""):
        svc = SERVICE_BY_CODE[m.group(1).upper()]
        add(svc, "Grant ID", m.group(0).strip(), svc)

    for funder in split_multi(record.get("funder")):
        matched = False
        for svc, rx in SERVICE_NAME_RES.items():
            if rx.search(funder):
                add(svc, "Funder", funder, svc)
                matched = True
        if not matched and VA_CONTEXT_RE.search(funder):
            add("VA", "Funder", funder)

    for field, source in (("funding_text", "Funding statement"), ("acknowledgements", "Acknowledgements")):
        text = clean_text(record.get(field))
        if not text:
            continue
        for m in GRANT_CODE_RE.finditer(text):
            svc = SERVICE_BY_CODE[m.group(1).upper()]
            add(svc, f"{source} (award number)", m.group(0).strip(), svc)
        for sentence in SENTENCE_SPLIT_RE.split(text):
            if DISCLAIMER_RE.search(sentence):
                continue
            if not (VA_CONTEXT_RE.search(sentence) and SUPPORT_RE.search(sentence)):
                continue
            found = False
            for svc, rx in SERVICE_NAME_RES.items():
                if rx.search(sentence):
                    add(svc, source, sentence, svc)
                    found = True
            if HSR_PROJECT_RE.search(sentence):
                add("HSR&D", f"{source} (HSR&D project number)", sentence, "HSR&D")
                found = True
            if not found and ORD_GENERIC_RE.search(sentence):
                add("ORD", source, sentence)
                state["ord"] = True
            elif not found:
                add("VA", source, sentence)

    ord_services = [s for s in SERVICE_ORDER if s in services]
    if state["ord"] and not ord_services:
        ord_services = [UNSPECIFIED]

    affil_text = " ".join(filter(None, [record.get("research_orgs"), record.get("affiliations")]))
    return {
        "va_affiliated": bool(VA_AFFIL_RE.search(affil_text)),
        "va_funded": state["va"],
        "ord_funded": state["ord"],
        "ord_services": ord_services,
        "funding_evidence": evidence,
    }
