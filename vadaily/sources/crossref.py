import re

from ..funding import VA_AFFIL_RE
from ..records import empty_record
from ..utils import normalize_doi
from .http import make_session

BASE = "https://api.crossref.org/works"
ROWS = 500
MAX_AFFIL_PAGES = 20
TYPE_LABELS = {"journal-article": "Article", "posted-content": "Preprint", "proceedings-article": "Conference-Abstract",
               "book-chapter": "Book Chapter", "review": "Review"}
_TAG_RE = re.compile(r"<[^>]+>")


def _date(parts):
    nums = ((parts or {}).get("date-parts") or [[None]])[0]
    if not nums or not nums[0]:
        return None
    y, m, d = (list(nums) + [1, 1])[:3]
    return f"{y:04d}-{(m or 1):02d}-{(d or 1):02d}"


def _text(v):
    return " ".join(_TAG_RE.sub(" ", v or "").split()) or None


def parse_item(it):
    rec = empty_record("crossref")
    rec["doi"] = normalize_doi(it.get("DOI"))
    rec["title"] = _text((it.get("title") or [None])[0])
    rec["abstract"] = _text(it.get("abstract"))
    rec["journal"] = _text((it.get("container-title") or [None])[0])
    rec["issn"] = "; ".join(it.get("ISSN") or []) or None
    rec["publisher"] = it.get("publisher")
    rec["pub_type"] = TYPE_LABELS.get(it.get("type"), (it.get("type") or "").replace("-", " ").title() or None)
    rec["pub_date"] = _date(it.get("published")) or _date(it.get("issued"))
    rec["times_cited"] = it.get("is-referenced-by-count")
    rec["source_linkout"] = it.get("URL")

    authors, affils = [], []
    for a in it.get("author") or []:
        name = " ".join(filter(None, [a.get("given"), a.get("family")])) or a.get("name")
        if name:
            authors.append(name)
        affils.extend(x["name"] for x in a.get("affiliation") or [] if x.get("name") and x["name"] not in affils)
    rec["authors"] = "; ".join(authors) or None
    rec["affiliations"] = "; ".join(affils) or None

    funders, awards = [], []
    for f in it.get("funder") or []:
        if f.get("name"):
            funders.append(f["name"])
        awards.extend(f.get("award") or [])
    rec["funder"] = "; ".join(dict.fromkeys(funders)) or None
    rec["grant_ids"] = "; ".join(dict.fromkeys(awards)) or None
    return rec


def _page(s, cfg, params):
    p = {"rows": ROWS, "mailto": cfg.get("contact_email") or None, **params}
    r = s.get(BASE, params=p, timeout=120)
    r.raise_for_status()
    return r.json()["message"]


def _cursor_items(s, cfg, params, max_pages=None, keep=None):
    cursor, out, pages = "*", [], 0
    while True:
        msg = _page(s, cfg, {**params, "cursor": cursor})
        items = msg.get("items") or []
        pages += 1
        kept = [i for i in items if keep is None or keep(i)]
        out.extend(kept)
        if not items or (keep is not None and not kept) or (max_pages and pages >= max_pages):
            break
        cursor = msg.get("next-cursor")
        if not cursor:
            break
    return out


def _has_va_affiliation(item):
    text = " ".join(x.get("name", "") for a in item.get("author") or [] for x in a.get("affiliation") or [])
    return bool(VA_AFFIL_RE.search(text))


def fetch(cfg, since, until, log=print):
    """Fetch Crossref works funded by VA, or whose deposited author affiliations name VA."""
    cc = cfg.get("crossref", {})
    s = make_session(cfg.get("contact_email", ""))
    dates = f"from-pub-date:{since.isoformat()},until-pub-date:{until.isoformat()}"
    items = {}
    trusted = set()
    for fid in cc.get("funder_dois") or []:
        found = _cursor_items(s, cfg, {"filter": f"funder:{fid},{dates}", "select": SELECT})
        log(f"Crossref: {len(found)} works for funder {fid}")
        items.update({i["DOI"].lower(): i for i in found})
        trusted.update(i["DOI"].lower() for i in found)
    for term in cc.get("affiliation_queries") or []:
        # Results are relevance ranked, so paging stops at the first page with no VA affiliation.
        found = _cursor_items(s, cfg, {"query.affiliation": term, "filter": dates, "select": SELECT},
                              MAX_AFFIL_PAGES, _has_va_affiliation)
        log(f"Crossref: {len(found)} works for affiliation '{term}'")
        items.update({i["DOI"].lower(): i for i in found})
    out = []
    for doi, i in items.items():
        rec = parse_item(i)
        rec["va_trusted"] = doi in trusted
        out.append(rec)
    return out


SELECT = ("DOI,title,abstract,container-title,ISSN,publisher,type,published,issued,"
          "is-referenced-by-count,URL,author,funder")
