"""A real committed transaction followed by a truncated HTTP response."""
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from shardlab.core import Store, canonical, commit_args
from shardlab.worker import request


class LostResponse(unittest.TestCase):
    def test_partial_commit_response_is_retried_without_duplicate_commit(self):
        with tempfile.TemporaryDirectory() as temp:
            store = Store(Path(temp) / 'state.sqlite')
            store.submit('run', [{'text': 'A complete test record.'}])
            task = store.claim('run', 'worker')['task']
            calls = []

            class Handler(BaseHTTPRequestHandler):
                def log_message(self, *args):
                    pass

                def do_POST(self):
                    args = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                    result = store.commit(**args)
                    calls.append(result)
                    body = canonical(result).encode()
                    self.send_response(200)
                    self.send_header('Content-Length', str(len(body)))
                    self.end_headers()
                    self.wfile.write(body[:5] if len(calls) == 1 else body)
                    self.wfile.flush()
                    self.close_connection = True

            server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                result = request(f'http://127.0.0.1:{server.server_port}', '/commit', commit_args(task))
                self.assertTrue(result['replayed'])
                self.assertEqual(len(calls), 2)
                self.assertEqual(sum(e['kind'] == 'committed' for e in store.status('run')['events']), 1)
                self.assertEqual(len(store.publish('run')['manifest']['records']), 1)
            finally:
                server.shutdown()
                thread.join()
                server.server_close()
