from vadaily.records import group_records, merge_records
from vadaily.utils import best_date, normalize_doi


def test_best_date_prefers_first_day_precise():
    assert best_date("", "2027-01", "2026-12-15") == "2026-12-15"
    assert best_date("2026-10-29", "2027-01") == "2026-10-29"
    assert best_date(None, "2026-11", "2026") == "2026-11-01"


def test_normalize_doi():
    assert normalize_doi("https://doi.org/10.1000/XYZ") == "10.1000/xyz"


def test_merge_by_doi_and_pmid_with_pubmed_priority():
    pm = {"sources": ["pubmed"], "doi": "10.1/a", "pmid": "55", "title": "PubMed title",
          "funder": "BLRD VA", "mesh_terms": "Veterans", "first_seen": "2026-11-05T09:00:00"}
    oa = {"sources": ["openalex"], "doi": None, "pmid": "55", "oa_url": "https://x", "funder": "VA",
          "first_seen": "2026-11-04T09:00:00"}
    other = {"sources": ["openalex"], "doi": "10.9/z", "title": "Other"}
    groups = group_records([pm, oa, other])
    assert len(groups) == 2
    merged = merge_records(next(g for g in groups if len(g) == 2))
    assert merged["title"] == "PubMed title"
    assert merged["pmid"] == "55"
    assert merged["oa_url"] == "https://x"
    assert merged["funder"] == "BLRD VA; VA"
    assert merged["sources"] == ["pubmed", "openalex"]
    assert merged["first_seen"] == "2026-11-04T09:00:00"
