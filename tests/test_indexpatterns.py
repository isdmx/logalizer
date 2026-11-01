import json
import unittest
from urllib.parse import parse_qs, urlsplit

from logalizer.client import ClientError

from logalizer.indexpatterns import (
    list_spaces,
    list_index_patterns,
    resolve_index_pattern,
    list_fields,
)


class _Fake:
    def __init__(self, responses):
        self._responses = responses
        self.calls = []

    def request(self, method, path, body=None):
        self.calls.append((method, path, body))
        return self._responses.pop(0)


def _page(objects, page, total, per_page=100):
    return 200, json.dumps({
        "saved_objects": objects, "page": page,
        "per_page": per_page, "total": total,
    })


def _patterns(count):
    return [
        {"id": f"id-{n}", "attributes": {"title": f"logs-{n}-*"}}
        for n in range(count)
    ]


class TestListSpaces(unittest.TestCase):
    def test_returns_ids(self):
        c = _Fake([(200, '[{"id": "default"}, {"id": "secondary"}]')])
        self.assertEqual(list_spaces(c), ["default", "secondary"])


class TestListIndexPatterns(unittest.TestCase):
    def test_returns_titles(self):
        body = ('{"saved_objects":['
                '{"attributes":{"title":"logs-*"}},'
                '{"attributes":{"title":"app-logs-*"}}]}')
        c = _Fake([(200, body)])
        result = list_index_patterns(c, "default")
        self.assertEqual(result, ["logs-*", "app-logs-*"])
        path = c.calls[0][1]
        self.assertIn("/s/default/api/saved_objects/_find", path)
        self.assertIn("type=index-pattern", path)

    def test_lists_all_pages(self):
        objects = _patterns(201)
        c = _Fake([_page(objects[:100], 1, 201),
                   _page(objects[100:200], 2, 201),
                   _page(objects[200:], 3, 201)])
        titles = list_index_patterns(c, "secondary")
        self.assertEqual(len(titles), 201)
        self.assertEqual(titles[100], "logs-100-*")
        self.assertEqual(titles[-1], "logs-200-*")
        self.assertEqual(len(set(titles)), 201)
        for page, (_, path, _) in enumerate(c.calls, 1):
            self.assertIn("/s/secondary/api/saved_objects/_find", path)
            self.assertEqual(parse_qs(urlsplit(path).query)["page"], [str(page)])

    def test_stops_at_total_on_full_page(self):
        c = _Fake([_page(_patterns(100), 1, 100)])
        self.assertEqual(len(list_index_patterns(c, "default")), 100)
        self.assertEqual(len(c.calls), 1)

    def test_uses_server_page_size(self):
        objects = _patterns(3)
        c = _Fake([_page(objects[:2], 1, 3, per_page=2),
                   _page(objects[2:], 2, 3, per_page=2)])
        self.assertEqual(list_index_patterns(c, "default"),
                         ["logs-0-*", "logs-1-*", "logs-2-*"])

    def test_full_page_without_total_continues_until_empty(self):
        c = _Fake([(200, json.dumps({"saved_objects": _patterns(100)})),
                   (200, '{"saved_objects":[]}')])
        self.assertEqual(len(list_index_patterns(c, "default")), 100)
        self.assertEqual(len(c.calls), 2)

    def test_empty_page_stops_even_if_total_is_stale(self):
        c = _Fake([_page([], 1, 101)])
        self.assertEqual(list_index_patterns(c, "default"), [])

    def test_second_page_error_does_not_return_partial_list(self):
        for status, exit_code in [(401, 3), (403, 3), (500, 5)]:
            with self.subTest(status=status):
                c = _Fake([_page(_patterns(100), 1, 101),
                           (status, '{"message":"failed"}')])
                with self.assertRaises(ClientError) as error:
                    list_index_patterns(c, "default")
                self.assertEqual(error.exception.exit_code, exit_code)


class TestResolveIndexPattern(unittest.TestCase):
    def test_resolves_id(self):
        body = ('{"saved_objects":['
                '{"id":"abc1","attributes":{"title":"logs-*"}},'
                '{"id":"abc2","attributes":{"title":"app-logs-*"}}]}')
        c = _Fake([(200, body)])
        self.assertEqual(resolve_index_pattern(c, "default", "app-logs-*"), "abc2")

    def test_unknown_pattern_returns_none(self):
        c = _Fake([(200, '{"saved_objects":[]}')])
        self.assertIsNone(resolve_index_pattern(c, "default", "nope*"))

    def test_resolves_title_on_second_page_to_distinct_id(self):
        objects = _patterns(101)
        c = _Fake([_page(objects[:100], 1, 101),
                   _page(objects[100:], 2, 101)])
        self.assertEqual(resolve_index_pattern(c, "default", "logs-100-*"),
                         "id-100")

    def test_missing_title_checks_all_pages(self):
        objects = _patterns(101)
        c = _Fake([_page(objects[:100], 1, 101),
                   _page(objects[100:], 2, 101)])
        self.assertIsNone(resolve_index_pattern(c, "default", "absent-*"))
        self.assertEqual(len(c.calls), 2)

    def test_second_page_error_is_not_reported_as_missing(self):
        c = _Fake([_page(_patterns(100), 1, 101), (403, '{}')])
        with self.assertRaises(ClientError) as error:
            resolve_index_pattern(c, "default", "absent-*")
        self.assertEqual(error.exception.exit_code, 3)


class TestListFields(unittest.TestCase):
    def test_uses_field_caps_when_present(self):
        c = _Fake([
            (200, '{"fields":[{"name":"@timestamp","type":"date"},{"name":"msg","type":"text"}]}'),
        ])
        result = list_fields(c, "default", "logs-*")
        self.assertEqual(result, ["@timestamp", "msg"])

    def test_falls_back_to_field_attrs(self):
        c = _Fake([
            (200, '{"fields":[]}'),
            (200, '{"saved_objects":[{"attributes":{"title":"logs-*",'
                  '"fieldAttrs":"{\\"level\\":{\\"count\\":1},\\"msg\\":{\\"count\\":1}}"}}]}'),
        ])
        result = list_fields(c, "default", "logs-*")
        self.assertEqual(result, ["level", "msg"])

    def test_fallback_finds_fields_on_second_page(self):
        objects = _patterns(101)
        objects[-1]["attributes"]["fieldAttrs"] = '{"message":{},"level":{}}'
        c = _Fake([(200, '{"fields":[]}'),
                   _page(objects[:100], 1, 101),
                   _page(objects[100:], 2, 101)])
        self.assertEqual(list_fields(c, "default", "logs-100-*"),
                         ["level", "message"])


if __name__ == "__main__":
    unittest.main()
