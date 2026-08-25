"""Discovery helpers: spaces, index patterns, and pattern→data-view-ID resolution."""
import json

from logalizer.client import raise_for_status


def list_spaces(client):
    status, body = client.request("GET", "/api/spaces/space")
    raise_for_status(status, body, "list spaces")
    return [s["id"] for s in json.loads(body)]


def list_index_patterns(client, space):
    path = f"/s/{space}/api/saved_objects/_find?type=index-pattern&per_page=100"
    status, body = client.request("GET", path)
    raise_for_status(status, body, "list index patterns")
    data = json.loads(body)
    return [so["attributes"]["title"] for so in data.get("saved_objects", [])]


def resolve_index_pattern(client, space, pattern):
    """Return the data-view ID for a pattern title, or None."""
    path = f"/s/{space}/api/saved_objects/_find?type=index-pattern&per_page=100"
    status, body = client.request("GET", path)
    raise_for_status(status, body, "resolve index pattern")
    for so in json.loads(body).get("saved_objects", []):
        if so["attributes"].get("title") == pattern:
            return so["id"]
    return None


def list_fields(client, space, pattern):
    """Best-effort field listing. Tries _fields_for_wildcard, then falls back
    to the index-pattern's fieldAttrs. May return [] for read-only roles."""
    path = (f"/s/{space}/api/index_patterns/_fields_for_wildcard"
            f"?pattern={pattern}&meta_fields=_source")
    status, body = client.request("GET", path)
    if status == 200:
        try:
            fields = json.loads(body).get("fields", [])
            if fields:
                return [f["name"] for f in fields]
        except (ValueError, KeyError):
            pass

    # fallback: index-pattern saved object fieldAttrs
    path = f"/s/{space}/api/saved_objects/_find?type=index-pattern&per_page=100"
    status, body = client.request("GET", path)
    raise_for_status(status, body, "list fields")
    for so in json.loads(body).get("saved_objects", []):
        if so["attributes"].get("title") == pattern:
            raw = so["attributes"].get("fieldAttrs", "{}")
            try:
                return sorted(json.loads(raw).keys())
            except (ValueError, TypeError):
                return []
    return []
