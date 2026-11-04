import json
from datetime import date, datetime, timedelta

from . import funding, journals, store
from .config import load_config, path_for
from .records import canonical_key, group_records, merge_records
from .scoring import Scorer
from .sources import openalex, pubmed


def _now():
    return datetime.now().isoformat(timespec="seconds")


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
        pieces = []

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

        summary.update({
            "total": len(kept),
            "new": sum(r["is_new"] for r in kept),
            "tiers": {t: sum(r["tier"] == t for r in kept) for t in ("High", "Medium", "Low")},
            "journal_tiers": {t: sum(r["journal_tier"] == t for r in kept) for t in journals.TIERS},
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
