import io
import json
import os
import unittest
from contextlib import redirect_stdout
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


class TestInitPingDispatch(unittest.TestCase):
    def test_init_flag_dispatches(self):
        with mock.patch("logalizer.cli.init.run_init", return_value=0) as ri, \
             mock.patch("logalizer.cli.load_config", return_value={}):
            rc = cli.main(["--init", "--url", "https://k.example",
                           "--username", "u", "--password", "p"])
        self.assertEqual(rc, 0)
        ri.assert_called_once()

    def test_ping_flag_dispatches(self):
        with mock.patch("logalizer.cli.ping.run_ping", return_value=0) as rp, \
             mock.patch("logalizer.cli.load_config", return_value={}):
            rc = cli.main(["--ping"])
        self.assertEqual(rc, 0)
        rp.assert_called_once()

    def test_help_json_lists_new_flags(self):
        hj = cli.help_json()
        flags = [f["flag"] for f in hj["flags"]]
        self.assertIn("--init", flags)
        self.assertIn("--ping", flags)
        self.assertIn("--url", flags)


class TestFormatLimit(unittest.TestCase):
    def test_format_json_wraps_output(self):
        with mock.patch("logalizer.cli.build_settings",
                        return_value=config.Settings(url="https://k", username="u", password="p", space="default", index="logs-*")), \
             mock.patch("logalizer.cli.Client"), \
             mock.patch("logalizer.cli.indexpatterns.resolve_index_pattern", return_value="idx"), \
             mock.patch("logalizer.cli.reporting.submit", return_value="j1"), \
             mock.patch("logalizer.cli.reporting.poll"), \
             mock.patch("logalizer.cli.reporting.download", return_value="a,b\n1,2\n3,4\n"), \
             mock.patch("sys.stdout.write") as w:
            rc = cli.main(["--index", "logs-*", "--format", "json"])
        self.assertEqual(rc, 0)
        written = w.call_args[0][0]
        self.assertIn('"rows"', written)
        self.assertIn('"truncated"', written)

    def test_limit_truncates(self):
        with mock.patch("logalizer.cli.build_settings",
                        return_value=config.Settings(url="https://k", username="u", password="p", space="default", index="logs-*")), \
             mock.patch("logalizer.cli.Client"), \
             mock.patch("logalizer.cli.indexpatterns.resolve_index_pattern", return_value="idx"), \
             mock.patch("logalizer.cli.reporting.submit", return_value="j1"), \
             mock.patch("logalizer.cli.reporting.poll"), \
             mock.patch("logalizer.cli.reporting.download", return_value="a,b\n1,2\n3,4\n"), \
             mock.patch("sys.stdout.write") as w:
            rc = cli.main(["--index", "logs-*", "--format", "json", "--limit", "1"])
        self.assertEqual(rc, 0)
        import json
        obj = json.loads(w.call_args[0][0])
        self.assertTrue(obj["truncated"])
        self.assertEqual(obj["count"], 1)

    def test_help_json_lists_format_and_limit(self):
        flags = [f["flag"] for f in cli.help_json()["flags"]]
        self.assertIn("--format", flags)
        self.assertIn("--limit", flags)


class TestCountMode(unittest.TestCase):
    def test_count_json(self):
        with mock.patch("logalizer.cli.build_settings",
                        return_value=config.Settings(url="https://k", username="u",
                                                     password="p", space="default", index="logs-*")), \
             mock.patch("logalizer.cli.Client"), \
             mock.patch("logalizer.cli.search.run_count",
                        return_value={"groups": [{"key": "info", "count": 2}],
                                      "total": 2, "distinct": 1, "truncated": False}) as run_count, \
             mock.patch("sys.stdout.write") as w:
            rc = cli.main(["--index", "logs-*", "--count", "--group-by", "level",
                           "--format", "json"])
        self.assertEqual(rc, 0)
        obj = json.loads(w.call_args[0][0])
        self.assertEqual(obj["total"], 2)
        self.assertEqual(obj["groups"][0]["key"], "info")
        run_count.assert_called_once()

    def test_count_requires_group_by(self):
        with mock.patch("logalizer.cli.build_settings",
                        return_value=config.Settings(url="https://k", username="u",
                                                     password="p", space="default", index="logs-*")):
            rc = cli.main(["--index", "logs-*", "--count"])
        self.assertEqual(rc, 2)

    def test_count_rejects_three_group_by_fields(self):
        with mock.patch("logalizer.cli.build_settings",
                        return_value=config.Settings(url="https://k", username="u",
                                                     password="p", space="default", index="logs-*")):
            rc = cli.main(["--index", "logs-*", "--count", "--group-by",
                           "level,status,url"])
        self.assertEqual(rc, 2)

    def test_help_json_lists_count_and_group_by(self):
        flags = [f["flag"] for f in cli.help_json()["flags"]]
        self.assertIn("--count", flags)
        self.assertIn("--group-by", flags)


