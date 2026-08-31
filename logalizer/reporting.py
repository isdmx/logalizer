"""Async CSV reporting job lifecycle: submit → poll → download."""
import json
import time

from logalizer import rison
from logalizer.client import ClientError, raise_for_status

KIBANA_VERSION = "7.17.29"


def submit(client, space, index_id, query, time_filter, columns):
    search_source = {
        "index": index_id,
        "query": {"query": query, "language": "kuery"},
    }
    if time_filter is not None:
        search_source["filter"] = [time_filter]
    job_params = {
        "title": "logalizer export",
        "objectType": "search",
        "browserTimezone": "UTC",
        "version": KIBANA_VERSION,
        "searchSource": search_source,
    }
    if columns:
        job_params["columns"] = columns
    body = {"jobParams": rison.encode(job_params)}
    path = f"/s/{space}/api/reporting/generate/csv_searchsource"
    status, raw = client.request("POST", path, body)
    raise_for_status(status, raw, "submit CSV job",
                     hint="CSV export via the reporting API requires the 'reporting_user' role — try --export-backend search.")
    return json.loads(raw)["job"]["id"]


def poll(client, job_id, timeout=120):
    deadline = time.time() + timeout
    while time.time() < deadline:
        status, raw = client.request(
            "GET", "/api/reporting/jobs/list?page=0&size=100"
        )
        raise_for_status(status, raw, "poll job")
        for job in json.loads(raw):
            if job["id"] == job_id:
                if job["status"] == "completed":
                    return
                if job["status"] == "failed":
                    out = job.get("output") or {}
                    detail = out.get("warnings") or out.get("error") or out
                    raise ClientError(
                        f"job {job_id} failed: {detail!r}. "
                        "Try narrowing --query or --last.", 4)
        time.sleep(2)
    raise ClientError(f"job {job_id} did not complete within {timeout}s", 4)


def download(client, job_id):
    status, raw = client.request(
        "GET", f"/api/reporting/jobs/download/{job_id}"
    )
    raise_for_status(status, raw, "download CSV")
    return raw
