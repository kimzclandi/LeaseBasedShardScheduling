import concurrent.futures
import tempfile
import unittest
from pathlib import Path
from shardlab.core import Store, Conflict, Missing, commit_args, digest, transform


class Contracts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.now = 1000.0
        self.path = Path(self.tmp.name) / "db.sqlite"
        self.store = Store(self.path, clock=lambda: self.now)
        self.data = [
            {"text": "  Ａlpha  training sample  "},
            {"text": "Alpha training sample"},
            {"text": "Beta training sample"},
            {"text": " "},
            {"text": 23},
        ]
        self.store.submit("r", self.data, shard_size=1, max_attempts=2)

    def claim(self):
        return self.store.claim("r", "w", 1)["task"]

    def finish(self):
        while task := self.claim():
            self.store.commit(**commit_args(task))
        return self.store.publish("r")

    def test_normalization_and_reasons(self):
        result = transform([{"row_id": str(i), "raw": r} for i, r in enumerate(self.data)])
        self.assertEqual(result[0]["text"], "Alpha training sample")
        self.assertEqual(result[3]["reason"], "short_text")
        self.assertEqual(result[4]["reason"], "invalid_text_schema")

    def test_submit_is_idempotent(self):
        self.assertTrue(self.store.submit("r", self.data, 1, 2)["replayed"])

    def test_changed_input_and_config_rejected(self):
        with self.assertRaises(Conflict):
            self.store.submit("r", self.data + [{}], 1, 2)
        with self.assertRaises(Conflict):
            self.store.submit("r", self.data, 2, 2)

    def test_concurrent_claims_are_exclusive(self):
        with concurrent.futures.ThreadPoolExecutor(8) as pool:
            tasks = list(pool.map(lambda i: self.store.claim("r", f"w{i}", 1)["task"], range(8)))
        self.assertEqual(sorted(t["shard"] for t in tasks if t), list(range(5)))

    def test_lost_ack_replay_survives_restart(self):
        t = self.claim()
        args = commit_args(t)
        self.assertFalse(self.store.commit(**args)["replayed"])
        restarted = Store(self.path, clock=lambda: self.now)
        self.assertTrue(restarted.commit(**args)["replayed"])
        self.assertEqual(restarted.status("r")["states"]["done"], 1)

    def test_changed_replay_rejected(self):
        args = commit_args(self.claim())
        self.store.commit(**args)
        args["results"][0]["text"] = "Changed training sample"
        args["results"][0]["text_sha256"] = digest(args["results"][0]["text"])
        with self.assertRaises(Conflict):
            self.store.commit(**args)

    def test_concurrent_commit_replays_write_once(self):
        args = commit_args(self.claim())
        with concurrent.futures.ThreadPoolExecutor(8) as pool:
            results = list(pool.map(lambda _: self.store.commit(**args), range(8)))
        self.assertEqual(sum(not r["replayed"] for r in results), 1)
        self.assertEqual(sum(e["kind"] == "committed" for e in self.store.status("r")["events"]), 1)

    def test_wrong_worker_cannot_commit(self):
        args = commit_args(self.claim())
        args["worker"] = "other"
        with self.assertRaises(Conflict):
            self.store.commit(**args)

    def test_expired_token_rejected_before_reassignment(self):
        args = commit_args(self.claim())
        self.now += 1
        with self.assertRaises(Conflict):
            self.store.commit(**args)

    def test_retry_fences_late_worker(self):
        old = self.claim()
        self.now += 2
        new = self.claim()
        self.assertEqual(old["shard"], new["shard"])
        self.assertGreater(new["token"], old["token"])
        with self.assertRaises(Conflict):
            self.store.commit(**commit_args(old))
        self.store.commit(**commit_args(new))

    def test_renewal_extends_live_lease(self):
        task = self.claim()
        self.now += 0.5
        self.store.renew(
            **{k: task[k] for k in ("run", "shard", "token", "worker")}, lease_seconds=2
        )
        self.now += 1
        self.store.commit(**commit_args(task))

    def test_expired_lease_cannot_be_resurrected(self):
        task = self.claim()
        self.now += 2
        with self.assertRaises(Conflict):
            self.store.renew(**{k: task[k] for k in ("run", "shard", "token", "worker")})

    def test_exhaustion_blocks_publication(self):
        self.claim()
        self.now += 2
        self.claim()
        self.now += 2
        self.claim()
        self.assertEqual(self.store.status("r")["states"]["dead"], 1)
        with self.assertRaises(Conflict):
            self.store.publish("r")

    def test_incomplete_run_cannot_publish(self):
        with self.assertRaises(Conflict):
            self.store.publish("r")

    def test_cross_shard_dedup_and_quarantine(self):
        body = self.finish()["manifest"]
        self.assertEqual(len(body["records"]), 2)
        self.assertEqual(len(body["duplicates"]), 1)
        self.assertEqual(len(body["quarantine"]), 2)
        self.assertEqual(body["duplicates"][0]["duplicate_of"], "00000000")

    def test_manifest_independent_of_completion_order(self):
        tasks = []
        while task := self.claim():
            tasks.append(task)
        for task in reversed(tasks):
            self.store.commit(**commit_args(task))
        result = self.store.publish("r")
        other = Store(Path(self.tmp.name) / "other.db", clock=lambda: self.now)
        other.submit("r", self.data, 1, 2)
        while task := other.claim("r", "other", 1)["task"]:
            other.commit(**commit_args(task))
        self.assertEqual(other.publish("r"), result)

    def test_publication_replay_and_restart(self):
        first = self.finish()
        self.now += 100
        self.assertEqual(Store(self.path).publish("r"), first)
        self.assertEqual(digest(first["manifest"]), first["sha256"])

    def test_incomplete_result_rolls_back(self):
        args = commit_args(self.claim())
        args["results"] = []
        with self.assertRaises(ValueError):
            self.store.commit(**args)
        self.assertNotIn("done", self.store.status("r")["states"])

    def test_wrong_lineage_and_digest_rejected(self):
        task = self.claim()
        args = commit_args(task)
        args["results"][0]["row_id"] = "bad"
        with self.assertRaises(ValueError):
            self.store.commit(**args)
        args = commit_args(task)
        args["results"][0]["text_sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            self.store.commit(**args)

    def test_rule_and_input_identity_rejected(self):
        task = self.claim()
        for key in ["rule", "input_sha256"]:
            args = commit_args(task)
            args[key] = "wrong"
            with self.assertRaises(Conflict):
                self.store.commit(**args)

    def test_unknown_run_is_not_success(self):
        with self.assertRaises(Missing):
            self.store.status("missing")

    def test_invalid_configuration(self):
        for seconds in [float("nan"), -1, 301]:
            with self.assertRaises(ValueError):
                self.store.claim("r", "w", seconds)
        with self.assertRaises(ValueError):
            self.store.submit("empty", [])


if __name__ == "__main__":
    unittest.main()