class TestExportBackendBranch(unittest.TestCase):
    def test_search_backend_calls_run_export(self):
        with mock.patch("logalizer.cli.build_settings",
                        return_value=config.Settings(url="https://k", username="u", password="p",
                                                     space="default", index="logs-*", export_backend="search")), \
             mock.patch("logalizer.cli.Client"), \
             mock.patch("logalizer.cli.search.run_export", return_value="a,b\n1,2\n") as re, \
             mock.patch("logalizer.cli.reporting.submit") as rs, \
             mock.patch("sys.stdout.write"):
            rc = cli.main(["--index", "logs-*", "--fields", "a,b"])
        self.assertEqual(rc, 0)
        re.assert_called_once()
        rs.assert_not_called()   # reporting path NOT used

    def test_reporting_backend_still_default(self):
        with mock.patch("logalizer.cli.build_settings",
                        return_value=config.Settings(url="https://k", username="u", password="p",
                                                     space="default", index="logs-*")), \
             mock.patch("logalizer.cli.Client"), \
             mock.patch("logalizer.cli.indexpatterns.resolve_index_pattern", return_value="idx"), \
             mock.patch("logalizer.cli.reporting.submit", return_value="j1"), \
             mock.patch("logalizer.cli.reporting.poll"), \
             mock.patch("logalizer.cli.reporting.download", return_value="a,b\n1,2\n"), \
             mock.patch("logalizer.cli.search.run_export") as re, \
             mock.patch("sys.stdout.write"):
            rc = cli.main(["--index", "logs-*", "--fields", "a,b"])
        self.assertEqual(rc, 0)
        re.assert_not_called()   # search NOT used when export_backend is default

    def test_export_backend_flag_passed_to_build_settings(self):
        with mock.patch("logalizer.cli.build_settings",
                        return_value=config.Settings(url="https://k", username="u", password="p",
                                                     space="default", index="logs-*",
                                                     export_backend="search")) as bs, \
             mock.patch("logalizer.cli.load_config", return_value={}), \
             mock.patch("logalizer.cli.Client"), \
             mock.patch("logalizer.cli.search.run_export", return_value="a,b\n1,2\n"), \
             mock.patch("sys.stdout.write"):
            rc = cli.main(["--index", "logs-*", "--export-backend", "search"])
        self.assertEqual(rc, 0)
        self.assertEqual(bs.call_args.kwargs.get("export_backend"), "search")

    def test_export_backend_flag_in_help_json(self):
        flags = [f["flag"] for f in cli.help_json()["flags"]]
        self.assertIn("--export-backend", flags)


class TestBareCall(unittest.TestCase):
    def test_bare_call_prints_help_and_exits_zero(self):
        buf = io.StringIO()
        with redirect_stdout(buf), \
             mock.patch("logalizer.cli.load_config", return_value={}):
            rc = cli.main([])
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn("usage:", out.lower())
        self.assertIn("logalizer", out)

    def test_explicit_index_still_exports(self):
        with mock.patch("logalizer.cli.build_settings",
                        return_value=config.Settings(url="https://k", username="u",
                                                     password="p", space="default", index="logs-*")), \
             mock.patch("logalizer.cli.Client"), \
             mock.patch("logalizer.cli.indexpatterns.resolve_index_pattern", return_value="idx"), \
             mock.patch("logalizer.cli.reporting.submit", return_value="j1"), \
             mock.patch("logalizer.cli.reporting.poll"), \
             mock.patch("logalizer.cli.reporting.download", return_value="a,b\n1,2\n"), \
             mock.patch("sys.stdout.write") as w:
            rc = cli.main(["--index", "logs-*"])
        self.assertEqual(rc, 0)
        self.assertIn("1,2", w.call_args[0][0])


