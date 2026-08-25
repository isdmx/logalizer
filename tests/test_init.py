import tempfile
import unittest
from pathlib import Path
from unittest import mock

from logalizer import init
from logalizer.client import ClientError
from logalizer.config import load_config, write_config


class _Args:
    def __init__(self, **kw):
        self.url = kw.get("url")
        self.username = kw.get("username")
        self.password = kw.get("password")
        self.space = kw.get("space")
        self.index = kw.get("index")
        self.insecure = kw.get("insecure", False)


class _FakeClient:
    def __init__(self, responses):
        self._responses = list(responses)

    def request(self, method, path, body=None):
        resp = self._responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        return resp


class TestConnect(unittest.TestCase):
    def test_connect_success(self):
        fake = _FakeClient([
            (200, '{"version":{"number":"7.17.29"}}'),
            (200, '{"username":"bob","roles":[]}'),
        ])
        with mock.patch("logalizer.init.Client", return_value=fake):
            client, msg = init._connect("https://k.example", "bob", "pw", False)
        self.assertIsNotNone(client)
        self.assertIn("7.17.29", msg)
        self.assertIn("bob", msg)

    def test_connect_auth_failure(self):
        fake = _FakeClient([
            (200, '{"version":{"number":"7.17.29"}}'),
            (401, '{"error":"unauthorized"}'),
        ])
        with mock.patch("logalizer.init.Client", return_value=fake):
            client, msg = init._connect("https://k.example", "bob", "bad", False)
        self.assertIsNone(client)
        self.assertIn("auth", msg.lower())

    def test_connect_network_error(self):
        fake = _FakeClient([ClientError("network error: refused", 5)])
        with mock.patch("logalizer.init.Client", return_value=fake):
            client, msg = init._connect("https://k.example", "bob", "pw", False)
        self.assertIsNone(client)


class TestPickNumbered(unittest.TestCase):
    def test_picks_by_number(self):
        with mock.patch("builtins.input", return_value="2"):
            self.assertEqual(init._pick_numbered(["a", "b", "c"], "T", "a"), "b")

    def test_enter_keeps_default(self):
        with mock.patch("builtins.input", return_value=""):
            self.assertEqual(init._pick_numbered(["a", "b"], "T", "a"), "a")

    def test_typed_name_returned(self):
        with mock.patch("builtins.input", return_value="custom"):
            self.assertEqual(init._pick_numbered(["a", "b"], "T", "a"), "custom")

    def test_no_items_falls_back_to_free_text(self):
        with mock.patch("builtins.input", return_value="typed"):
            self.assertEqual(init._pick_numbered(None, "T", "a"), "typed")


class TestRunInit(unittest.TestCase):
    def test_non_interactive_writes_config(self):
        d = Path(tempfile.mkdtemp()) / "config.ini"
        args = _Args(url="https://k.example", username="bob", password="hunter2")
        rc = init.run_init(args, {}, config_path=d)
        self.assertEqual(rc, 0)
        cfg = load_config(d)
        self.assertEqual(cfg["kibana"]["url"], "https://k.example")
        self.assertEqual(cfg["kibana"]["username"], "bob")
        self.assertEqual(cfg["kibana"]["password"], "hunter2")
        self.assertEqual(cfg["defaults"]["space"], "default")

    def test_merges_existing_keys(self):
        d = Path(tempfile.mkdtemp()) / "config.ini"
        write_config({"kibana": {"url": "https://old", "username": "u", "password": "p"},
                      "defaults": {"space": "default", "fields": "@timestamp,level"}},
                     path=d)
        args = _Args(url="https://new", username="u2", password="p2")
        rc = init.run_init(args, {}, config_path=d)
        self.assertEqual(rc, 0)
        cfg = load_config(d)
        self.assertEqual(cfg["kibana"]["url"], "https://new")
        self.assertEqual(cfg["defaults"]["fields"], "@timestamp,level")  # preserved


class TestRunInitInteractive(unittest.TestCase):
    def test_validates_and_picks_from_lists(self):
        d = Path(tempfile.mkdtemp()) / "config.ini"
        args = _Args()
        fake = _FakeClient([
            (200, '{"version":{"number":"7.17.29"}}'),
            (200, '{"username":"bob","roles":[]}'),
        ])
        # prompts: url, username, insecure, space pick, index pick
        answers = iter(["https://k.example", "bob", "", "1", "1"])
        with mock.patch("logalizer.init.Client", return_value=fake), \
             mock.patch("logalizer.init.indexpatterns.list_spaces", return_value=["s1", "s2"]), \
             mock.patch("logalizer.init.indexpatterns.list_index_patterns", return_value=["logs-*", "app-*"]), \
             mock.patch("builtins.input", side_effect=lambda *a: next(answers)), \
             mock.patch("getpass.getpass", return_value="pw"):
            rc = init.run_init(args, {}, config_path=d)
        self.assertEqual(rc, 0)
        cfg = load_config(d)
        self.assertEqual(cfg["kibana"]["url"], "https://k.example")
        self.assertEqual(cfg["defaults"]["space"], "s1")
        self.assertEqual(cfg["defaults"]["index"], "logs-*")

    def test_reprompts_until_valid(self):
        d = Path(tempfile.mkdtemp()) / "config.ini"
        args = _Args()
        fake_fail = _FakeClient([
            (200, '{"version":{"number":"7.17.29"}}'),
            (401, '{"error":"no"}'),
        ])
        fake_ok = _FakeClient([
            (200, '{"version":{"number":"7.17.29"}}'),
            (200, '{"username":"bob","roles":[]}'),
        ])
        answers = iter([
            "https://k.example",  # url
            "bob",                # username
            "",                   # insecure
            "https://k.example",  # re-prompt url (keep)
            "bob",                # re-prompt username (keep)
            "",                   # re-prompt insecure (keep)
            "1",                  # space pick
            "1",                  # index pick
        ])
        with mock.patch("logalizer.init.Client", side_effect=[fake_fail, fake_ok]) as cm, \
             mock.patch("logalizer.init.indexpatterns.list_spaces", return_value=["s1"]), \
             mock.patch("logalizer.init.indexpatterns.list_index_patterns", return_value=["logs-*"]), \
             mock.patch("builtins.input", side_effect=lambda *a: next(answers)), \
             mock.patch("getpass.getpass", return_value="pw"):
            rc = init.run_init(args, {}, config_path=d)
        self.assertEqual(rc, 0)
        self.assertEqual(cm.call_count, 2)
        cfg = load_config(d)
        self.assertEqual(cfg["defaults"]["space"], "s1")


if __name__ == "__main__":
    unittest.main()
