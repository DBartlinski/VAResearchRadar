import html
import re
from datetime import date

_DATE_RE = re.compile(r"^\s*(\d{4})(?:-(\d{1,2}))?(?:-(\d{1,2}))?")


def parse_date(value):
    """Return (iso_date, precision) with precision 0=none, 1=year, 2=month, 3=day."""
    if not value:
        return None, 0
    m = _DATE_RE.match(str(value))
    if not m:
        return None, 0
    y, mo, d = m.groups()
    try:
        if d:
            return date(int(y), int(mo), int(d)).isoformat(), 3
        if mo:
            return date(int(y), int(mo), 1).isoformat(), 2
        return date(int(y), 1, 1).isoformat(), 1
    except ValueError:
        return None, 0


def best_date(*values):
    """First day-precise date in order, otherwise the most precise one available."""
    best, best_p = None, 0
    for v in values:
        iso, p = parse_date(v)
        if p == 3:
            return iso
        if p > best_p:
            best, best_p = iso, p
    return best


def normalize_doi(doi):
    if not doi:
        return None
    d = str(doi).strip().lower()
    d = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", d)
    return d or None


def normalize_pmid(pmid):
    if not pmid:
        return None
    digits = re.sub(r"\D", "", str(pmid).rsplit("/", 1)[-1])
    return digits or None


def clean_text(value):
    if not value:
        return ""
    return html.unescape(str(value)).replace("\r\n", "\n").strip()


def split_multi(value):
    if not value:
        return []
    return [p.strip() for p in str(value).split(";") if p.strip()]


def join_unique(*values):
    seen, out = set(), []
    for v in values:
        for part in split_multi(v):
            k = part.lower()
            if k not in seen:
                seen.add(k)
                out.append(part)
    return "; ".join(out)


def to_number(value):
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
