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

VA_EXTRA_RE = re.compile(r"(?i)\bVeterans['\u2019]?\s+(?:Memorial\s+)?(?:Hospital|Medical)|\bVA\s+(?:Hospital|Clinic|Outpatient)")
# A bare agency name with no place, e.g. "Department of Veterans Affairs Medical Center".
GENERIC_FACILITY_RE = re.compile(
    r"(?i)^(?:(?:the )?(?:U\.?S\.? )?Department of )?(?:Veterans Affairs|VA|Veterans Health Administration|Veterans Administration)"
    r"(?: (?:Medical Cent(?:er|re)|Health ?care System|Health System))?$")
PLACE_SKIP_RE = re.compile(r"(?i)^(?:[A-Z]{2}|USA|U\.S\.A\.?|United States(?: of America)?)$|\d")
DEPARTMENT_WORD_RE = re.compile(
    r"(?i)\b(?:service|department|division|center|institute|school|program|office|section|unit|university)\b")
MAX_FACILITY_LEN = 100


def is_va_affiliation(text):
    return bool(VA_AFFIL_RE.search(text) or VA_EXTRA_RE.search(text))


_NAME_WORD = r"[A-Z][\w.'\u2019-]*"
# Facility phrases inside affiliations that have no comma separators.
FACILITY_PHRASE_RES = [
    re.compile(rf"(?:Department of )?Veterans Affairs(?: {_NAME_WORD}){{1,5}} Health ?[Cc]are System"),
    re.compile(rf"\bVA(?: {_NAME_WORD}){{1,5}} Health ?[Cc]are System"),
    re.compile(rf"(?:{_NAME_WORD} ){{1,4}}(?:VA|Veterans Affairs|Veterans) (?:Medical Cent(?:er|re)|Hospital)"),
]


def facility_name(affil):
    """Return (facility, cleaned); cleaned is False when only the raw affiliation text could be used."""
    text = " ".join(re.sub(r"\([^)]*\)", " ", affil).split())
    parts = [p.strip(" .") for p in re.split(r"[;,]", text)]
    parts = [p for p in parts if p]
    for i, p in enumerate(parts):
        if " and " in p:
            tail = p.rsplit(" and ", 1)[1]
            if is_va_affiliation(tail) and not GENERIC_FACILITY_RE.match(tail):
                p = tail
        if not is_va_affiliation(p) or len(p) > MAX_FACILITY_LEN:
            continue
        if not GENERIC_FACILITY_RE.match(p):
            return p, True
        nxt = parts[i + 1] if i + 1 < len(parts) else ""
        if nxt and len(nxt) <= 40 and not PLACE_SKIP_RE.search(nxt) and not DEPARTMENT_WORD_RE.search(nxt):
            return f"{p}, {nxt}", True
    for rx in FACILITY_PHRASE_RES:
        m = rx.search(text)
        if m:
            return m.group(0).strip(" ."), True
    raw = " ".join(affil.split())
    # Start the raw text at the first VA part so long multi-institution strings stay readable.
    va_part = next((p for p in parts if is_va_affiliation(p)), None)
    pos = raw.find(va_part[:30]) if va_part else -1
    if pos > 0:
        raw = raw[pos:]
    return (raw if len(raw) <= 160 else raw[:159] + "\u2026"), False


def first_va_author(record):
    """Indexes of VA affiliations plus the first author with one, with a cleaned facility name."""
    aa = record.get("author_affiliations") or {}
    affils = aa.get("affiliations") or []
    va_idx = [i for i, a in enumerate(affils) if is_va_affiliation(a)]
    va_set = set(va_idx)
    for au in aa.get("authors") or []:
        hit = next((i for i in au["aff"] if i in va_set), None)
        if hit is not None:
            facility, cleaned = facility_name(affils[hit])
            return va_idx, {"name": au["name"], "facility": facility, "cleaned": cleaned}
    return va_idx, None


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
    va_idx, first_va = first_va_author(record)
    return {
        "va_affiliated": bool(VA_AFFIL_RE.search(affil_text)),
        "va_affil_idx": va_idx,
        "first_va_author": first_va,
        "va_funded": state["va"],
        "ord_funded": state["ord"],
        "ord_services": ord_services,
        "funding_evidence": evidence,
    }
