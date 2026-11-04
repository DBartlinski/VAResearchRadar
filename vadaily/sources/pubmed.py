import os
import re
import time
import xml.etree.ElementTree as ET

from ..records import build_author_affiliations, empty_record
from ..utils import best_date, normalize_doi
from .http import make_session

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
BATCH = 200
MAX_RECORDS = 9999  # esearch history paging limit
_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def _text(el):
    return " ".join("".join(el.itertext()).split()) if el is not None else ""


def _date(el):
    if el is None:
        return None
    y, m, d = el.findtext("Year"), el.findtext("Month"), el.findtext("Day")
    if not y:
        mm = re.match(r"(\d{4})(?:\s+([A-Za-z]{3}))?", el.findtext("MedlineDate") or "")
        if not mm:
            return None
        y, m, d = mm.group(1), mm.group(2), None
    parts = [y]
    if m:
        mi = int(m) if m.isdigit() else _MONTHS.get(m[:3].lower())
        if mi:
            parts.append(f"{mi:02d}")
            if d and d.isdigit():
                parts.append(f"{int(d):02d}")
    return "-".join(parts)


def parse_article(art):
    rec = empty_record("pubmed")
    cit = art.find("MedlineCitation")
    article = cit.find("Article")
    rec["pmid"] = cit.findtext("PMID")
    rec["title"] = _text(article.find("ArticleTitle")) or None

    abstract_parts = []
    for a in article.findall("Abstract/AbstractText"):
        label = a.get("Label")
        body = _text(a)
        abstract_parts.append(f"{label}: {body}" if label else body)
    rec["abstract"] = "\n".join(abstract_parts) or None

    rec["journal"] = article.findtext("Journal/Title")
    issns = [article.findtext("Journal/ISSN"), cit.findtext("MedlineJournalInfo/ISSNLinking")]
    rec["issn"] = "; ".join(dict.fromkeys(i for i in issns if i)) or None
    rec["pub_date"] = best_date(_date(article.find("ArticleDate")),
                                _date(article.find("Journal/JournalIssue/PubDate")))

    authors, affils, pairs = [], [], []
    for au in article.findall("AuthorList/Author"):
        name = au.findtext("CollectiveName") or ", ".join(
            filter(None, [au.findtext("LastName"), au.findtext("ForeName") or au.findtext("Initials")]))
        if name:
            authors.append(name)
        own = []
        for af in au.findall("AffiliationInfo/Affiliation"):
            t = _text(af)
            if t:
                own.append(t)
            if t and t not in affils:
                affils.append(t)
        if name:
            pairs.append((name, own))
    rec["authors"] = "; ".join(authors) or None
    rec["affiliations"] = "; ".join(affils) or None
    rec["author_affiliations"] = build_author_affiliations(pairs)

    rec["mesh_terms"] = "; ".join(_text(d) for d in cit.findall("MeshHeadingList/MeshHeading/DescriptorName")) or None

    grant_ids, agencies = [], []
    for g in article.findall("GrantList/Grant"):
        if g.findtext("GrantID"):
            grant_ids.append(g.findtext("GrantID"))
        if g.findtext("Agency"):
            agencies.append(g.findtext("Agency"))
    rec["grant_ids"] = "; ".join(grant_ids) or None
    rec["funder"] = "; ".join(dict.fromkeys(agencies)) or None

    types = [_text(t) for t in article.findall("PublicationTypeList/PublicationType")]
    rec["doc_type"] = "; ".join(types) or None
    rec["pub_type"] = "Preprint" if "Preprint" in types else "Article"

    for aid in art.findall("PubmedData/ArticleIdList/ArticleId"):
        kind = aid.get("IdType")
        if kind == "doi":
            rec["doi"] = normalize_doi(aid.text)
        elif kind == "pmc":
            rec["pmcid"] = aid.text
    return rec


def fetch(cfg, since, until, log=print):
    """Fetch PubMed records added (Entrez date) between since and until."""
    pc = cfg["pubmed"]
    s = make_session(cfg.get("contact_email", ""))
    api_key = os.environ.get("NCBI_API_KEY")
    base = {"tool": "vadaily", "email": cfg.get("contact_email") or None, "api_key": api_key}
    delay = 0.12 if api_key else 0.4

    r = s.post(EUTILS + "esearch.fcgi", data={
        **base, "db": "pubmed", "term": " ".join(pc["query"].split()), "datetype": "edat",
        "mindate": since.strftime("%Y/%m/%d"), "maxdate": until.strftime("%Y/%m/%d"),
        "usehistory": "y", "retmax": 0, "retmode": "json",
    }, timeout=60)
    r.raise_for_status()
    result = r.json()["esearchresult"]
    count = int(result.get("count", 0))
    log(f"PubMed: {count} records since {since}")
    if count > MAX_RECORDS:
        log(f"PubMed: only the first {MAX_RECORDS} will be fetched; reduce lookback_days")

    records = []
    for start in range(0, min(count, MAX_RECORDS), BATCH):
        time.sleep(delay)
        r = s.post(EUTILS + "efetch.fcgi", data={
            **base, "db": "pubmed", "query_key": result["querykey"], "WebEnv": result["webenv"],
            "retstart": start, "retmax": BATCH, "retmode": "xml",
        }, timeout=120)
        r.raise_for_status()
        root = ET.fromstring(r.content)
        records.extend(parse_article(a) for a in root.iter("PubmedArticle"))
    return records
