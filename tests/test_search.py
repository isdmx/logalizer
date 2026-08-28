import json
import unittest
from unittest import mock

from logalizer import search
from logalizer.client import ClientError


def _raw(total=0, buckets=None, sum_other=0):
    if buckets is None:
        buckets = []
    return json.dumps({
        "rawResponse": {
            "hits": {"total": total},
            "_shards": {"total": 1, "successful": 1, "failed": 0},
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
                "_shards": {"total": 1, "successful": 1, "failed": 0},
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
                    "require per-document field data. set fielddata=true on [level]")
        client = _client([err, (200, _raw())])
        result = search.run_count(client, "idx", "", None, ["level"], None)

        self.assertEqual(client.request.call_count, 2)
        second_body = _captured_body(client, call_index=1)
        self.assertEqual(second_body["aggs"]["g0"]["terms"]["field"], "level.keyword")
        self.assertEqual(result["total"], 0)

    def test_retry_only_suffixes_offending_field(self):
        err = (400, "Text fields are not optimised for operations that "
                    "require per-document field data. set fielddata=true on [level]")
        client = _client([err, (200, _raw())])
        search.run_count(client, "idx", "", None, ["level", "status"], None)

        self.assertEqual(client.request.call_count, 2)
        second_body = _captured_body(client, call_index=1)
        self.assertEqual(second_body["aggs"]["g0"]["terms"]["field"], "level.keyword")
        self.assertEqual(
            second_body["aggs"]["g0"]["aggs"]["g1"]["terms"]["field"], "status")

    def test_retry_suffixes_nested_offending_field(self):
        # Nested aggs: the first 400 names only the OUTER offending field;
        # the inner field's problem is revealed only after the outer is fixed.
        err1 = (400, "Text fields are not optimised ... set fielddata=true on [level]")
        err2 = (400, "Text fields are not optimised ... set fielddata=true on [status]")
        client = _client([err1, err2, (200, _raw())])
        search.run_count(client, "idx", "", None, ["level", "status"], None)

        self.assertEqual(client.request.call_count, 3)
        third_body = _captured_body(client, call_index=2)
        self.assertEqual(third_body["aggs"]["g0"]["terms"]["field"], "level.keyword")
        self.assertEqual(
            third_body["aggs"]["g0"]["aggs"]["g1"]["terms"]["field"], "status.keyword")

    def test_keeps_existing_keyword_suffix(self):
        err = (400, "Text fields are not optimised ... set fielddata=true on [status]")
        client = _client([err, (200, _raw())])
        search.run_count(client, "idx", "", None, ["level.keyword", "status"], None)

        self.assertEqual(client.request.call_count, 2)
        second_body = _captured_body(client, call_index=1)
        self.assertEqual(second_body["aggs"]["g0"]["terms"]["field"], "level.keyword")
        self.assertEqual(
            second_body["aggs"]["g0"]["aggs"]["g1"]["terms"]["field"], "status.keyword")

    def test_retries_keyword_on_shard_failures(self):
        shard_failure = json.dumps({
            "rawResponse": {
                "hits": {"total": 0},
                "_shards": {
                    "total": 170,
                    "failed": 140,
                    "failures": [{
                        "reason": {
                            "reason": "Text fields are not optimised for operations "
                                      "that require per-document field data. "
                                      "set fielddata=true on [level]"
                        }
                    }]
                },
                "aggregations": {},
            }
        })
        buckets = [{"key": "debug", "doc_count": 100}]
        client = _client([
            (200, shard_failure),
            (200, _raw(total=100, buckets=buckets, sum_other=0)),
        ])
        result = search.run_count(client, "idx", "", None, ["level"], None)

        self.assertEqual(client.request.call_count, 2)
        second_body = _captured_body(client, call_index=1)
        self.assertEqual(second_body["aggs"]["g0"]["terms"]["field"], "level.keyword")
        self.assertEqual(result["total"], 100)
        self.assertEqual(result["groups"], [{"key": "debug", "count": 100}])


class TestOffendingFields(unittest.TestCase):
    def test_parses_offending_fields_deduped(self):
        text = ("Text fields are not optimised for operations that require "
                "per-document field data. set fielddata=true on [level] ... "
                "set fielddata=true on [status] ... set fielddata=true on [level]")
        self.assertEqual(search._offending_fields(text), ["level", "status"])

    def test_no_offending_fields_returns_empty(self):
        self.assertEqual(search._offending_fields("some other error"), [])

    def test_offending_fields_from_shard_failures(self):
        text = json.dumps({
            "rawResponse": {
                "_shards": {
                    "failures": [{
                        "reason": {
                            "reason": "Text fields are not optimised for operations "
                                      "that require per-document field data. "
                                      "set fielddata=true on [level]"
                        }
                    }]
                }
            }
        })
        self.assertEqual(search._offending_fields(text), ["level"])


class TestErrorHandling(unittest.TestCase):
    def test_auth_error_raises_client_error_3(self):
        client = _client([(401, '{"statusCode":401,"error":"Unauthorized"}')])
        with self.assertRaises(ClientError) as ctx:
            search.run_count(client, "idx", "", None, ["level"], None)
        self.assertEqual(ctx.exception.exit_code, 3)

    def test_server_error_raises_client_error_5(self):
        client = _client([(500, '{"statusCode":500,"error":"Internal Server Error"}')])
        with self.assertRaises(ClientError) as ctx:
            search.run_count(client, "idx", "", None, ["level"], None)
        self.assertEqual(ctx.exception.exit_code, 5)

    def test_no_matching_indices_raises_client_error(self):
        body = json.dumps({
            "rawResponse": {
                "hits": {"total": 0},
                "_shards": {"total": 0, "successful": 0, "failed": 0},
                "aggregations": {},
            }
        })
        client = _client([(200, body)])
        with self.assertRaises(ClientError) as ctx:
            search.run_count(client, "no-such-*", "", None, ["level"], None)
        self.assertEqual(ctx.exception.exit_code, 2)
        self.assertIn("matched no indices", str(ctx.exception))


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
