import os
import shutil
import tempfile
import unittest

TEST_DATA = tempfile.mkdtemp(prefix="amiorai-v401-test-")
os.environ["AMIORAI_DATA_DIR"] = TEST_DATA

import app
import secret_store


class AppRemoteSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.init_db()
        secret_store._SESSION.clear()
        secret_store._keyring_usable = lambda: False

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TEST_DATA, ignore_errors=True)

    def test_provider_settings_round_trip(self):
        app.save_settings({
            "llm_backend": "openai_compatible",
            "llm_remote_url": "http://example.invalid/v1",
            "image_backend": "runpod_pod",
            "runpod_idle_minutes": "15",
        })
        settings = app.get_settings()
        self.assertEqual(settings["llm_backend"], "openai_compatible")
        self.assertEqual(settings["image_backend"], "runpod_pod")
        self.assertEqual(settings["runpod_idle_minutes"], "15.0")

    def test_remote_secrets_never_enter_sqlite(self):
        secret_store.save_secret("runpod_api_key", "super-secret")
        app.save_settings({"runpod_api_key": "must-not-persist"})
        with app.db() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key='runpod_api_key'").fetchone()
        self.assertIsNone(row)
        safe = app._get_safe_settings()
        self.assertNotIn("runpod_api_key", safe)
        self.assertTrue(safe["runpod_api_key_set"])

    def test_invalid_backends_are_safely_normalized(self):
        app.save_settings({"llm_backend": "unknown", "image_backend": "unknown"})
        settings = app.get_settings()
        self.assertEqual(settings["llm_backend"], "lmstudio")
        self.assertEqual(settings["image_backend"], "comfy_local")


if __name__ == "__main__":
    unittest.main()
