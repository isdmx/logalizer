import os
import unittest

from logalizer import indexpatterns, reporting
from logalizer.client import Client
from logalizer.config import build_settings


@unittest.skipUnless(
    os.environ.get("KIBANA_URL") and os.environ.get("KIBANA_USERNAME")
    and os.environ.get("KIBANA_PASSWORD"),
    "set KIBANA_URL/KIBANA_USERNAME/KIBANA_PASSWORD to run integration tests",
)
class TestIntegration(unittest.TestCase):
    def setUp(self):
        s = build_settings(os.environ, {})
        self.client = Client(s.url, s.username, s.password, insecure=True)

    def test_list_spaces(self):
        spaces = indexpatterns.list_spaces(self.client)
        self.assertIn("default", spaces)

    def test_list_index_patterns(self):
        titles = indexpatterns.list_index_patterns(self.client, "default")
        self.assertTrue(any(t.endswith("*") for t in titles))

    def test_export_roundtrip(self):
        idx = os.environ.get("KIBANA_TEST_INDEX", "app-logs-*")
        index_id = indexpatterns.resolve_index_pattern(self.client, "default", idx)
        self.assertIsNotNone(index_id)
        job_id = reporting.submit(
            self.client, "default", index_id, "", None, ["@timestamp", "msg"])
        reporting.poll(self.client, job_id, timeout=120)
        csv_text = reporting.download(self.client, job_id)
        self.assertTrue(csv_text.startswith('"@timestamp"'))

    def test_ping_all_pass(self):
        from logalizer import ping
        from logalizer.config import config_file_path
        s = build_settings(os.environ, {})
        rc = ping.run_ping(s, config_file_path())
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
