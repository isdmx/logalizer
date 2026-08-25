import tempfile
import unittest
from pathlib import Path
from unittest import mock

from logalizer import init
from logalizer.config import load_config


class _Args:
    def __init__(self, **kw):
        self.url = kw.get("url")
        self.username = kw.get("username")
        self.password = kw.get("password")
        self.space = kw.get("space")
        self.index = kw.get("index")
        self.insecure = kw.get("insecure", False)


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

    def test_interactive_prompts_when_missing(self):
        d = Path(tempfile.mkdtemp()) / "config.ini"
        args = _Args(url="https://k.example")  # missing username+password -> interactive
        with mock.patch("builtins.input", side_effect=["alice"]), \
             mock.patch("getpass.getpass", return_value="pw"):
            rc = init.run_init(args, {}, config_path=d)
        self.assertEqual(rc, 0)
        cfg = load_config(d)
        self.assertEqual(cfg["kibana"]["username"], "alice")
        self.assertEqual(cfg["kibana"]["password"], "pw")

    def test_missing_required_returns_2(self):
        d = Path(tempfile.mkdtemp()) / "config.ini"
        args = _Args()
        with mock.patch("builtins.input", side_effect=["", ""]), \
             mock.patch("getpass.getpass", return_value=""):
            rc = init.run_init(args, {}, config_path=d)
        self.assertEqual(rc, 2)
        self.assertFalse(d.exists())

    def test_merges_existing_keys(self):
        d = Path(tempfile.mkdtemp()) / "config.ini"
        from logalizer.config import write_config
        write_config({"kibana": {"url": "https://old", "username": "u", "password": "p"},
                      "defaults": {"space": "default", "fields": "@timestamp,level"}},
                     path=d)
        args = _Args(url="https://new", username="u2", password="p2")
        rc = init.run_init(args, {}, config_path=d)
        self.assertEqual(rc, 0)
        cfg = load_config(d)
        self.assertEqual(cfg["kibana"]["url"], "https://new")
        self.assertEqual(cfg["defaults"]["fields"], "@timestamp,level")  # preserved


if __name__ == "__main__":
    unittest.main()
