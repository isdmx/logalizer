import tempfile
import unittest
from pathlib import Path
from unittest import mock

from logalizer import ping
from logalizer.config import Settings
from logalizer.client import ClientError


def _settings(**kw):
    defaults = dict(url="https://k.example", username="u", password="p",
                    space="default", index="logs-*", insecure=False)
    defaults.update(kw)
    return Settings(**defaults)


class _FakeClient:
    def __init__(self, responses):
        self._responses = list(responses)

    def request(self, method, path, body=None):
        resp = self._responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        return resp


class TestPing(unittest.TestCase):
    def _config_path(self, exists=True):
        d = Path(tempfile.mkdtemp()) / "config.ini"
        if exists:
            d.write_text("[kibana]\nurl = x\n")
        return d

    def test_missing_config_returns_2(self):
        s = _settings()
        rc = ping.run_ping(s, Path(tempfile.mkdtemp()) / "nope.ini")
        self.assertEqual(rc, 2)

    def test_missing_creds_returns_2(self):
        s = _settings(username="", password="")
        rc = ping.run_ping(s, self._config_path())
        self.assertEqual(rc, 2)

    def test_network_error_returns_5(self):
        s = _settings()
        fake = _FakeClient([ClientError("network error: refused", 5)])
        with mock.patch("logalizer.ping.Client", return_value=fake):
            rc = ping.run_ping(s, self._config_path())
        self.assertEqual(rc, 5)

    def test_auth_failure_returns_3(self):
        s = _settings()
        fake = _FakeClient([
            (200, '{"version":{"number":"7.17.29"}}'),
            (401, '{"error":"unauthorized"}'),
        ])
        with mock.patch("logalizer.ping.Client", return_value=fake):
            rc = ping.run_ping(s, self._config_path())
        self.assertEqual(rc, 3)

    def test_space_missing_returns_2(self):
        s = _settings()
        fake = _FakeClient([
            (200, '{"version":{"number":"7.17.29"}}'),
            (200, '{"username":"u","roles":["reporting_user"]}'),
            (200, '[{"id":"other"}]'),
        ])
        with mock.patch("logalizer.ping.Client", return_value=fake):
            rc = ping.run_ping(s, self._config_path())
        self.assertEqual(rc, 2)

    def test_index_missing_returns_2(self):
        s = _settings()
        fake = _FakeClient([
            (200, '{"version":{"number":"7.17.29"}}'),
            (200, '{"username":"u","roles":["reporting_user"]}'),
            (200, '[{"id":"default"}]'),
            (200, '{"saved_objects":[]}'),
        ])
        with mock.patch("logalizer.ping.Client", return_value=fake):
            rc = ping.run_ping(s, self._config_path())
        self.assertEqual(rc, 2)

    def test_all_pass_returns_0(self):
        s = _settings()
        fake = _FakeClient([
            (200, '{"version":{"number":"7.17.29"}}'),
            (200, '{"username":"u","roles":["reporting_user"]}'),
            (200, '[{"id":"default"}]'),
            (200, '{"saved_objects":[{"id":"abc","attributes":{"title":"logs-*"}}]}'),
        ])
        with mock.patch("logalizer.ping.Client", return_value=fake):
            rc = ping.run_ping(s, self._config_path())
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
