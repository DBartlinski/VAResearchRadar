from vadaily.funding import classify, facility_name
from vadaily.records import build_author_affiliations


def test_facility_cleaned_from_department_prefix():
    raw = "Department of Medicine, VA Boston Healthcare System, Boston, MA, USA."
    assert facility_name(raw) == ("VA Boston Healthcare System", True)


def test_generic_agency_gets_place_from_next_segment():
    raw = "Department of Veterans Affairs Medical Center, Durham, NC"
    assert facility_name(raw) == ("Department of Veterans Affairs Medical Center, Durham", True)


def test_unparseable_facility_falls_back_to_raw():
    raw = "Department of Veterans Affairs, Research Service, Unknown"
    assert facility_name(raw) == (raw, False)


def test_first_va_author_skips_non_va_authors():
    aa = build_author_affiliations([
        ("Lee, A", ["Harvard Medical School, Boston, MA"]),
        ("Kim, B", ["Hines VA Hospital, Hines, IL", "Northwestern University"]),
        ("Roe, C", ["VA Palo Alto Health Care System, Palo Alto, CA"]),
    ])
    r = classify({"author_affiliations": aa})
    assert r["first_va_author"]["name"] == "Kim, B"
    assert r["va_affil_idx"] == [1, 3]
    assert r["first_va_author"]["facility"].startswith("Hines VA Hospital")


def test_no_affiliations_gives_none():
    assert build_author_affiliations([("Lee, A", [])]) is None
    assert classify({})["first_va_author"] is None
