from vadaily.config import load_config
from vadaily.journals import JournalTiers
from vadaily.scoring import Scorer

TIER_CFG = {"top_min_citedness": 10, "mid_min_citedness": 4, "always_top": ["JAMA"], "always_mid": []}
CACHE = {
    "1111-1111": {"citedness": 15.2, "source_type": "journal"},
    "2222-2222": {"citedness": 5.0, "source_type": "journal"},
    "3333-3333": {"citedness": 1.1, "source_type": "journal"},
    "4444-4444": {"citedness": 2.0, "source_type": "repository"},
}


def test_journal_tiers():
    jt = JournalTiers(TIER_CFG, CACHE)
    assert jt.assign({"journal": "X", "issn": "1111-1111"})[0] == "Top"
    assert jt.assign({"journal": "X", "issn": "9999-9999; 2222-2222"})[0] == "Mid"
    assert jt.assign({"journal": "X", "issn": "3333-3333"})[0] == "Lower"
    assert jt.assign({"journal": "JAMA", "issn": "3333-3333"})[0] == "Top"
    assert jt.assign({"journal": "medRxiv", "issn": "1111-1111"})[0] == "Preprint"
    assert jt.assign({"journal": "Repo", "issn": "4444-4444"})[0] == "Lower"
    assert jt.assign({"journal": "PubMed", "issn": "1111-1111"}) == ("Not rated", None)
    assert jt.assign({"journal": "Y", "pub_type": "Preprint"})[0] == "Preprint"
    assert jt.assign({"journal": "Unknown", "issn": None}) == ("Not rated", None)


def test_scoring_tiers_and_reasons():
    scorer = Scorer(load_config()["scoring"])
    strong = {"title": "Suicide prevention among veterans: a randomized clinical trial", "abstract": "",
              "journal": "JAMA Psychiatry", "journal_tier": "Top", "ord_funded": True, "fields_of_research": "42 Health Sciences"}
    score, tier, reasons = scorer.score(strong)
    assert tier == "High"
    assert any("Suicide" in r for r in reasons)
    assert any("Randomized" in r for r in reasons)

    weak = {"title": "Catalyst design for CO2 reduction", "abstract": "", "journal": "Applied Catalysis B",
            "pub_type": "Article", "doc_type": "Research Article", "fields_of_research": "34 Chemical Sciences"}
    score, tier, reasons = scorer.score(weak)
    assert tier == "Low"
    assert any("No health" in r for r in reasons)

    erratum = {"title": "Corrigendum to something", "doc_type": "Correction Erratum"}
    assert scorer.score(erratum)[0] < 0
