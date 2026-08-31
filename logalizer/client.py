"""HTTP layer: basic auth + kbn-xsrf header, urllib-backed."""
import base64
import json
import ssl
import urllib.error
import urllib.request


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
        req = urllib.request.Request(
            self.base + path, data=data, method=method, headers=headers
        )
        req.headers["kbn-xsrf"] = "true"
        try:
            with urllib.request.urlopen(req, context=self._context(),
                                        timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
                return resp.status, raw
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8")
        except urllib.error.URLError as e:
            raise ClientError(f"network error: {e.reason}", 5)
