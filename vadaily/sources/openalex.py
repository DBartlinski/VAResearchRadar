import os
import time

import requests

from ..records import build_author_affiliations, empty_record
from ..utils import normalize_doi, normalize_pmid
from .http import make_session

BASE = "https://api.openalex.org"
MAX_PAGES = 100
PER_PAGE = 100


def _params(cfg, **extra):
    p = {"mailto": cfg.get("contact_email") or None, "api_key": os.environ.get("OPENALEX_API_KEY")}
    p.update(extra)
    return p


def _resolve(s, cfg, entity, search, must_contain):
    r = s.get(f"{BASE}/{entity}", params=_params(cfg, search=search, per_page=10), timeout=60)
    r.raise_for_status()
    hits = [h for h in r.json().get("results", []) if must_contain in (h.get("display_name") or "").lower()]
    if not hits:
        return None
    best = max(hits, key=lambda h: h.get("works_count") or 0)
    return {"id": best["id"].rsplit("/", 1)[-1], "name": best["display_name"]}


def _abstract(inv):
    if not inv:
        return None
    words = {}
    for word, positions in inv.items():
        for pos in positions:
            words[pos] = word
    return " ".join(words[i] for i in sorted(words)) or None


def parse_work(w):
    rec = empty_record("openalex")
    rec["openalex_id"] = (w.get("id") or "").rsplit("/", 1)[-1] or None
    rec["doi"] = normalize_doi(w.get("doi"))
    ids = w.get("ids") or {}
    rec["pmid"] = normalize_pmid(ids.get("pmid"))
    pmcid = ids.get("pmcid")
    rec["pmcid"] = pmcid.rstrip("/").rsplit("/", 1)[-1] if pmcid else None
    rec["title"] = w.get("display_name") or w.get("title")
    rec["abstract"] = _abstract(w.get("abstract_inverted_index"))
    loc = w.get("primary_location") or {}
    source = loc.get("source") or {}
    rec["journal"] = source.get("display_name")
    rec["issn"] = "; ".join(source.get("issn") or []) or None
    rec["source_linkout"] = loc.get("landing_page_url")
    rec["pub_date"] = w.get("publication_date")
    rec["pub_type"] = "Preprint" if w.get("type") == "preprint" else (w.get("type") or "").title() or None
    oa = w.get("open_access") or {}
    rec["oa_url"] = oa.get("oa_url")
    rec["open_access"] = oa.get("oa_status")
    rec["times_cited"] = w.get("cited_by_count")

    authors, affils, orgs, pairs = [], [], [], []
    for a in w.get("authorships") or []:
        name = (a.get("author") or {}).get("display_name")
        if name:
            authors.append(name)
        raw = a.get("raw_affiliation_strings") or []
        affils.extend(x for x in raw if x not in affils)
        inst_names = [i["display_name"] for i in a.get("institutions") or [] if i.get("display_name")]
        orgs.extend(n for n in inst_names if n not in orgs)
        if name:
            pairs.append((name, raw or inst_names))
    rec["authors"] = "; ".join(authors) or None
    rec["affiliations"] = "; ".join(affils) or None
    rec["research_orgs"] = "; ".join(orgs) or None
    rec["author_affiliations"] = build_author_affiliations(pairs)

    funders, awards = [], []
    for key in ("grants", "awards"):
        for g in w.get(key) or []:
            name = g.get("funder_display_name") or (g.get("funder") or {}).get("display_name")
            award = g.get("award_id") or g.get("funder_award_id")
            if name:
                funders.append(name)
            if award:
                awards.append(award)
    funders.extend(f.get("display_name") for f in w.get("funders") or [] if f.get("display_name"))
    rec["funder"] = "; ".join(dict.fromkeys(funders)) or None
    rec["grant_ids"] = "; ".join(dict.fromkeys(awards)) or None

    fields = {(t.get("field") or {}).get("display_name") for t in w.get("topics") or []}
    rec["fields_of_research"] = "; ".join(sorted(f for f in fields if f)) or None
    if w.get("is_retracted"):
        rec["retraction"] = "Retracted (OpenAlex)"
    return rec


def _works(s, cfg, filt, log):
    # Cursor paging needs an API key; without one, numbered pages work up to 10,000 results.
    use_cursor = bool(os.environ.get("OPENALEX_API_KEY"))
    cursor, page, out = "*", 1, []
    while page <= MAX_PAGES:
        paging = {"cursor": cursor} if use_cursor else {"page": page}
        r = s.get(f"{BASE}/works", params=_params(cfg, filter=filt, per_page=PER_PAGE, **paging), timeout=90)
        r.raise_for_status()
        data = r.json()
        results = data.get("results", [])
        out.extend(results)
        meta = data.get("meta") or {}
        if use_cursor:
            cursor = meta.get("next_cursor")
            if not cursor:
                break
        elif not results or len(out) >= (meta.get("count") or 0):
            break
        page += 1
        time.sleep(0.15)
    log(f"OpenAlex: {len(out)} works for {filt}")
    return out


def fetch(cfg, since, until, log=print):
    """Fetch OpenAlex works by VA institutions or VA funders published since `since`."""
    oc = cfg["openalex"]
    s = make_session(cfg.get("contact_email", ""))
    resolved = {"institutions": [], "funders": []}

    inst_ids = list(oc.get("institution_ids") or [])
    if not inst_ids:
        hit = _resolve(s, cfg, "institutions", "Department of Veterans Affairs", "veterans affairs")
        if hit:
            inst_ids = [hit["id"]]
            resolved["institutions"].append(hit)
    funder_ids = list(oc.get("funder_ids") or [])
    if not funder_ids:
        hit = _resolve(s, cfg, "funders", "Department of Veterans Affairs", "veterans affairs")
        if hit:
            funder_ids = [hit["id"]]
            resolved["funders"].append(hit)

    date_filter = f"from_publication_date:{since.isoformat()},to_publication_date:{until.isoformat()}"
    works = {}
    if inst_ids:
        for w in _works(s, cfg, f"authorships.institutions.lineage:{'|'.join(inst_ids)},{date_filter}", log):
            works[w["id"]] = w
    if funder_ids:
        # Funder filter name differs between OpenAlex API versions.
        for field in ("grants.funder", "funders.id"):
            try:
                for w in _works(s, cfg, f"{field}:{'|'.join(funder_ids)},{date_filter}", log):
                    works[w["id"]] = w
                break
            except requests.HTTPError as e:
                if e.response is None or e.response.status_code != 400:
                    raise
    return [parse_work(w) for w in works.values()], resolved
