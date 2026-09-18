import tempfile
import unittest
import urllib.request
from pathlib import Path
from scripts.demo import start, stop
from shardlab.worker import request, ApiError


class HttpBoundary(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.server, cls.url = start(Path(cls.tmp.name) / "state.sqlite")

    @classmethod
    def tearDownClass(cls):
        stop(cls.server)
        cls.tmp.cleanup()

    def test_unknown_route(self):
        with self.assertRaises(ApiError) as ctx:
            request(self.url, "/not-found", {})
        self.assertEqual(ctx.exception.status, 404)

    def test_unknown_run(self):
        with self.assertRaises(ApiError) as ctx:
            request(self.url, "/status", {"run": "missing"})
        self.assertEqual(ctx.exception.status, 404)

    def test_invalid_json(self):
        req = urllib.request.Request(self.url + "/submit", b"{invalid", method="POST")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(ctx.exception.code, 400)
        ctx.exception.close()

    def test_scalar_body(self):
        with self.assertRaises(ApiError) as ctx:
            request(self.url, "/submit", [])
        self.assertEqual(ctx.exception.status, 400)

    def test_input_conflict_and_publish_gate(self):
        request(
            self.url, "/submit", {"run": "http", "records": [{"text": "Example text for testing"}]}
        )
        with self.assertRaises(ApiError) as ctx:
            request(self.url, "/submit", {"run": "http", "records": [{}]})
        self.assertEqual(ctx.exception.status, 409)
        with self.assertRaises(ApiError) as ctx:
            request(self.url, "/publish", {"run": "http"})
        self.assertEqual(ctx.exception.status, 409)
