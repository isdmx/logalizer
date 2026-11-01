import io
import json
import socket
import ssl
import unittest
from contextlib import ExitStack, redirect_stdout
from email.message import Message
from http.client import IncompleteRead
from urllib.error import HTTPError, URLError
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


def response(status=200, body=b'{}', retry_after=None):
    headers = Message()
    if retry_after is not None:
        headers['Retry-After'] = retry_after
    return HTTPError('https://k.example/api/x', status, 'test', headers,
                     io.BytesIO(body))


class TestRetries(unittest.TestCase):
    def setUp(self):
        self.client = Client('https://k.example', 'u', 'p')
        stack = ExitStack()
        self.addCleanup(stack.close)
        self.sleep = stack.enter_context(mock.patch('time.sleep'))
        stack.enter_context(mock.patch('random.uniform', return_value=1))
        stack.enter_context(mock.patch('time.time', return_value=0))

    def test_transient_statuses_retry_only_safe_requests(self):
        for status in (408, 429, 500, 502, 503, 504):
            for method, path, attempts in (
                ('GET', '/api/x', 2), ('get', '/api/x', 2),
                ('POST', '/internal/search/es', 2),
                ('POST', '/internal/search/es?x=1', 2),
                ('POST', '/s/default/api/reporting/generate/csv_searchsource', 1),
                ('POST', '/internal/search/other', 1),
                ('DELETE', '/api/x', 1),
            ):
                with self.subTest(status=status, method=method, path=path):
                    with mock.patch('urllib.request.urlopen', side_effect=[
                        response(status, b'failed'), response()
                    ]) as opening:
                        result = self.client.request(method, path)
                    self.assertEqual(opening.call_count, attempts)
                    self.assertEqual(result, (200, '{}') if attempts == 2
                                     else (status, 'failed'))

    def test_400_retries_once_for_get_only(self):
        for method, path, expected in (
            ('GET', '/api/x', 2), ('POST', '/internal/search/es', 1),
            ('POST', '/api/reporting/generate/csv_searchsource', 1),
        ):
            with self.subTest(method=method, path=path):
                with mock.patch('urllib.request.urlopen', side_effect=[
                    response(400, b'first'), response(400, b'last'), response()
                ]) as opening:
                    result = self.client.request(method, path)
                self.assertEqual(opening.call_count, expected)
                self.assertEqual(result, (400, 'last' if expected == 2 else 'first'))

    def test_400_can_recover(self):
        with mock.patch('urllib.request.urlopen', side_effect=[response(400), response()]):
            self.assertEqual(self.client.request('GET', '/api/x'), (200, '{}'))
        self.sleep.assert_called_once_with(2)

    def test_other_http_errors_are_not_retried(self):
        for status in (401, 403, 404, 409, 501):
            with self.subTest(status=status):
                with mock.patch('urllib.request.urlopen', side_effect=response(status)) as opening:
                    self.assertEqual(self.client.request('GET', '/api/x')[0], status)
                self.assertEqual(opening.call_count, 1)
        self.sleep.assert_not_called()

    def test_mixed_failures_share_three_attempt_budget(self):
        for statuses in ((400, 503, 200), (503, 400, 200), (503, 503, 429)):
            with self.subTest(statuses=statuses):
                self.sleep.reset_mock()
                with mock.patch('urllib.request.urlopen', side_effect=[
                    response(s, str(s).encode()) for s in statuses
                ]) as opening:
                    self.assertEqual(self.client.request('GET', '/api/x'),
                                     (statuses[-1], str(statuses[-1])))
                self.assertEqual(opening.call_count, 3)
                self.assertEqual(self.sleep.call_args_list, [mock.call(2), mock.call(4)])

    def test_retry_after(self):
        for header, delay in (
            ('5', 5), ('Thu, 01 Jan 1970 00:00:05 GMT', 5),
            ('Wed, 31 Dec 1969 23:59:59 GMT', 2),
            ('Thu Jan  1 00:00:05 1970', 5),
            ('invalid', 2), ('-3', 2), ('1e100', 2), ('30', 30),
        ):
            with self.subTest(header=header):
                self.sleep.reset_mock()
                with mock.patch('urllib.request.urlopen', side_effect=[
                    response(429, retry_after=header), response()
                ]):
                    self.assertEqual(self.client.request('GET', '/api/x')[0], 200)
                self.sleep.assert_called_once_with(delay)

    def test_retry_after_is_not_shortened_by_jitter(self):
        with mock.patch('random.uniform', return_value=0.5), \
             mock.patch('urllib.request.urlopen', side_effect=[
                 response(429, retry_after='5'), response()
             ]):
            self.client.request('GET', '/api/x')
        self.sleep.assert_called_once_with(5)

    def test_excessive_retry_after_returns_response_without_waiting(self):
        with mock.patch('urllib.request.urlopen', side_effect=response(503, b'busy', '31')) as opening:
            self.assertEqual(self.client.request('GET', '/api/x'), (503, 'busy'))
        self.assertEqual(opening.call_count, 1)
        self.sleep.assert_not_called()

    def test_temporary_transport_errors_retry_safe_requests(self):
        errors = [TimeoutError('timed out'), ConnectionResetError('reset'),
                  IncompleteRead(b'partial', 10), URLError(ConnectionRefusedError('refused')),
                  URLError(socket.gaierror(socket.EAI_AGAIN, 'temporary DNS failure'))]
        for error in errors:
            for method, path in [('GET', '/api/x'), ('POST', '/internal/search/es')]:
                with self.subTest(error=repr(error), method=method):
                    with mock.patch('urllib.request.urlopen', side_effect=[error, response()]) as opening:
                        self.assertEqual(self.client.request(method, path), (200, '{}'))
                    self.assertEqual(opening.call_count, 2)

    def test_permanent_errors_and_mutating_requests_do_not_retry(self):
        cases = [
            ('GET', ssl.SSLCertVerificationError('certificate invalid')),
            ('GET', URLError(ssl.SSLCertVerificationError('certificate invalid'))),
            ('GET', URLError(socket.gaierror(socket.EAI_NONAME, 'unknown host'))),
            ('GET', URLError('unsupported protocol')),
            ('POST', TimeoutError('timed out')),
        ]
        for method, error in cases:
            with self.subTest(method=method, error=repr(error)):
                with mock.patch('urllib.request.urlopen', side_effect=error) as opening:
                    with self.assertRaises(ClientError) as raised:
                        self.client.request(method, '/api/reporting/generate/csv_searchsource')
                self.assertEqual(raised.exception.exit_code, 5)
                self.assertEqual(opening.call_count, 1)
        self.sleep.assert_not_called()

    def test_exhausted_transport_errors_keep_last_reason(self):
        with mock.patch('urllib.request.urlopen', side_effect=[
            TimeoutError('first'), TimeoutError('second'), TimeoutError('last')
        ]) as opening:
            with self.assertRaises(ClientError) as raised:
                self.client.request('GET', '/api/x')
        self.assertIn('last', str(raised.exception))
        self.assertEqual(raised.exception.exit_code, 5)
        self.assertEqual(opening.call_count, 3)
        self.assertEqual(self.sleep.call_count, 2)

    def test_retries_read_failure_and_preserves_request(self):
        broken = response()
        broken.read = mock.Mock(side_effect=IncompleteRead(b'partial', 5))
        output = io.StringIO()
        with mock.patch('urllib.request.urlopen', side_effect=[broken, response()]) as opening, \
             redirect_stdout(output):
            self.assertEqual(self.client.request('POST', '/internal/search/es', {'query': '*'}),
                             (200, '{}'))
        for call in opening.call_args_list:
            request = call.args[0]
            self.assertEqual(request.get_method(), 'POST')
            self.assertEqual(json.loads(request.data), {'query': '*'})
            self.assertEqual(request.get_header('Authorization'), 'Basic dTpw')
            self.assertEqual(request.get_header('kbn-xsrf'), 'true')
            self.assertEqual(request.get_header('Content-type'), 'application/json')
            self.assertEqual(call.kwargs['timeout'], 30)
        self.assertEqual(output.getvalue(), '')

    def test_truncated_error_body_preserves_http_retry_policy(self):
        for status, header, attempts in ((401, None, 1), (400, None, 2),
                                          (503, '31', 1), (503, '5', 3)):
            with self.subTest(status=status, header=header):
                errors = [response(status, retry_after=header) for _ in range(3)]
                for error in errors:
                    error.read = mock.Mock(side_effect=IncompleteRead(b'partial', 5))
                self.sleep.reset_mock()
                with mock.patch('urllib.request.urlopen', side_effect=errors) as opening:
                    actual_status, body = self.client.request('GET', '/api/x')
                self.assertEqual(actual_status, status)
                self.assertTrue(body)
                self.assertEqual(opening.call_count, attempts)
                self.assertEqual(self.sleep.call_count, attempts - 1)
                if header == '5':
                    self.assertEqual(self.sleep.call_args_list, [mock.call(5), mock.call(5)])

    def test_truncated_success_body_ignores_retry_after(self):
        for method, path in [('GET', '/api/x'), ('POST', '/internal/search/es')]:
            with self.subTest(method=method):
                broken = response(retry_after='31')
                broken.read = mock.Mock(side_effect=IncompleteRead(b'partial', 5))
                self.sleep.reset_mock()
                with mock.patch('urllib.request.urlopen', side_effect=[broken, response()]) as opening:
                    self.assertEqual(self.client.request(method, path), (200, '{}'))
                self.assertEqual(opening.call_count, 2)
                self.sleep.assert_called_once_with(2)


if __name__ == "__main__":
    unittest.main()
