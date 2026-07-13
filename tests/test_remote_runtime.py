import base64
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

import remote_runtime

PNG = b"\x89PNG\r\n\x1a\nmock"


class MockHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _json(self, payload, status=200):
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/v1/models":
            return self._json({"data": [{"id": "mock-model"}]})
        if self.path == "/v2/image-endpoint/status/job-1":
            return self._json({"status": "COMPLETED", "output": {"image": base64.b64encode(PNG).decode()}})
        self._json({}, 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        _ = self.rfile.read(length)
        if self.path == "/v1/chat/completions":
            return self._json({"choices": [{"message": {"content": "mock reply"}}]})
        if self.path == "/v2/image-endpoint/run":
            return self._json({"id": "job-1"})
        self._json({}, 404)


class RemoteRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), MockHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close()

    def test_openai_compatible_models_and_chat(self):
        self.assertEqual(remote_runtime.openai_models(self.base), ["mock-model"])
        reply = remote_runtime.openai_chat(self.base, "", "mock-model",
            [{"role": "user", "content": "hello"}], 20, 0.2)
        self.assertEqual(reply, "mock reply")

    def test_runpod_serverless_image_result(self):
        with mock.patch.object(remote_runtime, "RUNPOD_SERVERLESS_BASE", self.base + "/v2"):
            data, job_id = remote_runtime.runpod_serverless_image(
                "image-endpoint", "key", {"1": {"class_type": "Mock"}}, timeout=5)
        self.assertEqual(job_id, "job-1")
        self.assertEqual(data, PNG)

    def test_pod_status_variants(self):
        self.assertEqual(remote_runtime.runpod_pod_status({"desiredStatus": "RUNNING"}), "RUNNING")
        self.assertEqual(remote_runtime.runpod_pod_status({"runtime": {"status": "ready"}}), "READY")

    def test_idle_manager_stops_after_delay(self):
        manager = remote_runtime._PodAutoStopManager()
        manager.configure("llm-test", "pod-1", "key", 60, True)
        manager.begin("llm-test"); manager.end("llm-test")
        with mock.patch.object(remote_runtime, "runpod_pod_info", return_value={"status": "RUNNING"}), \
             mock.patch.object(remote_runtime, "runpod_pod_action", return_value={}) as action:
            manager.check_idle_once(manager.status("llm-test")["last_activity"] + 61)
        action.assert_called_once_with("pod-1", "key", "stop")


if __name__ == "__main__":
    unittest.main()
