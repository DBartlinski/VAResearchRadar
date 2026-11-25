import csv
import io
import threading
from collections import Counter

from flask import Flask, abort, jsonify, request, Response, send_from_directory

from loader import ROOT, build

STATIC = ROOT / "compare" / "static"
app = Flask(__name__, static_folder=None)
_lock = threading.Lock()
_cache = {}


def data(reload=False):
    with _lock:
        if reload or "d" not in _cache:
            _cache["d"] = build()
        return _cache["d"]


def month(r):
    return (r["date"] or "")[:7] or "unknown"


def breakdown(rows, key, top=None):
    c = Counter((key(r) or "(none)") for r in rows)
    return c.most_common(top)


@app.get("/")
def index():
    return send_from_directory(STATIC, "index.html")


@app.get("/api/summary")
def summary():
    d = data(reload=request.args.get("reload") == "1")
    m, ot, od = d["matched"], d["only_tool"], d["only_dim"]
    months = sorted({month(r) for r in [x["tool"] for x in m] + ot + od})
    cnt = lambda rows, f=month: Counter(f(r) for r in rows)  # noqa: E731
    mm, mt, md = cnt([x["tool"] for x in m]), cnt(ot), cnt(od)
    return jsonify(
        start=d["start"], files=d["files"], tool_total=d["tool_total"], dim_total=d["dim_total"],
        matched=len(m), only_tool=len(ot), only_dim=len(od), date_mismatch=d["date_mismatch"],
        by=dict(Counter(x["by"] for x in m)),
        months=[{"month": k, "matched": mm[k], "only_tool": mt[k], "only_dim": md[k]} for k in months],
        dim_journals=breakdown(od, lambda r: r["journal"], 15),
        tool_journals=breakdown(ot, lambda r: r["journal"], 15),
        dim_types=breakdown(od, lambda r: r["type"], 10),
        tool_sources=breakdown(ot, lambda r: r["sources"]),
    )


def select(side):
    d = data()
    if side == "matched":
        rows = [{**x["tool"], "dim_id": x["dim"]["id"], "by": x["by"], "url": x["dim"]["url"] or x["tool"]["url"]}
                for x in d["matched"]]
    elif side == "only_tool":
        rows = d["only_tool"]
    elif side == "only_dim":
        rows = d["only_dim"]
    else:
        abort(404)
    q = (request.args.get("q") or "").lower().strip()
    if q:
        rows = [r for r in rows if q in " ".join((r["title"], r["journal"], r["doi"] or "", r["pmid"] or "",
                                                  r["type"])).lower()]
    return sorted(rows, key=lambda r: r["date"], reverse=True)


FIELDS = ["date", "title", "journal", "type", "doi", "pmid", "dim_id", "sources", "url", "note"]


@app.get("/api/records/<side>")
def records(side):
    rows = select(side)
    page, size = max(int(request.args.get("page", 0)), 0), 50
    return jsonify(total=len(rows), rows=[{k: r.get(k) for k in FIELDS + ["by"]} for r in rows[page * size:(page + 1) * size]])


@app.get("/api/export/<side>")
def export(side):
    out = io.StringIO()
    w = csv.DictWriter(out, FIELDS, extrasaction="ignore")
    w.writeheader()
    w.writerows(select(side))
    return Response(out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={side}.csv"})


if __name__ == "__main__":
    print("Open http://127.0.0.1:5001")
    app.run(host="127.0.0.1", port=5001, debug=False)
