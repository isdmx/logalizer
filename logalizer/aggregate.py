"""Aggregation: group rows by one or two keys and count occurrences."""
import csv
import io
import json
from collections import defaultdict


def _norm(value):
    v = (value or "").strip()
    return "<none>" if v in ("", "-") else v


def _cell(v):
    return v.replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def count_by(header, rows, fields, limit=None):
    """Return {"groups": [...], "total": n, "distinct": n, "truncated": bool}.

    fields: list of 1 or 2 field names. limit: max top-level groups (None = all).
    Two-key groups are nested: each top-level node has a "subgroups" list.
    """
    if not fields:
        raise ValueError("no group-by fields")
    if len(fields) > 2:
        raise ValueError("count supports 1 or 2 group-by fields")

    indices = []
    for f in fields:
        if f not in header:
            raise ValueError(f"field {f!r} not in export columns {header}")
        indices.append(header.index(f))

    counts = {}
    for row in rows:
        keys = tuple(_norm(row[i] if i < len(row) else "") for i in indices)
        counts[keys] = counts.get(keys, 0) + 1

    total = sum(counts.values())
    distinct = len(counts)
    groups = _build_tree(counts, len(fields), limit)
    truncated = limit is not None and distinct > limit
    return {"groups": groups, "total": total, "distinct": distinct, "truncated": truncated}


def _build_tree(counts, depth, limit=None):
    grouped = defaultdict(int)
    sub = defaultdict(dict)
    for keys, cnt in counts.items():
        grouped[keys[0]] += cnt
        if depth > 1:
            sub[keys[0]][keys[1:]] = cnt

    ordered = sorted(grouped.items(), key=lambda kv: (kv[1], kv[0]), reverse=True)
    if limit is not None:
        ordered = ordered[:limit]

    result = []
    for key, cnt in ordered:
        node = {"key": key, "count": cnt}
        if depth > 1:
            node["subgroups"] = _build_tree(sub[key], depth - 1)
        result.append(node)
    return result


def _flatten_leaves(nodes, prefix=()):
    for n in nodes:
        if "subgroups" in n:
            yield from _flatten_leaves(n["subgroups"], prefix + (n["key"],))
        else:
            yield prefix + (n["key"],), n["count"]


def to_json(result, fields=None):
    return json.dumps(result, ensure_ascii=False, indent=2)


def to_jsonl(result, fields=None):
    lines = [json.dumps(g, ensure_ascii=False) for g in result["groups"]]
    return "\n".join(lines) + ("\n" if lines else "")


def to_csv(result, fields):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(fields + ["count"])
    for keys, cnt in _flatten_leaves(result["groups"]):
        w.writerow(list(keys) + [cnt])
    return buf.getvalue()


def to_markdown(result, fields):
    groups = result["groups"]
    if not groups:
        out = "| (no data) |"
    elif len(fields) == 1:
        lines = ["| key | count |", "| --- | --- |"]
        for g in groups:
            lines.append(f"| {_cell(g['key'])} | {g['count']} |")
        out = "\n".join(lines)
    else:
        col_totals = defaultdict(int)
        for g in groups:
            for sg in g["subgroups"]:
                col_totals[sg["key"]] += sg["count"]
        cols = [k for k, _ in sorted(col_totals.items(), key=lambda kv: (-kv[1], kv[0]))]

        header_cells = [fields[0]] + cols
        lines = ["| " + " | ".join(_cell(c) for c in header_cells) + " |",
                 "| " + " | ".join(["---"] * len(header_cells)) + " |"]
        for g in groups:
            cell_counts = {sg["key"]: sg["count"] for sg in g["subgroups"]}
            row_cells = [_cell(g["key"])]
            for c in cols:
                cnt = cell_counts.get(c)
                row_cells.append(str(cnt) if cnt is not None else "")
            lines.append("| " + " | ".join(row_cells) + " |")
        out = "\n".join(lines)

    if result["truncated"]:
        out += f"\n\n> truncated (showing top groups; {result['distinct']} distinct total)"
    return out


_RENDERERS = {
    "json": to_json,
    "jsonl": to_jsonl,
    "csv": to_csv,
    "markdown": to_markdown,
}


def render(fmt, result, fields):
    if fmt not in _RENDERERS:
        raise ValueError(f"unknown format: {fmt!r}")
    return _RENDERERS[fmt](result, fields)
