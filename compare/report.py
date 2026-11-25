"""Write a Dimensions-vs-tool comparison report (CSV of gaps plus a Markdown summary).

Usage: python -m compare.report <dimensions export folder> [label]
The Dimensions export is capped at 500 rows, so tool records are only compared from the
earliest Dimensions date in the export onward.
"""
import csv
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path

from compare import loader
from vadaily.config import load_config, path_for

VA_RE = re.compile(r"veteran|\bVA\b|VAMC|\bVHA\b", re.I)


def _dimensions_evidence(folder):
    """Why Dimensions tags each record as VA: affiliation, funder-only or neither."""
    out = {}
    for path in sorted(Path(folder).rglob("*.csv")):
        for row in loader._read_rows(path):
            if VA_RE.search(row.get("Research Organizations - standardized", "") + row.get("Authors (Raw Affiliation)", "")):
                why = "VA affiliation"
            elif VA_RE.search(row.get("Funder", "")):
                why = "VA funder only"
            else:
                why = "no VA signal in export"
            out[row.get("Publication ID", "")] = why
    return out


def main(folder, label=None):
    cfg = load_config()
    loader.DIM_FOLDER = Path(folder)
    res = loader.build()
    all_dim = [m["dim"] for m in res["matched"]] + res["only_dim"]
    start = min(d["date"] for d in all_dim)
    tool_window = loader.load_tool(cfg, start)
    why = _dimensions_evidence(folder)
    label = label or date.today().isoformat()
    reports = path_for(cfg, "reports")

    gaps = res["only_dim"]
    real = [d for d in gaps if not d["note"]]
    matched, dim_total = len(res["matched"]), res["dim_total"]
    artifacts = len(gaps) - len(real)
    tool_only = sum(1 for t in res["only_tool"] if t["date"] >= start)
    cause = Counter(why.get(d["dim_id"], "?") for d in real)

    with open(reports / f"dimensions-gaps-{label}.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["dim_id", "doi", "pmid", "title", "journal", "type", "date", "date_artifact", "why_dimensions_tags_va", "url"])
        for d in gaps:
            w.writerow([d["dim_id"], d["doi"], d["pmid"], d["title"], d["journal"], d["type"], d["date"],
                        d["note"], why.get(d["dim_id"], ""), d["url"]])

    lines = [
        f"# Dimensions comparison {label}",
        "",
        f"Dimensions export window starts {start} (export capped at 500 rows). Tool records compared: {len(tool_window)}.",
        "",
        "| Measure | Value |",
        "|---|---|",
        f"| Dimensions records in window | {dim_total} |",
        f"| Matched in tool | {matched} |",
        f"| Recall | {100 * matched / dim_total:.1f}% |",
        f"| Date artifacts (OpenAlex date before start) | {artifacts} |",
        f"| Recall excluding date artifacts | {100 * matched / (dim_total - artifacts):.1f}% |",
        f"| Real gaps | {len(real)} |",
        f"| Tool-only records in window | {tool_only} |",
        "",
        "## Real gaps by why Dimensions tags them VA",
        "",
    ] + [f"- {k}: {v}" for k, v in cause.most_common()]
    (reports / f"dimensions-comparison-{label}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    main(*sys.argv[1:3])
