import json
import unittest
from unittest import mock

from logalizer import search


def _raw(total=0, buckets=None, sum_other=0):
    if buckets is None:
        buckets = []
    return json.dumps({
        "rawResponse": {
            "hits": {"total": total},
            "aggregations": {
                "g0": {"buckets": buckets, "sum_other_doc_count": sum_other},
            },
        },
    })


def _client(responses):
    c = mock.Mock()
    c.request.side_effect = responses
    return c


def _captured_body(client, call_index=0):
    args = client.request.call_args_list[call_index][0]
    return args[2]["params"]["body"]


TIME_FILTER = {
    "meta": {"field": "@timestamp", "params": {}},
    "query": {"range": {"@timestamp": {
        "format": "strict_date_optional_time",
        "gte": "2026-08-25T00:00:00.000Z",
        "lte": "2026-08-25T23:59:59.000Z",
    }}},
}


class TestBuildBody(unittest.TestCase):
    def test_single_key_agg_structure(self):
        client = _client([(200, _raw())])
        search.run_count(client, "idx", "", None, ["level"], None)

        method, path, payload = client.request.call_args[0]
        self.assertEqual(method, "POST")
        self.assertEqual(path, "/internal/search/es")
        self.assertEqual(payload["params"]["index"], "idx")

        body = payload["params"]["body"]
        self.assertEqual(body["size"], 0)
        self.assertTrue(body["track_total_hits"])
        self.assertNotIn("query", body)

        terms = body["aggs"]["g0"]["terms"]
        self.assertEqual(terms["field"], "level")
        self.assertEqual(terms["missing"], "<none>")
        self.assertEqual(terms["size"], 10000)

    def test_two_key_nested_structure(self):
        client = _client([(200, _raw())])
        search.run_count(client, "idx", "", None, ["level", "status"], None)

        body = _captured_body(client)
        outer = body["aggs"]["g0"]
        self.assertEqual(outer["terms"]["field"], "level")
        inner = outer["aggs"]["g1"]["terms"]
        self.assertEqual(inner["field"], "status")
        self.assertEqual(inner["missing"], "<none>")

    def test_limit_sets_size(self):
        client = _client([(200, _raw())])
        search.run_count(client, "idx", "", None, ["level"], 25)
        body = _captured_body(client)
        self.assertEqual(body["aggs"]["g0"]["terms"]["size"], 25)


class TestMapResult(unittest.TestCase):
    def test_maps_buckets_to_groups(self):
        buckets = [{"key": "a", "doc_count": 60}, {"key": "b", "doc_count": 40}]
        client = _client([(200, _raw(total=100, buckets=buckets, sum_other=0))])
        result = search.run_count(client, "idx", "", None, ["level"], None)

        self.assertEqual(result["total"], 100)
        self.assertEqual(result["groups"], [
            {"key": "a", "count": 60},
            {"key": "b", "count": 40},
        ])
        self.assertEqual(result["distinct"], 2)
        self.assertFalse(result["truncated"])

    def test_truncation_from_sum_other_doc_count(self):
        buckets = [{"key": "a", "doc_count": 60}, {"key": "b", "doc_count": 40}]
        client = _client([(200, _raw(total=105, buckets=buckets, sum_other=5))])
        result = search.run_count(client, "idx", "", None, ["level"], None)

        self.assertTrue(result["truncated"])
        self.assertEqual(result["distinct"], 3)  # 2 buckets + 1 for sum_other

    def test_two_key_groups_nest_subgroups(self):
        raw = {
            "rawResponse": {
                "hits": {"total": 4},
                "aggregations": {
                    "g0": {
                        "buckets": [
                            {
                                "key": "info",
                                "doc_count": 2,
                                "g1": {"buckets": [{"key": "200", "doc_count": 2}]},
                            },
                            {
                                "key": "error",
                                "doc_count": 2,
                                "g1": {"buckets": [
                                    {"key": "500", "doc_count": 1},
                                    {"key": "502", "doc_count": 1},
                                ]},
                            },
                        ],
                        "sum_other_doc_count": 0,
                    }
                },
            }
        }
        client = _client([(200, json.dumps(raw))])
        result = search.run_count(client, "idx", "", None, ["level", "status"], None)

        info = result["groups"][0]
        self.assertEqual(info, {
            "key": "info",
            "count": 2,
            "subgroups": [{"key": "200", "count": 2}],
        })


class TestKeywordRetry(unittest.TestCase):
    def test_retries_keyword_on_text_error(self):
        err = (400, "Text fields are not optimised for operations that "
                    "require per-document field data")
        client = _client([err, (200, _raw())])
        result = search.run_count(client, "idx", "", None, ["level"], None)

        self.assertEqual(client.request.call_count, 2)
        second_body = _captured_body(client, call_index=1)
        self.assertEqual(second_body["aggs"]["g0"]["terms"]["field"], "level.keyword")
        self.assertEqual(result["total"], 0)


class TestQueryClauses(unittest.TestCase):
    def test_query_string_and_time_filter(self):
        client = _client([(200, _raw())])
        search.run_count(client, "idx", "level:error", TIME_FILTER, ["level"], None)

        body = _captured_body(client)
        filt = body["query"]["bool"]["filter"]

        ranges = [c for c in filt if "range" in c]
        qstrings = [c for c in filt if "query_string" in c]
        self.assertEqual(len(ranges), 1)
        self.assertEqual(len(qstrings), 1)
        self.assertEqual(qstrings[0]["query_string"]["query"], "level:error")
        self.assertEqual(ranges[0]["range"]["@timestamp"]["gte"],
                         "2026-08-25T00:00:00.000Z")

    def test_empty_query_no_time_filter_omits_query(self):
        client = _client([(200, _raw())])
        search.run_count(client, "idx", "", None, ["level"], None)
        body = _captured_body(client)
        self.assertNotIn("query", body)

    def test_query_only_wraps_in_bool_filter(self):
        client = _client([(200, _raw())])
        search.run_count(client, "idx", "status:500", None, ["level"], None)
        body = _captured_body(client)
        filt = body["query"]["bool"]["filter"]
        self.assertEqual(len(filt), 1)
        self.assertIn("query_string", filt[0])


if __name__ == "__main__":
    unittest.main()
