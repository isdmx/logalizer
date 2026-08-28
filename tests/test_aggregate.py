import json
import unittest

from logalizer import aggregate


RESULT = {
    "groups": [
        {"key": "info", "count": 2, "subgroups": [{"key": "200", "count": 2}]},
        {"key": "error", "count": 2, "subgroups": [
            {"key": "500", "count": 1},
            {"key": "502", "count": 1},
        ]},
    ],
    "total": 6,
    "distinct": 3,
    "truncated": True,
}


class TestRender(unittest.TestCase):
    def _r(self):
        return RESULT

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
