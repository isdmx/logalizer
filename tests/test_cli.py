import unittest

from logalizer import cli


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


if __name__ == "__main__":
    unittest.main()
