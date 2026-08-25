"""logalizer — export Kibana logs as CSV via the Reporting API."""

try:
    from importlib.metadata import version as _version

    __version__ = _version("logalizer")
except Exception:  # pragma: no cover - fallback for uninstalled source tree
    __version__ = "0.0.0"
