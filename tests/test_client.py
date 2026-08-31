import unittest
from unittest import mock

from logalizer.client import Client, ClientError, raise_for_status


class TestClient(unittest.TestCase):
    def test_basic_auth_header(self):
        c = Client("https://k.example", "user", "pass")
        self.assertEqual(c.base, "https://k.example")
        self.assertEqual(c.auth, "Basic dXNlcjpwYXNz")

    def test_request_sends_headers(self):
        c = Client("https://k.example", "u", "p")
        with mock.patch("urllib.request.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.status = 200
            urlopen.return_value.__enter__.return_value.read.return_value = b"{}"
            status, body = c.request("GET", "/api/x")
        self.assertEqual(status, 200)
        req = urlopen.call_args[0][0]
        self.assertEqual(req.get_header("kbn-xsrf"), "true")
        self.assertEqual(req.get_header("Authorization"), "Basic dTpw")

    def test_http_error_is_returned_not_raised(self):
        from urllib.error import HTTPError
        c = Client("https://k.example", "u", "p")
        err = HTTPError("url", 401, "Unauthorized", None, None)
        with mock.patch("urllib.request.urlopen", side_effect=err) as urlopen:
            err.read = lambda: b'{"error":"nope"}'
            status, body = c.request("GET", "/api/x")
        self.assertEqual(status, 401)
        self.assertIn("nope", body)

    def test_network_error_raises_client_error(self):
        from urllib.error import URLError
        c = Client("https://k.example", "u", "p")
        with mock.patch("urllib.request.urlopen", side_effect=URLError("conn refused")):
            with self.assertRaises(ClientError) as ctx:
                c.request("GET", "/api/x")
        self.assertEqual(ctx.exception.exit_code, 5)


class TestRaiseForStatusHint(unittest.TestCase):
    def test_403_appends_hint(self):
        with self.assertRaises(ClientError) as ctx:
            raise_for_status(403, "", "whatever", hint="try --export-backend search")
        self.assertIn("--export-backend search", str(ctx.exception))
        self.assertEqual(ctx.exception.exit_code, 3)

    def test_403_no_hint_unchanged(self):
        with self.assertRaises(ClientError) as ctx:
            raise_for_status(403, "", "whatever")
        self.assertNotIn("--export-backend", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
