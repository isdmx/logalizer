"""Aggregation rendering: format count results as json/jsonl/csv/markdown."""
import csv
import io
import json
from collections import defaultdict


def _cell(v):
    return v.replace("|", "\\|").replace("\r", " ").replace("\n", " ")


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
