import csv
import json
from datetime import date, datetime, timedelta

from . import funding, journals, store
from .config import load_config, path_for
from .records import canonical_key, group_records, merge_records
from .scoring import Scorer
from .sources import crossref, dimensions_csv, openalex, pubmed


def _now():
    return datetime.now().isoformat(timespec="seconds")


def coverage(records):
    """Compare Dimensions with PubMed/OpenAlex over the date range the Dimensions exports cover."""
    dims_dates = [r["pub_date"] for r in records if "dimensions" in r["sources"]]
    if not dims_dates:
        return None, []
    lo = min(dims_dates)
    window = [r for r in records if r["pub_date"] >= lo]
    in_dims = [r for r in window if "dimensions" in r["sources"]]
    both = [r for r in in_dims if {"pubmed", "openalex", "crossref"} & set(r["sources"])]
    free_only = [r for r in window if "dimensions" not in r["sources"]]
    stats = {
        "window_start": lo,
        "in_dimensions": len(in_dims),
        "also_in_free_sources": len(both),
        "dimensions_only": len(in_dims) - len(both),
        "free_sources_only": len(free_only),
        "free_source_recall_pct": round(100 * len(both) / len(in_dims), 1) if in_dims else None,
    }
    return stats, window


def _write_coverage_csv(path, window):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["Publication date", "Title", "Journal", "Type", "In Dimensions", "In PubMed", "In OpenAlex",
                    "DOI", "PMID", "Dimensions ID", "OpenAlex ID"])
        for r in sorted(window, key=lambda r: r["pub_date"], reverse=True):
            s = set(r["sources"])
            w.writerow([r["pub_date"], r.get("title"), r.get("journal"), r.get("pub_type"),
                        "dimensions" in s, "pubmed" in s, "openalex" in s,
                        r.get("doi"), r.get("pmid"), r.get("dimensions_id"), r.get("openalex_id")])


def run(cfg=None, log=print):
    cfg = cfg or load_config()
    started = _now()
    today = date.today()
    start_date = date.fromisoformat(str(cfg["start_date"]))
    con = store.connect(path_for(cfg, "database"))
    run_id = store.start_run(con, started)
    summary = {"started": started, "start_date": start_date.isoformat(), "sources": {}, "warnings": []}
    status = "error"
    try:
        dims, files = dimensions_csv.load_folder(path_for(cfg, "dimensions_folder"))
        summary["sources"]["dimensions"] = {"records": len(dims), "files": files}
        if not files:
            summary["warnings"].append("No Dimensions CSV files found in the Dimensions folder.")
        elif any(f["rows"] >= 500 for f in files[:1]):
            summary["warnings"].append("Newest Dimensions export has 500 rows (export cap); some records may be missing.")
        pieces = list(dims)

        since = max(start_date, today - timedelta(days=int(cfg.get("lookback_days", 45))))
        if cfg.get("pubmed", {}).get("enabled"):
            try:
                recs = pubmed.fetch(cfg, since, today, log)
                pieces += recs
                summary["sources"]["pubmed"] = {"records": len(recs), "since": since.isoformat()}
            except Exception as e:
                summary["warnings"].append(f"PubMed failed: {e}")
        if cfg.get("openalex", {}).get("enabled"):
            try:
                recs, resolved = openalex.fetch(cfg, since, today, log)
                pieces += recs
                summary["sources"]["openalex"] = {"records": len(recs), "since": since.isoformat(), "resolved": resolved}
            except Exception as e:
                summary["warnings"].append(f"OpenAlex failed: {e}")

        if cfg.get("crossref", {}).get("enabled"):
            try:
                recs = crossref.fetch(cfg, since, today, log)
                pieces += recs
                summary["sources"]["crossref"] = {"records": len(recs), "since": since.isoformat()}
            except Exception as e:
                summary["warnings"].append(f"Crossref failed: {e}")

        for p in pieces:
            p["_stored"] = False
            p["first_seen"] = started
        stored = store.load_records(con)
        for r in stored:
            r["_stored"] = True

        scorer = Scorer(cfg["scoring"])
        merged = [merge_records(g) for g in group_records(pieces + stored)]
        merged = [r for r in merged if r.get("pub_date") and r["pub_date"] >= start_date.isoformat()]
        try:
            journals.refresh_cache(con, cfg, merged, log)
        except Exception as e:
            summary["warnings"].append(f"Journal metrics lookup failed (using cached values): {e}")
        tiers = journals.JournalTiers(cfg["scoring"]["journal_tiers"], store.load_journals(con))

        kept = []
        for r in merged:
            r.update(funding.classify(r))
            r["journal_tier"], r["journal_citedness"] = tiers.assign(r)
            r["score"], r["tier"], r["score_reasons"] = scorer.score(r)
            r["key"] = canonical_key(r)
            r["added"] = r["first_seen"][:10]
            r["is_new"] = r["first_seen"] >= started
            kept.append(r)
        kept.sort(key=lambda r: (r["score"], r["pub_date"]), reverse=True)

        store.replace_records(con, kept)

        cov, window = coverage(kept)
        if window:
            _write_coverage_csv(path_for(cfg, "reports") / f"coverage-{today.isoformat()}.csv", window)
        summary.update({
            "total": len(kept),
            "new": sum(r["is_new"] for r in kept),
            "tiers": {t: sum(r["tier"] == t for r in kept) for t in ("High", "Medium", "Low")},
            "journal_tiers": {t: sum(r["journal_tier"] == t for r in kept) for t in journals.TIERS},
            "coverage": cov,
        })
        status = "ok"

        data_dir = path_for(cfg, "site") / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / "publications.json").write_text(json.dumps(kept, ensure_ascii=False), encoding="utf-8")
        summary["finished"] = _now()
        meta = {**summary, "scoring": cfg["scoring"]}
        (data_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        return summary
    except Exception as e:
        summary["warnings"].append(f"Run failed: {e}")
        raise
    finally:
        store.finish_run(con, run_id, _now(), status, summary)
        con.close()


if __name__ == "__main__":
    result = run()
    print(json.dumps({k: v for k, v in result.items() if k != "sources"}, indent=2))
