"""Independent HTTP worker; no shared SQLite connection or filesystem input."""

import argparse
import json
import time
import urllib.error
import urllib.request
from .core import canonical, commit_args, digest, RULE


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def request(url, route, body, attempts=4):
    # Identical commit bodies are retried after connection loss/5xx. Claim retries
    # can leave an unused lease, which the coordinator eventually expires.
    for attempt in range(attempts):
        try:
            req = urllib.request.Request(
                url + route, canonical(body).encode(), {"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            msg = exc.read().decode()
            exc.close()
            if exc.code < 500 or attempt == attempts - 1:
                raise ApiError(exc.code, msg) from exc
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt == attempts - 1:
                raise
        time.sleep(0.05 * 2**attempt)


def work(url, run, worker):
    deadline = time.monotonic() + 90
    committed = 0
    while time.monotonic() < deadline:
        task = request(url, "/claim", {"run": run, "worker": worker, "lease_seconds": 5})["task"]
        if task is None:
            status = request(url, "/status", {"run": run})
            if status["terminal"]:
                if not status["successful"]:
                    raise RuntimeError("run exhausted retries")
                return committed
            time.sleep(0.02)
            continue
        if task["rule"] != RULE or digest(task["rows"]) != task["input_sha256"]:
            raise ValueError("task identity mismatch")
        args = commit_args(task)
        try:
            request(
                url,
                "/renew",
                {k: task[k] for k in ("run", "shard", "token", "worker")} | {"lease_seconds": 5},
            )
            request(url, "/commit", args)
            committed += 1
        except ApiError as exc:
            if exc.status != 409:
                raise
            # Work longer than the lease is discarded, never force-committed.
    raise TimeoutError("worker deadline exceeded")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--url", required=True)
    p.add_argument("--run", required=True)
    p.add_argument("--worker", required=True)
    args = p.parse_args()
    print(canonical({"worker": args.worker, "committed": work(args.url, args.run, args.worker)}))
