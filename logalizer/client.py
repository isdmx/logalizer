"""HTTP layer: basic auth + kbn-xsrf header, urllib-backed."""
import base64
import json
import random
import socket
import ssl
import time
import urllib.error
import urllib.request
from datetime import timezone
from email.utils import parsedate_to_datetime
from http.client import IncompleteRead
from urllib.parse import urlsplit


_RETRY_STATUSES = {408, 429, 500, 502, 503, 504}
_MAX_ATTEMPTS = 3
_MAX_RETRY_DELAY = 30


def _temporary_error(error):
    reason = getattr(error, "reason", error)
    if isinstance(reason, socket.gaierror):
        return reason.errno == socket.EAI_AGAIN
    return isinstance(reason, (TimeoutError, ConnectionError, IncompleteRead))


def _retry_delay(attempt, retry_after):
    delay = (2 ** (attempt + 1)) * random.uniform(0.5, 1.0)
    if retry_after:
        try:
            seconds = int(retry_after)
        except ValueError:
            try:
                date = parsedate_to_datetime(retry_after)
                if date.tzinfo is None:
                    date = date.replace(tzinfo=timezone.utc)
                seconds = date.timestamp() - time.time()
            except (ValueError, TypeError, OverflowError):
                return delay
        delay = max(delay, seconds)
    return delay


class ClientError(Exception):
    def __init__(self, message, exit_code):
        super().__init__(message)
        self.exit_code = exit_code


def raise_for_status(status, body, what, hint=None):
    if status == 401:
        raise ClientError("authentication failed (401). Check KIBANA_USERNAME/KIBANA_PASSWORD.", 3)
    if status == 403:
        msg = "permission denied (403). Role lacks access to this space."
        if hint:
            msg += " " + hint
        raise ClientError(msg, 3)
    if status >= 400:
        raise ClientError(f"{what} failed ({status}): {body}", 5)


class Client:
    def __init__(self, url, username, password, insecure=False, timeout=30):
        self.base = (url or "").rstrip("/")
        self.auth = "Basic " + base64.b64encode(
            f"{username}:{password}".encode("utf-8")
        ).decode("ascii")
        self.insecure = insecure
        self.timeout = timeout

    def _context(self):
        if self.insecure:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            return ctx
        return None

    def request(self, method, path, body=None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Authorization": self.auth}
        if data is not None:
            headers["Content-Type"] = "application/json"
        method = method.upper()
        safe = method == "GET" or (
            method == "POST" and urlsplit(path).path == "/internal/search/es")
        retried_400 = False
        for attempt in range(_MAX_ATTEMPTS):
            req = urllib.request.Request(
                self.base + path, data=data, method=method, headers=dict(headers)
            )
            req.headers["kbn-xsrf"] = "true"
            retry_after = None
            try:
                try:
                    response = urllib.request.urlopen(
                        req, context=self._context(), timeout=self.timeout)
                except urllib.error.HTTPError as error:
                    response = error
                with response as resp:
                    status = resp.status
                    if resp.headers is not None:
                        retry_after = resp.headers.get("Retry-After")
                    try:
                        raw = resp.read().decode("utf-8")
                    except (urllib.error.URLError, OSError, IncompleteRead) as error:
                        if status < 400:
                            raise
                        # Preserve the HTTP policy even when its error body is truncated.
                        reason = getattr(error, "reason", error)
                        raw = f"could not read error response: {reason}"
                retry_400 = status == 400 and method == "GET" and not retried_400
                if (not safe or attempt == _MAX_ATTEMPTS - 1
                        or (status not in _RETRY_STATUSES and not retry_400)):
                    return status, raw
                retried_400 = retried_400 or retry_400
            except (urllib.error.URLError, OSError, IncompleteRead) as error:
                if not safe or attempt == _MAX_ATTEMPTS - 1 or not _temporary_error(error):
                    reason = getattr(error, "reason", error)
                    raise ClientError(f"network error: {reason}", 5) from error
            delay = _retry_delay(attempt, retry_after)
            if delay > _MAX_RETRY_DELAY:
                return status, raw
            time.sleep(delay)
