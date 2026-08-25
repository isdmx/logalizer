import os
import tempfile
import unittest
from pathlib import Path

from logalizer import indexpatterns, ping, reporting
from logalizer.client import Client
from logalizer.config import build_settings, write_config


def _space():
    return os.environ.get("KIBANA_TEST_SPACE", "default")


def _index():
    return os.environ.get("KIBANA_TEST_INDEX", "app-logs-*")


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
        self.assertTrue(len(spaces) > 0)

    def test_list_index_patterns(self):
        titles = indexpatterns.list_index_patterns(self.client, _space())
        self.assertTrue(any(t.endswith("*") for t in titles))

    def test_export_roundtrip(self):
        space = _space()
        index_id = indexpatterns.resolve_index_pattern(self.client, space, _index())
        self.assertIsNotNone(index_id)
        job_id = reporting.submit(
            self.client, space, index_id, "", None, ["@timestamp", "msg"])
        reporting.poll(self.client, job_id, timeout=120)
        csv_text = reporting.download(self.client, job_id)
        self.assertTrue(csv_text.startswith('"@timestamp"'))

    def test_ping_all_pass(self):
        s = build_settings(os.environ, {})
        s.space = _space()
        s.index = _index()
        cfg = Path(tempfile.mkdtemp()) / "config.ini"
        write_config(
            {"kibana": {"url": s.url, "username": s.username,
                        "password": s.password, "insecure": "true"},
             "defaults": {"space": s.space, "index": s.index}},
            path=cfg,
        )
        rc = ping.run_ping(s, cfg)
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
