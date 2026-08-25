import unittest

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


if __name__ == "__main__":
    unittest.main()
