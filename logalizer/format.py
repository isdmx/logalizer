"""Output formatting: parse CSV export and render as csv/json/jsonl/markdown."""
import csv
import io
import json


def parse_csv(text):
    """Return (header, rows) from CSV text. Empty input -> ([], [])."""
    reader = csv.reader(io.StringIO(text))
    all_rows = list(reader)
    if not all_rows:
        return [], []
    return all_rows[0], all_rows[1:]


def _truncate(rows, limit):
    if limit is None or len(rows) <= limit:
        return rows, False
    return rows[:limit], True


def to_csv(text, limit):
    """CSV passthrough; when limit is set, truncate data rows (keep header)."""
    if limit is None:
        return text
    header, rows = parse_csv(text)
    rows, _ = _truncate(rows, limit)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    writer.writerows(rows)
    return buf.getvalue()


def to_json(text, limit):
    header, rows = parse_csv(text)
    rows, truncated = _truncate(rows, limit)
    objs = [dict(zip(header, row)) for row in rows]
    return json.dumps(
        {"rows": objs, "count": len(objs), "truncated": truncated},
        ensure_ascii=False, indent=2,
    )


def to_jsonl(text, limit):
    header, rows = parse_csv(text)
    rows, _ = _truncate(rows, limit)
    lines = [json.dumps(dict(zip(header, row)), ensure_ascii=False) for row in rows]
    return "\n".join(lines) + ("\n" if lines else "")


def to_markdown(text, limit):
    header, rows = parse_csv(text)
    rows, truncated = _truncate(rows, limit)

    def cell(v):
        return v.replace("|", "\\|").replace("\r", " ").replace("\n", " ")

    lines = ["| " + " | ".join(cell(h) for h in header) + " |",
             "| " + " | ".join("---" for _ in header) + " |"]
    for row in rows:
        padded = list(row) + [""] * (len(header) - len(row))
        lines.append("| " + " | ".join(cell(c) for c in padded[:len(header)]) + " |")
    out = "\n".join(lines)
    if truncated:
        out += f"\n\n> truncated at {limit} rows"
    return out


RENDERERS = {
    "csv": to_csv,
    "json": to_json,
    "jsonl": to_jsonl,
    "markdown": to_markdown,
}


def render(fmt, text, limit):
    """Render CSV export text in the given format, honoring limit."""
    if fmt not in RENDERERS:
        raise ValueError(f"unknown format: {fmt!r}")
    return RENDERERS[fmt](text, limit)
