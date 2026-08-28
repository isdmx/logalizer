"""Command-line interface for logalizer."""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

from logalizer import reporting, indexpatterns, search
from logalizer import aggregate
from logalizer import format as fmt
from logalizer import init, ping
from logalizer.client import Client, ClientError
from logalizer.config import build_settings, config_file_path, load_config


class UsageError(Exception):
    pass


_DURATION_RE = re.compile(r"^(\d+)([smhd])$")
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def parse_duration(text):
    m = _DURATION_RE.match(text)
    if not m:
        raise ValueError(f"invalid duration: {text!r} (expected like 15m, 1h, 24h, 7d)")
    return timedelta(seconds=int(m.group(1)) * _UNIT_SECONDS[m.group(2)])


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def build_time_filter(from_iso, to_iso, last):
    if from_iso and to_iso:
        gte, lte = from_iso, to_iso
    elif from_iso or to_iso:
        raise UsageError("--from and --to must be used together")
    else:
        now = datetime.now(timezone.utc)
        delta = parse_duration(last or "24h")
        gte, lte = _iso(now - delta), _iso(now)
    return {
        "meta": {"field": "@timestamp", "params": {}},
        "query": {"range": {"@timestamp": {
            "format": "strict_date_optional_time",
            "gte": gte, "lte": lte}}},
    }


HELP_TEXT = """\
logalizer — export Kibana logs as CSV (Kibana 7.17 Reporting API)

USAGE
    logalizer [export] [OPTIONS]                 # export CSV (default action)
    logalizer --list-spaces                      # print available spaces
    logalizer --list-indices [--space SPACE]     # print index patterns
    logalizer --list-fields --index PATTERN      # print fields (best-effort)
    logalizer --help-json                        # machine-readable help
    logalizer --init                             # write config.ini (wizard)
    logalizer --init --url URL --username U --password P [--space S] [--index P] [--insecure]
    logalizer --ping                             # test config + connectivity

EXAMPLES (copy-paste ready)
    # Last 24h of errors from brain service, clean columns
    logalizer --index 'logs-*' --query 'level:error' --last 24h \\
        --fields '@timestamp,level,msg,logger' -o brain-errors.csv

    # Absolute time window, match a correlation id (your real query shape)
    logalizer -i 'app-logs-*' \\
        --query '"00000000-0000-0000-0000-000000000000"' \\
        --from 2026-08-25T10:00:00Z --to 2026-08-25T14:00:00Z

    # Everything from an index, all fields, streamed to stdout for piping
    logalizer -i 'agent-logs-*' --last 1h | grep 'status:500'

    # Discover what's available
    logalizer --list-spaces
    logalizer --list-indices --space default
    logalizer --list-fields --index 'logs-*'

QUERY OPTIONS
    -q, --query KQL        KQL query (default: "" = match all)
                           Examples: 'level:error'
                                     'status:500 AND url:*api*'
                                     'session_id:"01a03931-..."'
    -i, --index PATTERN    index pattern (REQUIRED for export), e.g. 'logs-*'
    -s, --space SPACE      Kibana space (default: from config, else default)
    --last DURATION        relative range: 30s, 15m, 1h, 24h, 7d
    --from ISO --to ISO    absolute range (ISO 8601). Overrides --last.
                           Use both, or neither.
    --fields LIST          comma-separated columns, in order.
                           Omit to export ALL fields (wide, includes internals).
    --count               count rows grouped by --group-by (instead of exporting)
    --group-by FIELDS     fields to group by, comma-separated (1 or 2). e.g. 'level'

OUTPUT OPTIONS
    -o, --out PATH         write CSV to file (default: stdout)
    --format FMT          output format: csv (default), json, jsonl, markdown
    --limit N             max rows to output (default: unlimited)
    --timeout SECONDS      max wait for the async job (default: 120)
    --insecure             skip TLS cert verification (self-signed servers)
    -v, --verbose          progress messages to stderr

DISCOVERY OPTIONS (exit 0; print to stdout, one per line)
    --list-spaces          list spaces
    --list-indices         list index patterns in --space
    --list-fields          list fields for --index (best-effort, may be partial)


CONFIGURATION & DIAGNOSTICS
    --init                write ~/.config/logalizer/config.ini (0600).
                          Interactive wizard when url/username/password omitted;
                          non-interactive when all three are given via flags.
    --ping                health check: config -> TLS -> auth -> space -> index.
                          Prints one line per check; exit 0 all good, else first
                          failure (2 config, 3 auth, 5 network).
    --url, --username, --password   used only by --init (never for export).

CREDENTIALS (never pass on command line)
    KIBANA_URL, KIBANA_USERNAME, KIBANA_PASSWORD   # env vars (recommended)
    or ~/.config/logalizer/config.ini              # 0600 perms

I/O CONTRACT
    stdout = CSV data (or discovery output). stderr = all logs/errors.
    Safe to run:  logalizer ... > out.csv   (diagnostics never pollute CSV)

EXIT CODES
    0  success
    2  usage error (bad flags / missing required)
    3  auth or permission failure (check KIBANA_USERNAME/PASSWORD, space)
    4  job failed or timed out (see stderr for Kibana's error)
    5  network / connection error

GOTCHAS
    - CSV export is capped by xpack.reporting.csv.maxSizeBytes (10 MB default).
      Very large exports will fail the job; narrow --query or --last.
    - Omitting --fields exports EVERY field (including _id, _index, _score,
      _type, @version, agent.*). Usually you want an explicit --fields list.
    - --list-fields may be incomplete for read-only roles; you can still pass
      any field name directly.
"""


