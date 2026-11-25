"""Load the tool's PubMed/OpenAlex records and the Dimensions CSVs, then match them (read-only)."""
import csv
import json
import re
import sqlite3
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from vadaily.config import load_config, path_for  # noqa: E402
from vadaily.sources.http import make_session  # noqa: E402
from vadaily.utils import best_date, normalize_doi, normalize_pmid  # noqa: E402

DIM_FOLDER = ROOT / "Dimensions comparison"
OA_CACHE = ROOT / "compare" / "oa_dates_cache.json"
csv.field_size_limit(sys.maxsize)
# Dimensions carries future-dated records the tool cannot have yet.
END = date.today().isoformat()


def norm_title(t):
    return re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).strip()


def load_tool(cfg, start):
    con = sqlite3.connect(f"file:{path_for(cfg, 'database')}?mode=ro", uri=True)
    out = []
    for (raw,) in con.execute("SELECT record FROM publications"):
        r = json.loads(raw)
        srcs = r.get("sources") or []
        if not ({"pubmed", "openalex", "crossref"} & set(srcs)):
            continue
        if not start <= (r.get("pub_date") or "") <= END:
            continue
        out.append({"side": "tool", "id": r.get("key"), "doi": normalize_doi(r.get("doi")),
                    "pmid": normalize_pmid(r.get("pmid")), "dim_id": r.get("dimensions_id"),
                    "title": r.get("title") or "", "journal": r.get("journal") or "",
                    "type": r.get("pub_type") or "", "date": r.get("pub_date") or "",
                    "sources": ", ".join(srcs), "url": r.get("source_linkout") or r.get("oa_url") or ""})
    con.close()
    return out


def _read_rows(path):
    """Yield dict rows, skipping any preamble lines above the 'Publication ID' header."""
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        header = None
        for i, row in enumerate(reader):
            if "Publication ID" in row:
                header = [c.strip() for c in row]
                break
            if i > 10:
                raise ValueError(f"No header row in {path}")
        if header is None:
            return
        idx = {c: i for i, c in enumerate(header)}
        for row in reader:
            yield {c: (row[i].strip() if i < len(row) else "") for c, i in idx.items()}


def load_dimensions(folder, start):
    seen, files = {}, []
    for path in sorted(Path(folder).rglob("*.csv")):
        if not path.is_file():
            continue
        n = 0
        for row in _read_rows(path):
            n += 1
            pid = row.get("Publication ID", "")
            if not pid or pid in seen:
                continue
            date = best_date(row.get("Publication date (online)"), row.get("Publication date"),
                             row.get("Publication date (print)"), row.get("PubYear")) or ""
            if date < start or date > END:
                continue
            seen[pid] = {"side": "dim", "id": pid, "doi": normalize_doi(row.get("DOI")),
                         "pmid": normalize_pmid(row.get("PMID")), "dim_id": pid,
                         "title": row.get("Title", ""), "journal": row.get("Source title", ""),
                         "type": row.get("Publication Type") or row.get("Document Type", ""),
                         "date": date, "sources": "dimensions",
                         "url": row.get("Dimensions for Veterans Affairs URL", "")}
        files.append({"file": path.name, "rows": n})
    return list(seen.values()), files


def match(tool, dim):
    """Pair tool and Dimensions records by DOI, PMID or Dimensions ID, then by exact title."""
    idx = {}
    titles = {}
    for i, d in enumerate(dim):
        for k in (("doi", d["doi"]), ("pmid", d["pmid"]), ("dim", d["dim_id"])):
            if k[1]:
                idx.setdefault(k, i)
        nt = norm_title(d["title"])
        if len(nt) > 25:
            titles.setdefault(nt, i)

    used, matched = set(), []
    for t in tool:
        j, how = None, None
        for name, key in (("DOI", ("doi", t["doi"])), ("PMID", ("pmid", t["pmid"])),
                          ("Dimensions ID", ("dim", t["dim_id"]))):
            if key[1] and key in idx and idx[key] not in used:
                j, how = idx[key], name
                break
        if j is None:
            nt = norm_title(t["title"])
            if nt in titles and titles[nt] not in used:
                j, how = titles[nt], "Title"
        if j is not None:
            used.add(j)
            matched.append({"tool": t, "dim": dim[j], "by": how})
    matched_tool = {id(m["tool"]) for m in matched}
    return {
        "matched": matched,
        "only_tool": [t for t in tool if id(t) not in matched_tool],
        "only_dim": [d for i, d in enumerate(dim) if i not in used],
    }


def _oa_dates(dois):
    """OpenAlex publication date per DOI (cached on disk; None when OpenAlex has no record)."""
    cache = json.loads(OA_CACHE.read_text()) if OA_CACHE.exists() else {}
    missing = [d for d in dois if d not in cache]
    if missing:
        s = make_session()
        for d in missing:
            try:
                r = s.get(f"https://api.openalex.org/works/doi:{d}", params={"select": "publication_date"}, timeout=30)
                cache[d] = r.json().get("publication_date") if r.status_code == 200 else None
            except Exception:
                continue
        OA_CACHE.write_text(json.dumps(cache))
    return cache


def build():
    cfg = load_config()
    start = str(cfg.get("start_date"))
    tool = load_tool(cfg, start)
    dim, files = load_dimensions(DIM_FOLDER, start)
    res = match(tool, dim)
    # Dimensions dates by issue/print date; OpenAlex by first publication, which can precede the start date.
    oa = _oa_dates([d["doi"] for d in res["only_dim"] if d["doi"]])
    for d in res["only_dim"]:
        od = oa.get(d["doi"])
        d["note"] = f"Date mismatch: OpenAlex date {od} is before {start}" if od and od < start else ""
    res.update(start=start, files=files, tool_total=len(tool), dim_total=len(dim),
               date_mismatch=sum(1 for d in res["only_dim"] if d["note"]))
    return res