class TestExportIntentWithoutIndex(unittest.TestCase):
    def test_truly_bare_still_prints_help(self):
        buf = io.StringIO()
        with redirect_stdout(buf), \
             mock.patch("logalizer.cli.load_config", return_value={}):
            rc = cli.main([])
        self.assertEqual(rc, 0)
        self.assertIn("usage:", buf.getvalue().lower())


class TestConfigDefaultIndexSatisfiesExport(unittest.TestCase):
    def test_query_uses_config_index(self):
        # Regression: a config-provided index satisfies export with no --index flag.
        with mock.patch("logalizer.cli.build_settings",
                        return_value=config.Settings(url="https://k", username="u", password="p",
                                                     space="default", index="logs-*")), \
             mock.patch("logalizer.cli.Client"), \
             mock.patch("logalizer.cli.indexpatterns.resolve_index_pattern", return_value="idx"), \
             mock.patch("logalizer.cli.reporting.submit", return_value="j1"), \
             mock.patch("logalizer.cli.reporting.poll"), \
             mock.patch("logalizer.cli.reporting.download", return_value="a,b\n1,2\n"), \
             mock.patch("sys.stdout.write") as w:
            rc = cli.main(["--query", "level:error", "--fields", "a,b"])
        self.assertEqual(rc, 0)
        self.assertIn("1,2", w.call_args[0][0])

    def test_no_index_no_config_still_errors(self):
        # No --index flag and no config index → export intent still exits 2, not help.
        with mock.patch("logalizer.cli.build_settings",
                        return_value=config.Settings(url="https://k", username="u", password="p",
                                                     space="default")), \
             mock.patch("logalizer.cli.Client"):
            rc = cli.main(["--query", "level:error"])
        self.assertEqual(rc, 2)


class TestInitProfileOrdering(unittest.TestCase):
    def test_init_with_profile_bypasses_build_settings(self):
        # build_settings must NOT be called when --init is present,
        # otherwise --init --profile NEWPROFILE would raise "unknown profile".
        with mock.patch("logalizer.cli.load_config", return_value={}), \
             mock.patch("logalizer.cli.init.run_init", return_value=0) as ri, \
             mock.patch("logalizer.cli.build_settings") as bs:
            rc = cli.main(["--init", "--profile", "brandnew",
                           "--url", "https://k", "--username", "u", "--password", "p"])
        self.assertEqual(rc, 0)
        ri.assert_called_once()
        bs.assert_not_called()


class TestProfiles(unittest.TestCase):
    def test_list_profiles_flag(self):
        with mock.patch("logalizer.cli.load_config", return_value={"profile.prod": {}, "profile.staging": {}}), \
             mock.patch("sys.stdout.write") as w:
            rc = cli.main(["--list-profiles"])
        self.assertEqual(rc, 0)
        written = "".join(c.args[0] for c in w.call_args_list if c.args)
        self.assertIn("prod", written)
        self.assertIn("staging", written)

    def test_profile_passed_to_build_settings(self):
        with mock.patch("logalizer.cli.build_settings",
                        return_value=config.Settings(url="https://k", username="u",
                                                     password="p", space="default", index="logs-*")) as bs, \
             mock.patch("logalizer.cli.load_config", return_value={}), \
             mock.patch("logalizer.cli.Client"), \
             mock.patch("logalizer.cli.indexpatterns.resolve_index_pattern", return_value="idx"), \
             mock.patch("logalizer.cli.reporting.submit", return_value="j1"), \
             mock.patch("logalizer.cli.reporting.poll"), \
             mock.patch("logalizer.cli.reporting.download", return_value="a,b\n1,2\n"), \
             mock.patch("sys.stdout.write"):
            rc = cli.main(["--index", "logs-*", "--profile", "prod"])
        self.assertEqual(rc, 0)
        self.assertEqual(bs.call_args.kwargs.get("profile"), "prod")

    def test_help_json_lists_profile_flags(self):
        flags = [f["flag"] for f in cli.help_json()["flags"]]
        self.assertIn("--profile", flags)
        self.assertIn("--list-profiles", flags)


if __name__ == "__main__":
    unittest.main()
