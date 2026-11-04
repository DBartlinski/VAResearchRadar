from vadaily.funding import UNSPECIFIED, classify


def rec(**kw):
    base = {"funder": None, "grant_ids": None, "funding_text": None, "acknowledgements": None,
            "research_orgs": None, "affiliations": None}
    base.update(kw)
    return base


def test_grant_id_codes_map_to_services():
    r = classify(rec(grant_ids="R01AG085279; I01BX004251; IK2CX002629; 1IK6HX003762; RX003225"))
    assert r["ord_services"] == ["BLR&D", "CSR&D", "HSR&D", "RR&D"]
    assert r["va_funded"] and r["ord_funded"]


def test_award_numbers_with_spaces_and_dashes_in_text():
    r = classify(rec(funding_text="Supported by grant I21 BX002664-12 and VA award HX0003205\u201001 and IK2 RX003823."))
    assert r["ord_services"] == ["BLR&D", "HSR&D", "RR&D"]


def test_service_name_in_funder_field():
    r = classify(rec(funder="United States Department of Veterans Affairs; Rehabilitation Research and Development Service"))
    assert r["ord_services"] == ["RR&D"]


def test_hsrd_project_number_and_new_name():
    r = classify(rec(funding_text="This work was supported by the Department of Veterans Affairs, Health Systems Research (HSR), IIR 21-163."))
    assert r["ord_services"] == ["HSR&D"]


def test_disclaimer_is_not_funding():
    r = classify(rec(funding_text="The views expressed are those of the authors and do not represent the position or policy of the Department of Veterans Affairs."))
    assert not r["va_funded"]


def test_facilities_only_is_not_funding():
    r = classify(rec(acknowledgements="This material is the result of work supported with resources and use of facilities at the Ann Arbor VA Medical Center."))
    assert not r["va_funded"]


def test_generic_ord_support_without_service():
    r = classify(rec(funding_text="Dr. Smith is supported by a VA Merit Review award."))
    assert r["ord_funded"] and r["ord_services"] == [UNSPECIFIED]


def test_va_funded_without_ord():
    r = classify(rec(funding_text="Nasia Safdar is also supported by the Department of Veterans Affairs."))
    assert r["va_funded"] and not r["ord_funded"]


def test_virginia_is_not_va():
    r = classify(rec(funding_text="Supported by the Smith Foundation, Richmond, VA."))
    assert not r["va_funded"]


def test_non_va_ord_acronym_ignored():
    r = classify(rec(funding_text="Funded by CHIST-ERA grant CHIST-ERA-22-ORD-02."))
    assert not r["ord_funded"]


def test_pubmed_agency_names():
    r = classify(rec(funder="BLRD VA; NIA NIH HHS", grant_ids="I01 BX004146"))
    assert r["ord_services"] == ["BLR&D"]


def test_va_affiliation():
    assert classify(rec(affiliations="Smith, J (VA Boston Healthcare System)"))["va_affiliated"]
    assert classify(rec(research_orgs="Veterans Health Administration"))["va_affiliated"]
    assert not classify(rec(affiliations="University of Virginia, Charlottesville, VA"))["va_affiliated"]
