import unittest
from logalizer import rison


class TestRisonEncode(unittest.TestCase):
    def test_scalars(self):
        self.assertEqual(rison.encode("hello"), "'hello'")
        self.assertEqual(rison.encode(""), "''")
        self.assertEqual(rison.encode(None), "!n")
        self.assertEqual(rison.encode(True), "!t")
        self.assertEqual(rison.encode(False), "!f")
        self.assertEqual(rison.encode(42), "42")
        self.assertEqual(rison.encode(3.14), "3.14")

    def test_string_escaping(self):
        # ' must become !', ! must become !!
        self.assertEqual(rison.encode("a'b"), "'a!'b'")
        self.assertEqual(rison.encode("a!b"), "'a!!b'")

    def test_array(self):
        self.assertEqual(rison.encode([1, 2, 3]), "!(1,2,3)")
        self.assertEqual(rison.encode([]), "!()")

    def test_object(self):
        self.assertEqual(rison.encode({"a": 1, "b": "x"}), "(a:1,b:'x')")
        self.assertEqual(rison.encode({}), "()")

    def test_non_identifier_key_is_quoted(self):
        self.assertEqual(rison.encode({"@timestamp": "t"}), "('@timestamp':'t')")

    def test_nested(self):
        v = {"q": {"r": [1, "x"]}, "k": None}
        self.assertEqual(rison.encode(v), "(q:(r:!(1,'x')),k:!n)")

    def test_real_jobparams_shape(self):
        # This exact structure is what we send to Kibana (verified live).
        jp = {
            "title": "t",
            "objectType": "search",
            "browserTimezone": "UTC",
            "version": "7.17.29",
            "searchSource": {
                "index": "abc980e0",
                "query": {"query": "", "language": "kuery"},
                "filter": [{
                    "meta": {"field": "@timestamp", "params": {}},
                    "query": {"range": {"@timestamp": {
                        "format": "strict_date_optional_time",
                        "gte": "2026-08-25T10:00:00.000Z",
                        "lte": "2026-08-25T14:00:00.000Z"}}}
                }],
            },
            "columns": ["@timestamp", "msg"],
        }
        out = rison.encode(jp)
        self.assertIn("'@timestamp':(format:'strict_date_optional_time'", out)
        self.assertIn("columns:!('@timestamp','msg')", out)
        self.assertIn("params:()", out)


if __name__ == "__main__":
    unittest.main()
