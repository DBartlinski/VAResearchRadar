"""Journal tiers from OpenAlex source metrics (2-year mean citedness, similar to an impact factor)."""
import re
import time
from datetime import date, timedelta

from . import store
from .sources.http import make_session
from .sources.openalex import BASE, _params
from .utils import split_multi

TIERS = ["Top", "Mid", "Lower", "Preprint", "Not rated"]
ISSN_RE = re.compile(r"^\d{4}-\d{3}[\dX]$")
PREPRINT_RE = re.compile(r"rxiv|preprint|research square|ssrn|authorea|preprints\.org|qeios", re.I)
# Repositories that host articles but say nothing about journal quality.
GENERIC_HOST_RE = re.compile(r"^(?:pubmed|pubmed central|europe pmc|zenodo|figshare|osf|hal|semantic scholar)\b", re.I)
CACHE_DAYS = 30
BATCH = 50


def _issns(rec):
    return [i.upper() for i in split_multi(rec.get("issn")) if ISSN_RE.match(i.upper())]


def refresh_cache(con, cfg, records, log=print):
    """Fetch metrics for ISSNs that are missing or older than CACHE_DAYS."""
    cache = store.load_journals(con)
    stale = (date.today() - timedelta(days=CACHE_DAYS)).isoformat()
    needed = sorted({i for r in records for i in _issns(r)
                     if i not in cache or (cache[i]["fetched"] or "") < stale})
    if not needed:
        return 0
    s = make_session(cfg.get("contact_email", ""))
    today = date.today().isoformat()
    for start in range(0, len(needed), BATCH):
        batch = needed[start:start + BATCH]
        r = s.get(f"{BASE}/sources", params=_params(
            cfg, filter="issn:" + "|".join(batch), per_page=100,
            select="id,display_name,issn,summary_stats,type"), timeout=60)
        r.raise_for_status()
        rows = {i: {"issn": i, "name": None, "citedness": None, "h_index": None, "source_type": None,
                    "fetched": today} for i in batch}
        for src in r.json().get("results", []):
            stats = src.get("summary_stats") or {}
            for i in src.get("issn") or []:
                rows[i.upper()] = {"issn": i.upper(), "name": src.get("display_name"),
                                   "citedness": stats.get("2yr_mean_citedness"), "h_index": stats.get("h_index"),
                                   "source_type": src.get("type"), "fetched": today}
        store.save_journals(con, list(rows.values()))
        time.sleep(0.15)
    log(f"Journal metrics refreshed for {len(needed)} ISSNs")
    return len(needed)


class JournalTiers:
    def __init__(self, tier_cfg, cache):
        self.cfg = tier_cfg
        self.cache = cache
        self.always_top = {n.lower() for n in tier_cfg.get("always_top", [])}
        self.always_mid = {n.lower() for n in tier_cfg.get("always_mid", [])}

    def assign(self, rec):
        """Return (tier, citedness)."""
        journal = " ".join((rec.get("journal") or "").split())
        rows = [self.cache[i] for i in _issns(rec) if i in self.cache]
        citedness = max((x["citedness"] for x in rows if x["citedness"] is not None), default=None)
        if rec.get("pub_type") == "Preprint" or PREPRINT_RE.search(journal):
            return "Preprint", citedness
        if GENERIC_HOST_RE.match(journal):
            return "Not rated", None
        if journal.lower() in self.always_top:
            return "Top", citedness
        if journal.lower() in self.always_mid:
            return "Mid", citedness
        if citedness is None:
            return "Not rated", None
        if citedness >= self.cfg["top_min_citedness"]:
            return "Top", citedness
        if citedness >= self.cfg["mid_min_citedness"]:
            return "Mid", citedness
        return "Lower", citedness
