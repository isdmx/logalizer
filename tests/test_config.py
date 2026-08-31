import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from logalizer import config


class TestXdgPaths(unittest.TestCase):
    def test_config_home_env(self):
        with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": "/x/cfg"}):
            self.assertEqual(config.xdg_config_home(), Path("/x/cfg"))

    def test_config_home_default(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(config.xdg_config_home(), Path.home() / ".config")


class TestConfigFile(unittest.TestCase):
    def test_load_config_file(self):
        d = Path(tempfile.mkdtemp())
        f = d / "config.ini"
        f.write_text(
            "[kibana]\nurl = https://k.example\nusername = bob\ninsecure = true\n\n"
            "[defaults]\nspace = default\nindex = logs-*\n"
            "fields = @timestamp,level\ntimeout = 90\n"
        )
        cfg = config.load_config(f)
        self.assertEqual(cfg["kibana"]["url"], "https://k.example")
        self.assertEqual(cfg["kibana"]["username"], "bob")
        self.assertEqual(cfg["kibana"]["insecure"], "true")
        self.assertEqual(cfg["defaults"]["space"], "default")
        self.assertEqual(cfg["defaults"]["index"], "logs-*")
        self.assertEqual(cfg["defaults"]["timeout"], "90")

    def test_missing_config_file_returns_empty(self):
        cfg = config.load_config(Path("/nonexistent/nope.ini"))
        self.assertEqual(cfg, {})


class TestBuildSettings(unittest.TestCase):
    def test_env_overrides_config(self):
        cfg = {
            "kibana": {"url": "https://cfg", "username": "cfguser", "insecure": "false"},
            "defaults": {"space": "cfgspace"},
        }
        env = {
            "KIBANA_URL": "https://env",
            "KIBANA_USERNAME": "envuser",
            "KIBANA_PASSWORD": "envpass",
        }
        s = config.build_settings(env, cfg, space=None)
        self.assertEqual(s.url, "https://env")
        self.assertEqual(s.username, "envuser")
        self.assertEqual(s.password, "envpass")
        self.assertEqual(s.space, "cfgspace")  # no env/flag space

    def test_flag_space_overrides_all(self):
        cfg = {"kibana": {}, "defaults": {"space": "cfgspace"}}
        env = {"KIBANA_SPACE": "envspace"}
        s = config.build_settings(env, cfg, space="flagspace")
        self.assertEqual(s.space, "flagspace")

    def test_defaults(self):
        s = config.build_settings({}, {}, space=None)
        self.assertEqual(s.space, "default")
        self.assertEqual(s.timeout, 120)
        self.assertFalse(s.insecure)

    def test_insecure_precedence(self):
        cfg = {"kibana": {"insecure": "false"}, "defaults": {}}
        self.assertTrue(config.build_settings({}, cfg, space=None, insecure=True).insecure)
        self.assertTrue(config.build_settings({"KIBANA_INSECURE": "1"}, cfg, space=None).insecure)


class TestWriteConfig(unittest.TestCase):
    def test_write_and_roundtrip(self):
        d = Path(tempfile.mkdtemp())
        f = d / "config.ini"
        config.write_config(
            {"kibana": {"url": "https://k.example", "username": "bob",
                        "password": "hunter2", "insecure": "true"},
             "defaults": {"space": "default", "index": "logs-*"}},
            path=f,
        )
        self.assertTrue(f.exists())
        cfg = config.load_config(f)
        self.assertEqual(cfg["kibana"]["url"], "https://k.example")
        self.assertEqual(cfg["kibana"]["password"], "hunter2")
        self.assertEqual(cfg["defaults"]["index"], "logs-*")

    def test_write_sets_0600_perms(self):
        d = Path(tempfile.mkdtemp())
        f = d / "config.ini"
        config.write_config({"kibana": {"url": "https://k.example"}}, path=f)
        mode = stat.S_IMODE(f.stat().st_mode)
        self.assertEqual(mode, 0o600)

    def test_write_creates_parent_dirs(self):
        d = Path(tempfile.mkdtemp()) / "nested" / "deep"
        f = d / "config.ini"
        config.write_config({"kibana": {"url": "x"}}, path=f)
        self.assertTrue(f.exists())


class TestProfiles(unittest.TestCase):
    def test_list_profiles(self):
        cfg = {"profile.prod": {}, "profile.staging": {}, "kibana": {}, "defaults": {}}
        self.assertEqual(config.list_profiles(cfg), ["default", "prod", "staging"])

    def test_list_profiles_includes_legacy_default(self):
        cfg = {"kibana": {"url": "https://l"}, "defaults": {"space": "default"},
               "profile.staging": {}}
        self.assertEqual(config.list_profiles(cfg), ["default", "staging"])

    def test_list_profiles_no_default_when_no_legacy(self):
        cfg = {"profile.prod": {}, "profile.staging": {}}
        self.assertEqual(config.list_profiles(cfg), ["prod", "staging"])

    def test_select_profile_splits_flat_keys(self):
        cfg = {"profile.prod": {"url": "https://p", "username": "u", "password": "pw",
                                "insecure": "true", "space": "aiorch", "index": "logs-*"}}
        sel = config.select_profile(cfg, "prod")
        self.assertEqual(sel["kibana"]["url"], "https://p")
        self.assertEqual(sel["kibana"]["insecure"], "true")
        self.assertEqual(sel["defaults"]["space"], "aiorch")
        self.assertEqual(sel["defaults"]["index"], "logs-*")
        self.assertNotIn("space", sel["kibana"])

    def test_select_profile_unknown_raises(self):
        with self.assertRaises(ValueError):
            config.select_profile({}, "nope")

    def test_select_profile_none_returns_legacy(self):
        cfg = {"kibana": {"url": "https://l"}, "defaults": {"space": "default"}}
        sel = config.select_profile(cfg, None)
        self.assertEqual(sel["kibana"]["url"], "https://l")
        self.assertEqual(sel["defaults"]["space"], "default")

    def test_select_profile_default_resolves_legacy(self):
        cfg = {"kibana": {"url": "https://l", "username": "lu"},
               "defaults": {"space": "default"}}
        sel = config.select_profile(cfg, "default")
        self.assertEqual(sel["kibana"]["url"], "https://l")
        self.assertEqual(sel["defaults"]["space"], "default")

    def test_build_settings_default_profile_resolves_legacy(self):
        cfg = {"kibana": {"url": "https://l", "username": "u", "password": "p"}}
        s = config.build_settings({}, cfg, profile="default")
        self.assertEqual(s.url, "https://l")

    def test_build_settings_uses_profile(self):
        cfg = {"profile.prod": {"url": "https://p", "username": "u", "password": "pw",
                                "space": "aiorch"}}
        s = config.build_settings({}, cfg, profile="prod")
        self.assertEqual(s.url, "https://p")
        self.assertEqual(s.space, "aiorch")

    def test_env_overrides_profile(self):
        cfg = {"profile.prod": {"url": "https://p", "username": "u", "password": "pw"}}
        s = config.build_settings({"KIBANA_URL": "https://env"}, cfg, profile="prod")
        self.assertEqual(s.url, "https://env")


if __name__ == "__main__":
    unittest.main()
