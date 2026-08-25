"""Minimal rison encoder (the wire format Kibana's reporting API expects).

Rison: strings '...' (! -> !!, ' -> !'), null !n, true !t, false !f,
array !(...), object (key:value,...). Keys matching an identifier are bare;
all other keys are quoted.
"""
import re

_ID_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")


def _escape(s):
    return s.replace("!", "!!").replace("'", "!'")


def encode(value):
    if value is None:
        return "!n"
    if value is True:
        return "!t"
    if value is False:
        return "!f"
    if isinstance(value, str):
        return "'" + _escape(value) + "'"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        parts = []
        for k, v in value.items():
            key = k if _ID_RE.match(k) else "'" + _escape(k) + "'"
            parts.append(key + ":" + encode(v))
        return "(" + ",".join(parts) + ")"
    if isinstance(value, (list, tuple)):
        return "!(" + ",".join(encode(v) for v in value) + ")"
    raise TypeError(f"cannot rison-encode {type(value).__name__}")
