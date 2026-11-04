from .utils import join_unique

SOURCE_PRIORITY = {"pubmed": 1, "openalex": 2}

FIELDS = [
    "pmid", "pmcid", "doi", "openalex_id", "title", "abstract", "journal",
    "publisher", "pub_date", "pub_type", "doc_type", "authors", "corresponding_authors",
    "affiliations", "open_access", "oa_url", "times_cited", "rcr", "fcr", "retraction",
    "source_linkout", "rcdc", "health_areas",
]
UNION_FIELDS = ["funder", "grant_ids", "research_orgs", "mesh_terms", "fields_of_research", "issn"]
TEXT_FIELDS = ["funding_text", "acknowledgements"]


def empty_record(source):
    rec = {f: None for f in FIELDS + UNION_FIELDS + TEXT_FIELDS}
    rec["sources"] = [source]
    return rec


def _priority(rec):
    return min((SOURCE_PRIORITY.get(s, 9) for s in rec.get("sources") or []), default=9)


def _identity_keys(rec):
    keys = []
    for prefix, field in (("doi", "doi"), ("pmid", "pmid"), ("oa", "openalex_id")):
        if rec.get(field):
            keys.append(f"{prefix}:{rec[field]}")
    return keys


def canonical_key(rec):
    keys = _identity_keys(rec)
    return keys[0] if keys else None


def group_records(records):
    """Group records that share a DOI, PMID or OpenAlex ID."""
    parent = list(range(len(records)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    seen = {}
    for i, rec in enumerate(records):
        for k in _identity_keys(rec):
            if k in seen:
                a, b = find(i), find(seen[k])
                if a != b:
                    parent[a] = b
            else:
                seen[k] = i

    groups = {}
    for i, rec in enumerate(records):
        groups.setdefault(find(i), []).append(rec)
    return list(groups.values())


def merge_records(pieces):
    # Fresh source data outranks stored copies of the same priority.
    ordered = sorted(pieces, key=lambda r: (_priority(r), bool(r.get("_stored"))))
    out = {}
    for f in FIELDS:
        out[f] = next((p[f] for p in ordered if p.get(f) not in (None, "")), None)
    for f in UNION_FIELDS:
        out[f] = join_unique(*(p.get(f) for p in ordered)) or None
    for f in TEXT_FIELDS:
        parts = []
        for p in ordered:
            for t in (p.get(f) or "").split("\n\n"):
                t = t.strip()
                if t and t not in parts:
                    parts.append(t)
        out[f] = "\n\n".join(parts) or None
    out["sources"] = sorted({s for p in pieces for s in p.get("sources") or []},
                            key=lambda s: SOURCE_PRIORITY.get(s, 9))
    seen = [p["first_seen"] for p in pieces if p.get("first_seen")]
    out["first_seen"] = min(seen) if seen else None
    return out
