import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "compare"))

from loader import match  # noqa: E402


def rec(side, **kw):
    base = {"side": side, "id": "x", "doi": None, "pmid": None, "dim_id": None, "title": "", "journal": "",
            "type": "", "date": "2026-10-05", "sources": "", "url": ""}
    return {**base, **kw}


def test_match_by_each_key_and_title_fallback():
    long_title = "A sufficiently long publication title about veterans"
    tool = [rec("tool", doi="10.1/a"), rec("tool", pmid="2"), rec("tool", dim_id="pub.3"),
            rec("tool", title=long_title), rec("tool", doi="10.1/zzz")]
    dim = [rec("dim", doi="10.1/a"), rec("dim", pmid="2"), rec("dim", dim_id="pub.3"),
           rec("dim", title=long_title.upper() + "."), rec("dim", doi="10.1/only")]
    res = match(tool, dim)
    assert [m["by"] for m in res["matched"]] == ["DOI", "PMID", "Dimensions ID", "Title"]
    assert len(res["only_tool"]) == 1 and len(res["only_dim"]) == 1


def test_one_dimensions_record_matches_once():
    res = match([rec("tool", doi="10.1/a"), rec("tool", doi="10.1/a")], [rec("dim", doi="10.1/a")])
    assert len(res["matched"]) == 1 and len(res["only_tool"]) == 1
