import json
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS publications (
    key TEXT PRIMARY KEY,
    first_seen TEXT,
    record TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started TEXT,
    finished TEXT,
    status TEXT,
    summary TEXT
);
CREATE TABLE IF NOT EXISTS journals (
    issn TEXT PRIMARY KEY,
    name TEXT,
    citedness REAL,
    h_index INTEGER,
    source_type TEXT,
    fetched TEXT
);
"""


def connect(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    return con


def load_records(con):
    return [json.loads(r) for (r,) in con.execute("SELECT record FROM publications")]


def replace_records(con, records):
    with con:
        con.execute("DELETE FROM publications")
        con.executemany(
            "INSERT INTO publications (key, first_seen, record) VALUES (?, ?, ?)",
            [(r["key"], r.get("first_seen"), json.dumps(r)) for r in records],
        )


def start_run(con, started):
    with con:
        return con.execute("INSERT INTO runs (started, status) VALUES (?, 'running')", (started,)).lastrowid


def finish_run(con, run_id, finished, status, summary):
    with con:
        con.execute("UPDATE runs SET finished = ?, status = ?, summary = ? WHERE id = ?",
                    (finished, status, json.dumps(summary), run_id))


def load_journals(con):
    cols = ("issn", "name", "citedness", "h_index", "source_type", "fetched")
    return {row[0]: dict(zip(cols, row)) for row in con.execute(f"SELECT {', '.join(cols)} FROM journals")}


def save_journals(con, rows):
    with con:
        con.executemany(
            "INSERT OR REPLACE INTO journals (issn, name, citedness, h_index, source_type, fetched) "
            "VALUES (:issn, :name, :citedness, :h_index, :source_type, :fetched)", rows)
