import json
import os
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer

import app
import secret_store


class CloudHttpApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.makedirs(app.DATA_DIR, exist_ok=True)
        app.init_db()
        secret_store._SESSION.clear()
        secret_store._keyring_usable = lambda: False
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    @classmethod
    def request(cls, path, method="GET", payload=None):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            cls.base + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json"} if data is not None else {},
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    def test_settings_route_masks_secret_values(self):
        status, result = self.request("/api/settings", "POST", {
            "llm_backend": "runpod_serverless",
            "llm_runpod_endpoint_id": "endpoint-test",
            "runpod_api_key": "rpa-secret-http-test",
        })
        self.assertEqual(status, 200)
        self.assertTrue(result["ok"])

        status, settings = self.request("/api/settings")
        self.assertEqual(status, 200)
        self.assertEqual(settings["llm_backend"], "runpod_serverless")
        self.assertEqual(settings["llm_runpod_endpoint_id"], "endpoint-test")
        self.assertTrue(settings["runpod_api_key_set"])
        serialized = json.dumps(settings)
        self.assertNotIn("rpa-secret-http-test", serialized)
        self.assertNotIn('"runpod_api_key"', serialized)

    def test_secret_status_route_returns_metadata_only(self):
        secret_store.save_secret("image_remote_api_key", "image-secret-http-test")
        status, result = self.request("/api/cloud/secrets/status")
        self.assertEqual(status, 200)
        self.assertTrue(result["image_remote_api_key"]["configured"])
        self.assertNotIn("image-secret-http-test", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
