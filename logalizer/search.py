"""Server-side count aggregation via Kibana's internal search endpoint."""
import json
import re

from logalizer.client import ClientError, raise_for_status

_ENDPOINT = "/internal/search/es"
_DEFAULT_SIZE = 10000
_MISSING = "<none>"
_TEXT_FIELD_ERROR = "Text fields are not optimised"
_OFFENDING_FIELD_RE = re.compile(r"set fielddata=true on \[([^\]]+)\]")


def _offending_fields(text):
    """Return offending text-field names found in a response body, deduped in order."""
    return list(dict.fromkeys(_OFFENDING_FIELD_RE.findall(text)))


def _has_text_field_failure(text):
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return False
    failures = data.get("rawResponse", {}).get("_shards", {}).get("failures", [])
    for failure in failures:
        reason = failure.get("reason")
        if isinstance(reason, dict):
            reason = reason.get("reason", "")
        if isinstance(reason, str) and _TEXT_FIELD_ERROR in reason:
            return True
    return False


def _build_body(query, time_filter, fields, limit):
    """Assemble the ES search body (size 0 + terms aggs) for the given inputs."""
    size = limit if limit is not None else _DEFAULT_SIZE
    body: dict[str, object] = {"size": 0, "track_total_hits": True}

    clauses = []
    if time_filter is not None:
        clauses.append(time_filter["query"])
    if query:
        clauses.append({"query_string": {"query": query}})
    if clauses:
        body["query"] = {"bool": {"filter": clauses}}

    outer = {"terms": {"field": fields[0], "size": size, "missing": _MISSING}}
    if len(fields) > 1:
        outer["aggs"] = {
            "g1": {"terms": {"field": fields[1], "size": size, "missing": _MISSING}}
        }
    body["aggs"] = {"g0": outer}
    return body


def _map_buckets(buckets, depth):
    groups = []
    for bucket in buckets:
        node = {"key": bucket["key"], "count": bucket["doc_count"]}
        if depth > 1:
            sub = bucket.get("g1", {})
            node["subgroups"] = [
                {"key": s["key"], "count": s["doc_count"]}
                for s in sub.get("buckets", [])
            ]
        groups.append(node)
    return groups


def _map_result(raw_response, depth):
    aggs = raw_response.get("aggregations", {})
    top = aggs.get("g0", {})
    buckets = top.get("buckets", [])
    sum_other = top.get("sum_other_doc_count", 0)

    return {
        "groups": _map_buckets(buckets, depth),
        "total": raw_response.get("hits", {}).get("total", 0),
        "distinct": len(buckets) + (1 if sum_other > 0 else 0),
        "truncated": sum_other > 0,
    }


def run_count(client, index, query, time_filter, fields, limit):
    """Return {"groups": [...], "total": n, "distinct": n, "truncated": bool}.

    fields: list of 1 or 2 field names. query: KQL string ("" = match all).
    time_filter: the dict from cli.build_time_filter, or None.
    limit: max top-level groups (None = default size).
    """
    depth = len(fields)
    current_fields = list(fields)
    status, text = client.request(
        "POST", _ENDPOINT,
        {"params": {"index": index,
                    "body": _build_body(query, time_filter, current_fields, limit)}},
    )

    while (status == 400 and _TEXT_FIELD_ERROR in text) or _has_text_field_failure(text):
        offending = _offending_fields(text)
        new_fields = [
            f + ".keyword" if f in offending and not f.endswith(".keyword") else f
            for f in current_fields
        ]
        if new_fields == current_fields:
            break
        current_fields = new_fields
        status, text = client.request(
            "POST", _ENDPOINT,
            {"params": {"index": index,
                        "body": _build_body(query, time_filter, current_fields, limit)}},
        )

    raise_for_status(status, text, "count search")
    raw_response = json.loads(text)["rawResponse"]
    if raw_response.get("_shards", {}).get("total", 0) == 0:
        raise ClientError(f"index pattern {index!r} matched no indices", 2)
    return _map_result(raw_response, depth)
