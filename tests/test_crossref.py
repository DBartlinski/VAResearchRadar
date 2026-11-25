from vadaily.sources.crossref import _has_va_affiliation, parse_item


ITEM = {
    "DOI": "10.1161/CIRC.154.SUPPL_1.9207",
    "title": ["Abstract 9207: Test"],
    "container-title": ["Circulation"],
    "type": "proceedings-article",
    "published": {"date-parts": [[2026, 11]]},
    "author": [{"given": "Ann", "family": "Lee", "affiliation": [{"name": "VA Boston Healthcare System, Boston, MA"}]}],
    "funder": [{"name": "U.S. Department of Veterans Affairs", "award": ["I01 HX001234"]}],
    "abstract": "<jats:p>Hello <jats:italic>world</jats:italic></jats:p>",
}


def test_parse_item():
    rec = parse_item(ITEM)
    assert rec["doi"] == "10.1161/circ.154.suppl_1.9207"
    assert rec["pub_date"] == "2026-11-01"
    assert rec["pub_type"] == "Conference-Abstract"
    assert rec["authors"] == "Ann Lee"
    assert rec["grant_ids"] == "I01 HX001234"
    assert rec["abstract"] == "Hello world"
    assert rec["sources"] == ["crossref"]


def test_va_affiliation_filter():
    assert _has_va_affiliation(ITEM)
    other = {"author": [{"affiliation": [{"name": "University of Virginia, Charlottesville, VA"}]}]}
    assert not _has_va_affiliation(other)
