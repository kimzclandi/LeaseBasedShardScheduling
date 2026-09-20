"""Durable shard leases, fenced commits and deterministic dataset publication.

Workers are trusted. SQLite is local to one coordinator. This is deliberately
not an implementation of consensus, replicated storage or a production broker.
"""

import hashlib
import json
import math
import sqlite3
import time
import unicodedata
from contextlib import closing, contextmanager

RULE = "nfkc-whitespace-min8-v1"


def canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class Conflict(Exception):
    pass


class Missing(Exception):
    pass


def transform(rows):
    """Only schema/length hygiene, NOT semantic quality or PII removal."""
    output = []
    for row in rows:
        raw = row["raw"]
        item = {"row_id": row["row_id"], "source_sha256": digest(raw)}
        if not isinstance(raw, dict) or not isinstance(raw.get("text"), str):
            item.update(status="quarantine", reason="invalid_text_schema")
        else:
            text = " ".join(unicodedata.normalize("NFKC", raw["text"]).split())
            if len(text) < 8:
                item.update(status="quarantine", reason="short_text")
            else:
                item.update(status="accepted", text=text, text_sha256=digest(text))
        output.append(item)
    return output


class Store:
    def __init__(self, path, clock=time.time):
        self.path = str(path)
        self.clock = clock
        with closing(self.connect()) as con:
            con.execute("PRAGMA journal_mode=WAL")
            con.executescript("""
                CREATE TABLE IF NOT EXISTS runs(
                    id TEXT PRIMARY KEY, source_hash TEXT NOT NULL,
                    rule TEXT NOT NULL, shard_size INTEGER NOT NULL,
                    max_attempts INTEGER NOT NULL, input_count INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS shards(
                    run TEXT NOT NULL, id INTEGER NOT NULL, payload TEXT NOT NULL,
                    input_hash TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'queued',
                    attempt INTEGER NOT NULL DEFAULT 0, owner TEXT,
                    deadline REAL, result TEXT, result_hash TEXT,
                    PRIMARY KEY(run,id), FOREIGN KEY(run) REFERENCES runs(id));
                CREATE INDEX IF NOT EXISTS queue ON shards(run,state,id);
                CREATE TABLE IF NOT EXISTS events(
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, run TEXT, shard INTEGER,
                    kind TEXT, attempt INTEGER, at REAL);
                CREATE TABLE IF NOT EXISTS manifests(
                    run TEXT PRIMARY KEY, body TEXT NOT NULL, hash TEXT NOT NULL,
                    FOREIGN KEY(run) REFERENCES runs(id));
            """)

    def connect(self):
        con = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("PRAGMA synchronous=FULL")
        return con

    @contextmanager
    def transaction(self):
        con = self.connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            yield con
            con.commit()
        except BaseException:
            con.rollback()
            raise
        finally:
            con.close()

    def event(self, con, run, shard, kind, attempt):
        con.execute(
            "INSERT INTO events(run,shard,kind,attempt,at) VALUES(?,?,?,?,?)",
            (run, shard, kind, attempt, self.clock()),
        )

    @staticmethod
    def run(con, run):
        row = con.execute("SELECT * FROM runs WHERE id=?", (run,)).fetchone()
        if row is None:
            raise Missing("unknown run")
        return row

    def submit(self, run, records, shard_size=100, max_attempts=3):
        if not isinstance(run, str) or not run or len(run) > 100:
            raise ValueError("run must be a nonempty string <=100 characters")
        if not isinstance(records, list) or not records or len(records) > 100000:
            raise ValueError("records must be a list with 1..100000 rows")
        if type(shard_size) is not int or not 1 <= shard_size <= 1000:
            raise ValueError("shard_size must be 1..1000")
        if type(max_attempts) is not int or not 1 <= max_attempts <= 10:
            raise ValueError("max_attempts must be 1..10")
        identity = (digest(records), RULE, shard_size, max_attempts, len(records))
        with self.transaction() as con:
            previous = con.execute("SELECT * FROM runs WHERE id=?", (run,)).fetchone()
            if previous:
                if tuple(previous)[1:] != identity:
                    raise Conflict("run identity already exists with different input/config")
                return {"run": run, "replayed": True}
            con.execute("INSERT INTO runs VALUES(?,?,?,?,?,?)", (run, *identity))
            rows = [{"row_id": f"{i:08d}", "raw": r} for i, r in enumerate(records)]
            for start in range(0, len(rows), shard_size):
                shard = rows[start : start + shard_size]
                con.execute(
                    "INSERT INTO shards(run,id,payload,input_hash) VALUES(?,?,?,?)",
                    (run, start // shard_size, canonical(shard), digest(shard)),
                )
            return {"run": run, "replayed": False}

    @staticmethod
    def check_lease_seconds(seconds):
        if (
            not isinstance(seconds, (int, float))
            or not math.isfinite(seconds)
            or not 0.05 <= seconds <= 300
        ):
            raise ValueError("lease_seconds must be finite and within .05..300")

    def claim(self, run, worker, lease_seconds=5):
        self.check_lease_seconds(lease_seconds)
        if not isinstance(worker, str) or not worker or len(worker) > 100:
            raise ValueError("worker must be a nonempty string <=100 characters")
        with self.transaction() as con:
            config = self.run(con, run)
            expired = con.execute(
                "SELECT * FROM shards WHERE run=? AND state='leased' AND deadline<=?",
                (run, self.clock()),
            ).fetchall()
            for s in expired:
                state = "dead" if s["attempt"] >= config["max_attempts"] else "queued"
                con.execute("UPDATE shards SET state=? WHERE run=? AND id=?", (state, run, s["id"]))
                self.event(
                    con, run, s["id"], "exhausted" if state == "dead" else "expired", s["attempt"]
                )
            s = con.execute(
                "SELECT * FROM shards WHERE run=? AND state='queued' ORDER BY id LIMIT 1", (run,)
            ).fetchone()
            if s is None:
                return {"task": None}
            token = s["attempt"] + 1
            deadline = self.clock() + lease_seconds
            con.execute(
                "UPDATE shards SET state='leased',attempt=?,owner=?,deadline=? WHERE run=? AND id=?",
                (token, worker, deadline, run, s["id"]),
            )
            self.event(con, run, s["id"], "claimed", token)
            return {
                "task": {
                    "run": run,
                    "shard": s["id"],
                    "token": token,
                    "worker": worker,
                    "deadline": deadline,
                    "input_sha256": s["input_hash"],
                    "rule": config["rule"],
                    "rows": json.loads(s["payload"]),
                }
            }

    def lease_row(self, con, run, shard, token, worker):
        self.run(con, run)
        s = con.execute("SELECT * FROM shards WHERE run=? AND id=?", (run, shard)).fetchone()
        if s is None:
            raise Missing("unknown shard")
        if s["attempt"] != token or s["owner"] != worker:
            raise Conflict("fenced: old token or different worker")
        return s

    def renew(self, run, shard, token, worker, lease_seconds=5):
        self.check_lease_seconds(lease_seconds)
        with self.transaction() as con:
            s = self.lease_row(con, run, shard, token, worker)
            if s["state"] != "leased" or s["deadline"] <= self.clock():
                raise Conflict("lease not active")
            deadline = self.clock() + lease_seconds
            con.execute("UPDATE shards SET deadline=? WHERE run=? AND id=?", (deadline, run, shard))
            return {"deadline": deadline}

    def commit(self, run, shard, token, worker, input_sha256, rule, results):
        result_hash = digest(results)
        with self.transaction() as con:
            s = self.lease_row(con, run, shard, token, worker)
            if input_sha256 != s["input_hash"] or rule != RULE:
                raise Conflict("input identity or rule mismatch")
            if s["state"] == "done":
                if s["result_hash"] != result_hash:
                    raise Conflict("conflicting replay")
                self.event(con, run, shard, "replayed", token)
                return {"replayed": True, "result_sha256": result_hash}
            if s["state"] != "leased" or s["deadline"] <= self.clock():
                raise Conflict("lease expired or not active")
            source = json.loads(s["payload"])
            if not isinstance(results, list) or len(results) != len(source):
                raise ValueError("one result per input row is required")
            for raw, res in zip(source, results):
                if (
                    not isinstance(res, dict)
                    or res.get("row_id") != raw["row_id"]
                    or res.get("source_sha256") != digest(raw["raw"])
                ):
                    raise ValueError("row lineage mismatch")
                base = {"row_id", "source_sha256", "status"}
                if res.get("status") == "accepted":
                    if (
                        set(res) != base | {"text", "text_sha256"}
                        or not isinstance(res["text"], str)
                        or res["text_sha256"] != digest(res["text"])
                    ):
                        raise ValueError("invalid accepted result")
                elif res.get("status") == "quarantine":
                    if set(res) != base | {"reason"} or res["reason"] not in (
                        "invalid_text_schema",
                        "short_text",
                    ):
                        raise ValueError("invalid quarantine result")
                else:
                    raise ValueError("invalid result status")
            con.execute(
                "UPDATE shards SET state='done',result=?,result_hash=? WHERE run=? AND id=?",
                (canonical(results), result_hash, run, shard),
            )
            self.event(con, run, shard, "committed", token)
            return {"replayed": False, "result_sha256": result_hash}

    def status(self, run):
        with self.transaction() as con:
            self.run(con, run)
            counts = {
                s["state"]: s["n"]
                for s in con.execute(
                    "SELECT state,count(*) n FROM shards WHERE run=? GROUP BY state", (run,)
                )
            }
            events = [
                dict(s)
                for s in con.execute(
                    "SELECT shard,kind,attempt,at FROM events WHERE run=? ORDER BY seq", (run,)
                )
            ]
            return {
                "states": counts,
                "events": events,
                "terminal": not counts.get("queued", 0) and not counts.get("leased", 0),
                "successful": set(counts) == {"done"},
            }

    def publish(self, run):
        with self.transaction() as con:
            config = self.run(con, run)
            old = con.execute("SELECT * FROM manifests WHERE run=?", (run,)).fetchone()
            if old:
                return {"manifest": json.loads(old["body"]), "sha256": old["hash"]}
            shards = con.execute("SELECT * FROM shards WHERE run=? ORDER BY id", (run,)).fetchall()
            if any(s["state"] != "done" for s in shards):
                raise Conflict("cannot publish incomplete or exhausted run")
            rows = []
            for s in shards:
                rows.extend(json.loads(s["result"]))
            rows.sort(key=lambda r: r["row_id"])
            seen = {}
            output = []
            quarantine = []
            duplicates = []
            for r in rows:
                if r["status"] == "quarantine":
                    quarantine.append(r)
                elif r["text_sha256"] in seen:
                    duplicates.append(
                        {
                            "row_id": r["row_id"],
                            "source_sha256": r["source_sha256"],
                            "duplicate_of": seen[r["text_sha256"]],
                        }
                    )
                else:
                    seen[r["text_sha256"]] = r["row_id"]
                    output.append(r)
            body = {
                "schema_version": 1,
                "rule": config["rule"],
                "source_sha256": config["source_hash"],
                "input_count": config["input_count"],
                "records": output,
                "quarantine": quarantine,
                "duplicates": duplicates,
                "shards": [
                    {
                        "id": s["id"],
                        "input_sha256": s["input_hash"],
                        "result_sha256": s["result_hash"],
                    }
                    for s in shards
                ],
            }
            sha = digest(body)
            con.execute("INSERT INTO manifests VALUES(?,?,?)", (run, canonical(body), sha))
            return {"manifest": body, "sha256": sha}


def commit_args(task):
    return {k: task[k] for k in ("run", "shard", "token", "worker", "rule")} | {
        "input_sha256": task["input_sha256"],
        "results": transform(task["rows"]),
    }