def help_json():
    return {
        "name": "logalizer",
        "summary": "Export Kibana logs as CSV via the Kibana 7.17 Reporting API",
        "flags": [
            {"flag": "--query", "alias": "-q", "type": "string", "format": "KQL",
             "default": "\"\"", "example": "level:error"},
            {"flag": "--index", "alias": "-i", "type": "string", "format": "index-pattern",
             "required": True, "example": "logs-*"},
            {"flag": "--last", "type": "duration", "format": "30s|15m|1h|24h|7d",
             "default": "24h", "example": "1h"},
            {"flag": "--fields", "type": "csv-list", "default": "all fields",
             "example": "@timestamp,level,msg"},
            {"flag": "--out", "alias": "-o", "type": "path", "default": "stdout"},
            {"flag": "--format", "type": "string", "choices": ["csv", "json", "jsonl", "markdown"], "default": "csv"},
            {"flag": "--limit", "type": "int", "default": "unlimited"},
            {"flag": "--count", "type": "bool", "default": "false"},
            {"flag": "--group-by", "type": "string", "format": "field[,field]"},
            {"flag": "--space", "alias": "-s", "type": "string", "default": "default"},
            {"flag": "--init", "type": "bool", "default": "false"},
            {"flag": "--ping", "type": "bool", "default": "false"},
            {"flag": "--url", "type": "string", "used_by": "--init"},
            {"flag": "--username", "type": "string", "used_by": "--init"},
            {"flag": "--password", "type": "string", "used_by": "--init"},
        ],
        "exit_codes": {"0": "success", "2": "usage", "3": "auth/permission",
                       "4": "job failed/timeout", "5": "network"},
        "io_contract": {"stdout": "CSV data", "stderr": "diagnostics"},
        "env": ["KIBANA_URL", "KIBANA_USERNAME", "KIBANA_PASSWORD"],
    }


def build_parser():
    p = argparse.ArgumentParser(
        prog="logalizer",
        description="Export Kibana logs as CSV (Kibana 7.17 Reporting API)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=HELP_TEXT,
    )
    p.add_argument("-q", "--query", default="", help="KQL query (default: match all)")
    p.add_argument("-i", "--index", help="index pattern, e.g. 'logs-*'")
    p.add_argument("-s", "--space", help="Kibana space (default: from config, else default)")
    p.add_argument("--last", default="24h", help="relative range: 30s/15m/1h/24h/7d (default 24h)")
    p.add_argument("--from", dest="from_iso", help="absolute range start (ISO 8601)")
    p.add_argument("--to", dest="to_iso", help="absolute range end (ISO 8601)")
    p.add_argument("--fields", help="comma-separated columns (omit = all fields)")
    p.add_argument("--count", action="store_true", help="count rows grouped by --group-by")
    p.add_argument("--group-by", help="field(s) to group by (comma-separated, 1 or 2)")
    p.add_argument("--format", dest="fmt", choices=["csv", "json", "jsonl", "markdown"],
                   default="csv", help="output format (default: csv)")
    p.add_argument("--limit", type=int, default=None,
                   help="max rows to output (default: unlimited)")
    p.add_argument("-o", "--out", help="write CSV to file (default: stdout)")
    p.add_argument("--timeout", type=int, help="max job wait in seconds (default 120)")
    p.add_argument("--insecure", action="store_true", help="skip TLS verification")
    p.add_argument("-v", "--verbose", action="store_true", help="progress to stderr")
    p.add_argument("--list-spaces", action="store_true", help="list spaces")
    p.add_argument("--list-indices", action="store_true", help="list index patterns")
    p.add_argument("--list-fields", action="store_true", help="list fields for --index")
    p.add_argument("--help-json", action="store_true", help="machine-readable help")
    p.add_argument("--init", action="store_true", help="configure and write config.ini")
    p.add_argument("--ping", action="store_true", help="test config + connectivity")
    p.add_argument("--url", help="Kibana URL (for --init)")
    p.add_argument("--username", help="username (for --init)")
    p.add_argument("--password", help="password (for --init)")
    return p


