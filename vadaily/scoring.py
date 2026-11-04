import re

HEALTH_FIELD_RE = re.compile(
    r"\b(?:3[12]|42|52|11)\d*\b|Medic|Health|Psych|Neuro|Biolog|Nursing|Pharm|Immun|Genetic|Clinical", re.I)


def _keyword_regex(keywords):
    parts = []
    for k in keywords:
        if k.startswith("re:"):
            parts.append(k[3:])
        else:
            parts.append(r"\b" + re.escape(k).replace(r"\*", r"\w*") + r"\b")
    return re.compile("|".join(f"(?:{p})" for p in parts), re.I)


class Scorer:
    def __init__(self, scoring_cfg):
        self.cfg = scoring_cfg
        self.topics = [(t["name"], t["weight"], _keyword_regex(t["keywords"])) for t in scoring_cfg["topics"]]
        self.designs = [(d["name"], d["weight"], _keyword_regex(d["keywords"])) for d in scoring_cfg["study_designs"]]
        vt = scoring_cfg["veteran_in_title"]
        self.veteran_title = (vt["weight"], _keyword_regex(vt["keywords"]))

    def score(self, r):
        c = self.cfg
        total, reasons = 0, []

        def bump(points, reason):
            nonlocal total
            total += points
            reasons.append(f"{points:+d} {reason}")

        title = r.get("title") or ""
        text = " ".join(filter(None, [title, r.get("abstract"), r.get("mesh_terms"), r.get("doc_type")]))

        topic_hit = False
        for name, weight, rx in self.topics:
            if rx.search(text):
                bump(weight, f"Topic: {name}")
                topic_hit = True
        for name, weight, rx in self.designs:
            if rx.search(text):
                bump(weight, f"Design: {name}")
        weight, rx = self.veteran_title
        if rx.search(title):
            bump(weight, "Veterans/military in title")

        jt = c["journal_tiers"]
        if r.get("journal_tier") == "Top":
            bump(jt["top_weight"], f"Top-tier journal: {r.get('journal')}")
        elif r.get("journal_tier") == "Mid":
            bump(jt["mid_weight"], f"Mid-tier journal: {r.get('journal')}")

        if r.get("ord_funded"):
            bump(c["funding"]["ord_funded"], "ORD funded")
        elif r.get("va_funded"):
            bump(c["funding"]["va_funded_only"], "VA funded")

        oa = (r.get("open_access") or "").lower()
        if r.get("oa_url") or ("oa" in oa and "closed" not in oa):
            bump(c["other"]["open_access"], "Open access")
        if (r.get("times_cited") or 0) >= 5:
            bump(c["other"]["cited_5_plus"], "Cited 5+ times")

        p = c["penalties"]
        kind = f"{r.get('pub_type') or ''} {r.get('doc_type') or ''}".lower()
        if "preprint" in kind:
            bump(p["preprint"], "Preprint")
        if "conference abstract" in kind or "meeting abstract" in kind:
            bump(p["conference_abstract"], "Conference abstract")
        if re.search(r"editorial|letter|comment", kind):
            bump(p["editorial_or_letter"], "Editorial/letter/comment")
        if re.search(r"erratum|correction", kind) or re.match(r"(?i)corrigendum|erratum", title):
            bump(p["erratum"], "Correction/erratum")
        if r.get("retraction"):
            bump(p["retracted"], "Retraction or notice")
        if not (topic_hit or r.get("mesh_terms") or HEALTH_FIELD_RE.search(r.get("fields_of_research") or "")):
            bump(p["non_health"], "No health/veteran signals")

        tiers = c["tiers"]
        tier = "High" if total >= tiers["high"] else "Medium" if total >= tiers["medium"] else "Low"
        return total, tier, reasons
