import unittest

from logalizer import reporting
from logalizer.client import ClientError


class _Fake:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def request(self, method, path, body=None):
        self.calls.append((method, path, body))
        return self._responses.pop(0)


class TestSubmit(unittest.TestCase):
    def test_submits_rison_jobparams(self):
        c = _Fake([(200, '{"job": {"id": "j1"}}')])
        jid = reporting.submit(
            c, "default", "abc-id", 'level:error', None, ["@timestamp", "msg"]
        )
        self.assertEqual(jid, "j1")
        method, path, body = c.calls[0]
        self.assertEqual(method, "POST")
        self.assertIn("/s/default/api/reporting/generate/csv_searchsource", path)
        self.assertIn("jobParams", body)
        jp = body["jobParams"]
        self.assertIn("index:'abc-id'", jp)
        self.assertIn("query:(query:'level:error',language:'kuery')", jp)
        self.assertIn("columns:!('@timestamp','msg')", jp)

    def test_omits_columns_when_none(self):
        c = _Fake([(200, '{"job": {"id": "j2"}}')])
        reporting.submit(c, "default", "abc-id", "", None, None)
        self.assertNotIn("columns", c.calls[0][2]["jobParams"])


class TestPoll(unittest.TestCase):
    def test_completed(self):
        c = _Fake([(200, '[{"id":"j1","status":"completed"}]')])
        reporting.poll(c, "j1", timeout=60)  # should not raise

    def test_failed_raises(self):
        c = _Fake([(200, '[{"id":"j1","status":"failed","output":{"warnings":["boom"]}}]')])
        with self.assertRaises(ClientError) as ctx:
            reporting.poll(c, "j1", timeout=60)
        self.assertEqual(ctx.exception.exit_code, 4)
        self.assertIn("boom", str(ctx.exception))


class TestDownload(unittest.TestCase):
    def test_returns_csv(self):
        c = _Fake([(200, "a,b\n1,2\n")])
        self.assertEqual(reporting.download(c, "j1"), "a,b\n1,2\n")


if __name__ == "__main__":
    unittest.main()