def _err(msg, code):
    print(f"logalizer: {msg}", file=sys.stderr)
    return code


def main(argv=None):
    args = build_parser().parse_args(argv)

    if args.help_json:
        print(json.dumps(help_json(), indent=2))
        return 0

    try:
        cfg = load_config()
        settings = build_settings(
            os.environ, cfg, space=args.space, index=args.index, fields=args.fields,
            timeout=args.timeout, insecure=(True if args.insecure else None),
        )

        if args.init:
            return init.run_init(args, os.environ, config_path=None)

        if args.ping:
            return ping.run_ping(settings, config_file_path())

        if not settings.url or not settings.username or not settings.password:
            return _err(
                "missing credentials. Set KIBANA_URL/KIBANA_USERNAME/KIBANA_PASSWORD "
                "or ~/.config/logalizer/config.ini. Exit code 2.", 2)

        client = Client(settings.url, settings.username, settings.password,
                        insecure=settings.insecure)

        if args.list_spaces:
            for s in indexpatterns.list_spaces(client):
                print(s)
            return 0
        if args.list_indices:
            for t in indexpatterns.list_index_patterns(client, settings.space):
                print(t)
            return 0
        if args.list_fields:
            if not settings.index:
                return _err("--list-fields requires --index PATTERN", 2)
            for f in indexpatterns.list_fields(client, settings.space, settings.index):
                print(f)
            return 0

        # export
        if not settings.index:
            return _err("--index is required for export", 2)

        time_filter = build_time_filter(args.from_iso, args.to_iso, args.last)

        if args.count:
            if not args.group_by:
                return _err("--count requires --group-by", 2)
            group_fields = [f.strip() for f in args.group_by.split(",") if f.strip()]
            if len(group_fields) > 2:
                return _err(
                    f"--group-by accepts 1 or 2 fields (got {len(group_fields)})", 2)
            result = search.run_count(client, settings.index, args.query,
                                      time_filter, group_fields, args.limit)
            output = aggregate.render(args.fmt, result, group_fields)
        else:
            columns = [c.strip() for c in settings.fields.split(",") if c.strip()] if settings.fields else None

            index_id = indexpatterns.resolve_index_pattern(
                client, settings.space, settings.index)
            if not index_id:
                return _err(
                    f"index pattern {settings.index!r} not found in space "
                    f"{settings.space!r}. Use --list-indices to see available patterns.", 2)

            if args.verbose:
                print(f"submitting CSV job (index={settings.index}, space={settings.space})...",
                      file=sys.stderr)
            job_id = reporting.submit(client, settings.space, index_id,
                                      args.query, time_filter, columns)
            if args.verbose:
                print(f"job {job_id} submitted, waiting...", file=sys.stderr)
            reporting.poll(client, job_id, timeout=settings.timeout)
            if args.verbose:
                print("job completed, downloading...", file=sys.stderr)
            csv_text = reporting.download(client, job_id)
            output = fmt.render(args.fmt, csv_text, args.limit)

        if args.out:
            with open(args.out, "w", encoding="utf-8") as fh:
                fh.write(output)
        else:
            sys.stdout.write(output)
        return 0

    except ClientError as e:
        return _err(str(e) + f" Exit code {e.exit_code}.", e.exit_code)
    except UsageError as e:
        return _err(str(e) + " Exit code 2.", 2)
    except (ValueError, OSError) as e:
        return _err(str(e) + " Exit code 2.", 2)
