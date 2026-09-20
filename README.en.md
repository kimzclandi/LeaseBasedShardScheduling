# AI Data Shard Lab · Shard Processing and Failure Recovery

[简体中文](README.md) | **English**

[![reliability-contracts](https://github.com/kimzclandi/LeaseBasedShardScheduling/actions/workflows/ci.yml/badge.svg)](https://github.com/kimzclandi/LeaseBasedShardScheduling/actions/workflows/ci.yml)

**What happens if a worker finishes processing but loses the commit response? Can an expired worker overwrite a newer result after it recovers?**

This small AI text-processing experiment uses the Python standard library. An HTTP coordinator assigns shards, independent worker processes normalize text and perform basic quality checks, and SQLite stores leases, committed results and events. Publication produces a deterministic data manifest with source hashes.

**Verified scope: one machine, multiple processes, loopback HTTP and synthetic text.** The project implements leases, fencing and idempotency commonly used in distributed task processing. It does not establish multi-machine deployment, distributed storage, consensus or production-scale behavior. There is no model training; basic cleaning rules are not semantic quality assessment.

## Project history (added 2026-09-20)

According to the maintainer, related early work began locally around June 2026 before consolidation and upload to GitHub. This approximate starting point does not mean all current features or experiments were completed then. Later implementations, experiments and maintenance retain their actual version and run dates.

## Quick verification

Requires Python 3.12+ on macOS or Linux. No third-party runtime dependencies, model downloads or paid APIs.

```bash
git clone https://github.com/kimzclandi/LeaseBasedShardScheduling.git
cd LeaseBasedShardScheduling
python3 -m unittest discover -s tests -v
python3 scripts/verify_evidence.py
python3 scripts/demo.py --out runs/my-first-run --repeats 1
```

`--out` must name a new directory to preserve existing experiments. The last command starts an actual HTTP server and worker subprocesses, injects failures and cleans up processes on exit. SQLite and JSON records remain in the output directory. The service listens only on `127.0.0.1`, uses a temporary port by default and is not externally deployed.

| Entry point | What to inspect |
|---|---|
| [Experiment report](docs/RESULTS.md) | Environment, timings, failure results and limitations |
| [Saved raw records](evidence/local/summary.json) | Individual runs, worker receipts and source hashes |
| [Architecture and semantics](docs/ARCHITECTURE.md) | State machine, transaction boundaries, leases and fencing |
| [Code review path](docs/REVIEW.md) | Five key implementations and counterexamples |
| [Tests](tests/test_core.py) | Concurrent claims, expired commits, recovery and cross-shard deduplication |

Linked technical documents retain their original language.

## Inputs, processing and outputs

- Input: 1,200 fixed synthetic records in 24 shards: 1,000 unique valid records, 100 duplicates and 100 blank or incorrectly typed records.
- Workers: NFKC and whitespace normalization, string-type and minimum-length checks. Each row produces an original-record hash, stable row ID and acceptance/quarantine reason.
- Coordinator: lease expiry and retries, increasing attempt tokens, conditional commits and persistent events. Identical submissions can replay their acknowledgment; conflicting results cannot overwrite committed data.
- Publication: all shards must succeed first. Row IDs determine which duplicate is retained. Outputs include accepted data, quarantined records, duplicate mappings and source hashes, independent of worker completion order.

## Failure validation

The experiment compares one worker, four workers and four workers with injected failures: SIGKILL after a worker claims a shard, coordinator SIGKILL and restart after commit, duplicate submission and stale-lease submission. Every run should produce the same manifest.

This is **retryable execution with idempotent database commits**, not general exactly-once execution. Expired work can run more than once. File writes, model calls and other external side effects are outside the transaction guarantee.

## Limitations and next steps

- SQLite and publication are single-node bottlenecks. HA, network partitions and machine power loss have not been tested.
- Workers are trusted. Hashes establish identity and detect corruption; they cannot prevent a malicious worker from fabricating valid-looking results.
- The API serves local experiments only. It has no authentication, TLS or tenant isolation and must not be exposed publicly.
- Batch inputs and manifests are processed in memory. Exact deduplication does not replace semantic deduplication or train/test contamination detection.
- HTTP and transaction overhead may slow small tasks. Timings describe the measured machine, not linear scalability.
- Real expansion would require object storage, a production queue/database and load/failure matrices before multi-machine deployment. These are not implemented.

Historical experiments and maintenance retain their recorded dates. Code, tests and documentation were developed with AI assistance. This experiment verifies single-machine, multi-process behavior, not multi-machine deployment or production load. Code and synthetic examples: [MIT](LICENSE).

[2026-09-19 maintenance and validation scope](docs/maintenance/2026-09-19/README.md)

[2026-09-21 maintenance and validation](docs/maintenance/2026-09-21/README.md)
