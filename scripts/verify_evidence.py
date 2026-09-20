"""Offline integrity checks; does not claim to re-execute saved fault injections."""

import hashlib
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from shardlab.core import digest


def main():
    if not __debug__:raise SystemExit("Assertions must be enabled; remove -O")
    evidence = ROOT / "evidence" / "local"
    summary = json.loads((evidence / "summary.json").read_text())
    for name, sha in summary["source_sha256"].items():
        path = ROOT / name
        if name in {"shardlab/worker.py", "scripts/verify_evidence.py"}:
            path = ROOT / "docs/maintenance/2026-09-19/baseline" / f"{name}.txt"
        if name in {'shardlab/core.py', 'tests/test_http.py'}:
            path = ROOT / "docs/maintenance/2026-09-21/baseline" / f"{name}.txt"
        assert hashlib.sha256(path.read_bytes()).hexdigest() == sha, name
    manifests = list(evidence.glob("*/manifest.json"))
    assert len(manifests) == len(summary["results"])
    hashes = set()
    for path in manifests:
        value = json.loads(path.read_text())
        body = value["manifest"]
        assert digest(body) == value["sha256"]
        hashes.add(value["sha256"])
        assert body["input_count"] == 1200
        assert len(body["records"]) == 1000
        assert len(body["quarantine"]) == 100
        assert len(body["duplicates"]) == 100
        ids = [r["row_id"] for k in ["records", "quarantine", "duplicates"] for r in body[k]]
        assert sorted(ids) == [f"{i:08d}" for i in range(1200)]
        accepted = {r["row_id"] for r in body["records"]}
        assert all(r["duplicate_of"] in accepted for r in body["duplicates"])
        assert all(digest(r["text"]) == r["text_sha256"] for r in body["records"])
        status = json.loads((path.parent / "events.json").read_text())
        assert status["states"] == {"done": 24}
        commits = [e["shard"] for e in status["events"] if e["kind"] == "committed"]
        assert sorted(commits) == list(range(24))
    assert len(hashes) == 1
    assert {r["manifest_sha256"] for r in summary["results"]} == hashes
    serial = statistics.median(r["seconds"] for r in summary["results"] if r["workers"] == 1)
    parallel = statistics.median(
        r["seconds"] for r in summary["results"] if r["workers"] == 4 and not r["fault_injection"]
    )
    assert summary["median_seconds"] == {"one_worker": serial, "four_workers": parallel}
    assert summary["observed_speedup"] == serial / parallel
    trace = json.loads((evidence / "fault" / "fault_trace.json").read_text())
    assert [e["event"] for e in trace] == [
        "commit_ack_discarded",
        "coordinator_sigkill_restart_and_commit_replay",
        "worker_sigkill_after_claim",
        "stale_commit_rejected",
    ]
    assert trace[-1]["http_status"] == 409
    events = json.loads((evidence / "fault" / "events.json").read_text())["events"]
    assert any(e["kind"] == "expired" for e in events)
    assert any(e["kind"] == "replayed" for e in events)
    print(
        f"Verified {len(manifests)} saved manifests, row accounting, commits, timings and source identities. No new execution."
    )


if __name__ == "__main__":
    main()
