import os
import unittest
from unittest import mock

from logalizer import cli, config


class TestParseDuration(unittest.TestCase):
    def test_units(self):
        self.assertEqual(cli.parse_duration("30s").total_seconds(), 30)
        self.assertEqual(cli.parse_duration("15m").total_seconds(), 900)
        self.assertEqual(cli.parse_duration("1h").total_seconds(), 3600)
        self.assertEqual(cli.parse_duration("24h").total_seconds(), 86400)
        self.assertEqual(cli.parse_duration("7d").total_seconds(), 604800)

    def test_invalid_raises(self):
        with self.assertRaises(ValueError):
            cli.parse_duration("nope")


class TestBuildTimeFilter(unittest.TestCase):
    def test_absolute_range(self):
        f = cli.build_time_filter("2026-08-25T10:00:00Z", "2026-08-25T14:00:00Z", "24h")
        rng = f["query"]["range"]["@timestamp"]
        self.assertEqual(rng["gte"], "2026-08-25T10:00:00Z")
        self.assertEqual(rng["lte"], "2026-08-25T14:00:00Z")
        self.assertEqual(rng["format"], "strict_date_optional_time")
        self.assertEqual(f["meta"]["field"], "@timestamp")

    def test_relative_range(self):
        f = cli.build_time_filter(None, None, "1h")
        rng = f["query"]["range"]["@timestamp"]
        self.assertIn("gte", rng)
        self.assertIn("lte", rng)

    def test_only_one_of_from_to_is_error(self):
        with self.assertRaises(cli.UsageError):
            cli.build_time_filter("2026-08-25T10:00:00Z", None, "24h")


class TestHelpJson(unittest.TestCase):
    def test_help_json_has_flags_and_exit_codes(self):
        hj = cli.help_json()
        self.assertEqual(hj["name"], "logalizer")
        self.assertIn("flags", hj)
        self.assertIn("exit_codes", hj)
        self.assertIn("io_contract", hj)


class TestMainReadsEnv(unittest.TestCase):
    def test_env_credentials_reach_settings(self):
        # Patch load_config + Client so no real network/config is touched.
        env = {
            "KIBANA_URL": "https://k.example",
            "KIBANA_USERNAME": "u",
            "KIBANA_PASSWORD": "p",
        }
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch("logalizer.cli.load_config", return_value={}), \
             mock.patch("logalizer.cli.Client") as ClientMock, \
             mock.patch("logalizer.cli.indexpatterns.resolve_index_pattern", return_value=None):
            rc = cli.main(["--index", "logs-*"])
            # resolve_index_pattern returned None → usage error exit 2,
            # but Client must have been constructed with env credentials.
            self.assertEqual(rc, 2)
            ClientMock.assert_called_once()
            kw = ClientMock.call_args
            self.assertEqual(kw[0][0], "https://k.example")
            self.assertEqual(kw[0][1], "u")
            self.assertEqual(kw[0][2], "p")

    def test_kibana_insecure_env_reaches_client(self):
        env = {
            "KIBANA_URL": "https://k.example",
            "KIBANA_USERNAME": "u",
            "KIBANA_PASSWORD": "p",
            "KIBANA_INSECURE": "1",
        }
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch("logalizer.cli.load_config", return_value={}), \
             mock.patch("logalizer.cli.Client") as ClientMock, \
             mock.patch("logalizer.cli.indexpatterns.resolve_index_pattern", return_value=None):
            cli.main(["--index", "logs-*"])
            ClientMock.assert_called_once()
            self.assertTrue(ClientMock.call_args.kwargs.get("insecure"))

    def test_kibana_insecure_false_overrides_config_true(self):
        cfg = {"kibana": {"insecure": "true"}, "defaults": {}}
        s = config.build_settings({"KIBANA_INSECURE": "0"}, cfg, space=None)
        self.assertFalse(s.insecure)


if __name__ == "__main__":
    unittest.main()
