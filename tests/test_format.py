import json
import unittest

from logalizer import format as fmt


CSV = 'a,b\n1,2\n3,4\n5,6\n'


class TestParseCsv(unittest.TestCase):
    def test_parses_header_and_rows(self):
        header, rows = fmt.parse_csv(CSV)
        self.assertEqual(header, ["a", "b"])
        self.assertEqual(rows, [["1", "2"], ["3", "4"], ["5", "6"]])

    def test_quoted_embedded_newline(self):
        text = 'a,b\n"hello\nworld",2\n'
        header, rows = fmt.parse_csv(text)
        self.assertEqual(rows, [["hello\nworld", "2"]])

    def test_empty_input(self):
        header, rows = fmt.parse_csv("")
        self.assertEqual(header, [])
        self.assertEqual(rows, [])


class TestToCsv(unittest.TestCase):
    def test_passthrough_without_limit(self):
        self.assertEqual(fmt.to_csv(CSV, None), CSV)

    def test_truncates_with_limit(self):
        out = fmt.to_csv(CSV, 1)
        header, rows = fmt.parse_csv(out)
        self.assertEqual(rows, [["1", "2"]])


class TestToJson(unittest.TestCase):
    def test_wrapper_shape(self):
        out = fmt.to_json(CSV, None)
        obj = json.loads(out)
        self.assertEqual(set(obj.keys()), {"rows", "count", "truncated"})
        self.assertEqual(obj["rows"], [{"a": "1", "b": "2"}, {"a": "3", "b": "4"}, {"a": "5", "b": "6"}])
        self.assertEqual(obj["count"], 3)
        self.assertFalse(obj["truncated"])

    def test_truncation_flag(self):
        obj = json.loads(fmt.to_json(CSV, 2))
        self.assertEqual(obj["count"], 2)
        self.assertTrue(obj["truncated"])

    def test_no_truncation_when_limit_exceeds(self):
        obj = json.loads(fmt.to_json(CSV, 99))
        self.assertFalse(obj["truncated"])


class TestToJsonl(unittest.TestCase):
    def test_one_object_per_line(self):
        lines = fmt.to_jsonl(CSV, None).strip().split("\n")
        self.assertEqual(len(lines), 3)
        self.assertEqual(json.loads(lines[0]), {"a": "1", "b": "2"})

    def test_truncates(self):
        lines = fmt.to_jsonl(CSV, 1).strip().split("\n")
        self.assertEqual(len(lines), 1)


class TestToMarkdown(unittest.TestCase):
    def test_table(self):
        out = fmt.to_markdown(CSV, None)
        self.assertIn("| a | b |", out)
        self.assertIn("| 1 | 2 |", out)

    def test_escapes_pipe_and_newline(self):
        text = 'a,b\n"x|y","line\nbreak"\n'
        out = fmt.to_markdown(text, None)
        self.assertIn("x\\|y", out)
        self.assertNotIn("\nbreak", out)

    def test_truncation_note(self):
        out = fmt.to_markdown(CSV, 1)
        self.assertIn("truncated", out)


if __name__ == "__main__":
    unittest.main()
