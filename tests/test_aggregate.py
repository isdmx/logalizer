import json
import unittest

from logalizer import aggregate


HEADER = ["level", "status"]
ROWS = [
    ["info", "200"], ["info", "200"], ["error", "500"],
    ["error", "502"], ["-", "200"], ["", "200"],
]


class TestCountBy(unittest.TestCase):
    def test_single_key(self):
        r = aggregate.count_by(HEADER, ROWS, ["level"])
        self.assertEqual(r["total"], 6)
        self.assertEqual(r["distinct"], 3)
        self.assertFalse(r["truncated"])
        self.assertEqual(r["groups"][0], {"key": "info", "count": 2})
        none_group = [g for g in r["groups"] if g["key"] == "<none>"][0]
        self.assertEqual(none_group["count"], 2)

    def test_two_keys_nested(self):
        r = aggregate.count_by(HEADER, ROWS, ["level", "status"])
        info = [g for g in r["groups"] if g["key"] == "info"][0]
        self.assertEqual(info["count"], 2)
        self.assertEqual(info["subgroups"], [{"key": "200", "count": 2}])
        error = [g for g in r["groups"] if g["key"] == "error"][0]
        self.assertEqual(error["count"], 2)
        self.assertEqual(len(error["subgroups"]), 2)

    def test_sort_by_count_then_key(self):
        r = aggregate.count_by(HEADER, [["a", "1"], ["b", "1"], ["b", "1"]], ["level"])
        self.assertEqual([g["key"] for g in r["groups"]], ["b", "a"])

    def test_limit_truncates(self):
        r = aggregate.count_by(HEADER, ROWS, ["level"], limit=1)
        self.assertTrue(r["truncated"])
        self.assertEqual(len(r["groups"]), 1)

    def test_unknown_field_raises(self):
        with self.assertRaises(ValueError):
            aggregate.count_by(HEADER, ROWS, ["nope"])

    def test_more_than_two_fields_raises(self):
        with self.assertRaises(ValueError):
            aggregate.count_by(["a", "b", "c"], [["1", "2", "3"]], ["a", "b", "c"])


class TestRender(unittest.TestCase):
    def _r(self):
        return aggregate.count_by(HEADER, ROWS, ["level", "status"], limit=2)

    def test_json_wrapper(self):
        obj = json.loads(aggregate.render("json", self._r(), ["level", "status"]))
        self.assertEqual(set(obj.keys()), {"groups", "total", "distinct", "truncated"})
        self.assertIn("subgroups", obj["groups"][0])

    def test_csv_flat(self):
        out = aggregate.render("csv", self._r(), ["level", "status"])
        self.assertEqual(out.strip().split("\n")[0], "level,status,count")

    def test_jsonl_one_line_per_group(self):
        out = aggregate.render("jsonl", self._r(), ["level", "status"])
        self.assertEqual(len(out.strip().split("\n")), 2)

    def test_markdown_pivot(self):
        out = aggregate.render("markdown", self._r(), ["level", "status"])
        self.assertIn("| level |", out)
        self.assertIn("| --- |", out)
        self.assertIn("info", out)
        self.assertIn("error", out)


if __name__ == "__main__":
    unittest.main()
