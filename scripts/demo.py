"""Real loopback HTTP, independent workers, SIGKILL, restart, replay, stale commit.

Run from repository root: python scripts/demo.py --out runs/example
Each invocation requires a new output directory; historical evidence is untouched.
"""

import argparse
import hashlib
import json
import os
import platform
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from shardlab.core import canonical, commit_args
from shardlab.worker import request, ApiError


def fixture():
    unique = [
        {"text": f"  Synthetic training example {i:04d} for data processing.  "}
        for i in range(1000)
    ]
    return (
        unique
        + [dict(r) for r in unique[:100]]
        + [{"text": " " if i % 2 else None} for i in range(100)]
    )


def stop(process):
    if process.poll() is None:
        process.kill()
        process.wait(timeout=10)
    if process.stdout:
        process.stdout.close()
    if process.stderr:
        process.stderr.close()


def start(db):
    p = subprocess.Popen(
        [sys.executable, "-m", "shardlab.server", "--db", str(db)],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    # Bounded startup wait, no readline hang on an unhealthy server.
    import select

    ready, _, _ = select.select([p.stdout], [], [], 10)
    if not ready:
        stop(p)
        raise TimeoutError("coordinator startup")
    line = p.stdout.readline()
    if not line:
        detail = p.stderr.read()
        stop(p)
        raise RuntimeError(detail)
    return p, json.loads(line)["url"]


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def scenario(path, workers, fault=False):
    path.mkdir()
    server, url = start(path / "state.sqlite")
    children = []
    victim = None
    trace = []
    try:
        records = fixture()
        request(url, "/submit", {"run": "demo", "records": records, "shard_size": 50})
        check(
            request(url, "/submit", {"run": "demo", "records": records, "shard_size": 50})[
                "replayed"
            ],
            "submit replay",
        )
        start_time = time.perf_counter()
        if fault:
            # Finish one shard, discard first ACK, kill and restart the coordinator.
            first = request(
                url, "/claim", {"run": "demo", "worker": "ack-loss", "lease_seconds": 5}
            )["task"]
            args = commit_args(first)
            request(url, "/commit", args)
            trace.append({"event": "commit_ack_discarded", "shard": first["shard"]})
            stop(server)
            server, url = start(path / "state.sqlite")
            check(
                request(url, "/commit", args)["replayed"],
                "durable replay after coordinator restart",
            )
            trace.append({"event": "coordinator_sigkill_restart_and_commit_replay", "passed": True})
            # A real child claims a task, acknowledges the claim locally, then stalls.
            code = """import json,sys,time
from shardlab.worker import request
t=request(sys.argv[1],'/claim',{'run':'demo','worker':'victim','lease_seconds':0.3})['task']
print(json.dumps(t),flush=True)
time.sleep(60)
"""
            victim = subprocess.Popen(
                [sys.executable, "-c", code, url], cwd=ROOT, stdout=subprocess.PIPE, text=True
            )
            import select

            ready, _, _ = select.select([victim.stdout], [], [], 10)
            if not ready:
                raise TimeoutError("victim claim")
            stale = json.loads(victim.stdout.readline())
            stop(victim)
            trace.append(
                {
                    "event": "worker_sigkill_after_claim",
                    "shard": stale["shard"],
                    "token": stale["token"],
                }
            )
        for i in range(workers):
            children.append(
                subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "shardlab.worker",
                        "--url",
                        url,
                        "--run",
                        "demo",
                        "--worker",
                        f"worker-{i}",
                    ],
                    cwd=ROOT,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
            )
        receipts = []
        for p in children:
            out, err = p.communicate(timeout=40)
            check(p.returncode == 0, err)
            receipts.append(json.loads(out))
        seconds = time.perf_counter() - start_time
        if fault:
            try:
                request(url, "/commit", commit_args(stale))
            except ApiError as exc:
                check(exc.status == 409, "expected stale token 409")
            else:
                raise AssertionError("stale worker was not fenced")
            trace.append({"event": "stale_commit_rejected", "http_status": 409})
        status = request(url, "/status", {"run": "demo"})
        result = request(url, "/publish", {"run": "demo"})
        check(request(url, "/publish", {"run": "demo"}) == result, "manifest replay")
        body = result["manifest"]
        check(
            len(body["records"]) == 1000
            and len(body["duplicates"]) == 100
            and len(body["quarantine"]) == 100,
            "fixture oracle counts",
        )
        check(
            [r["text"] for r in body["records"]]
            == [f"Synthetic training example {i:04d} for data processing." for i in range(1000)],
            "independent content oracle",
        )
        check(status["states"] == {"done": 24}, "all shards committed")
        check(
            sum(e["kind"] == "committed" for e in status["events"]) == 24,
            "one durable commit per shard",
        )
        if fault:
            check(any(e["kind"] == "expired" for e in status["events"]), "actual lease expiry")
        (path / "manifest.json").write_text(canonical(result) + "\n")
        (path / "events.json").write_text(json.dumps(status, indent=2) + "\n")
        (path / "fault_trace.json").write_text(json.dumps(trace, indent=2) + "\n")
        return {
            "workers": workers,
            "fault_injection": fault,
            "seconds": seconds,
            "rows_per_second": 1200 / seconds,
            "manifest_sha256": result["sha256"],
            "states": status["states"],
            "worker_receipts": receipts,
            "fault_trace": trace,
        }
    finally:
        for p in children:
            stop(p)
        if victim:
            stop(victim)
        stop(server)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.repeats <= 10:
        parser.error("repeats must be 1..10")
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=False)
    results = []
    # Alternate order to reduce a fixed ordering bias; no artificial per-row sleep.
    for repeat in range(args.repeats):
        for workers in [1, 4] if repeat % 2 == 0 else [4, 1]:
            results.append(scenario(out / f"w{workers}-{repeat}", workers))
    results.append(scenario(out / "fault", 4, True))
    check(
        len({r["manifest_sha256"] for r in results}) == 1,
        "manifest differs by worker count or failures",
    )
    serial = statistics.median(r["seconds"] for r in results if r["workers"] == 1)
    parallel = statistics.median(
        r["seconds"] for r in results if r["workers"] == 4 and not r["fault_injection"]
    )
    source = {
        str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
        for folder in ["shardlab", "scripts", "tests"]
        for p in sorted((ROOT / folder).glob("*.py"))
    }
    summary = {
        "environment": {
            "python": platform.python_version(),
            "system": platform.system(),
            "machine": platform.machine(),
            "cpu_count": os.cpu_count(),
            "topology": "one host; loopback HTTP; one SQLite coordinator",
        },
        "fixture": {
            "rows": 1200,
            "shards": 24,
            "accepted_unique": 1000,
            "duplicates": 100,
            "quarantine": 100,
        },
        "source_sha256": source,
        "results": results,
        "median_seconds": {"one_worker": serial, "four_workers": parallel},
        "observed_speedup": serial / parallel,
        "scope": "local synthetic text processing; no model training or production scale",
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(
        json.dumps(
            {"output": str(out), "all_checks_passed": True, "observed_speedup": serial / parallel},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
