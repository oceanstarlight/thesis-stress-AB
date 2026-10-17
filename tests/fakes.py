"""Offline fake HTTP and SEC payload builders used by the tests."""

from __future__ import annotations

import json

from riskprobe.http import Response, public_url


class FakeHttp:
    """Routes: (url, params subset, status, payload). First match wins; unmatched -> 404."""

    def __init__(self):
        self.routes: list[tuple[str, dict, int, object]] = []
        self.calls: list[tuple[str, dict]] = []

    def add(self, url: str, payload, params: dict | None = None, status: int = 200) -> "FakeHttp":
        self.routes.append((url, params or {}, status, payload))
        return self

    def get(self, url, params=None, headers=None, auth=None, ttl_hours=None) -> Response:
        params = params or {}
        self.calls.append((url, params))
        for r_url, r_params, status, payload in self.routes:
            if r_url == url and all(str(params.get(k)) == str(v) for k, v in r_params.items()):
                body = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
                return Response(status, body, public_url(url, params))
        return Response(404, b"{}", public_url(url, params))


def fact_row(val, start, end, accn, filed, form="10-Q") -> dict:
    row = {"end": end, "val": val, "accn": accn, "form": form, "filed": filed}
    if start:
        row["start"] = start
    return row


def company_facts(name: str, concepts: dict[str, list[dict]], unit: str = "USD") -> dict:
    return {"entityName": name, "facts": {"us-gaap": {c: {"units": {unit: rows}} for c, rows in concepts.items()}}}


def submissions(name: str, filings: list[tuple[str, str, str]]) -> dict:
    """filings: (accession, form, filing date)."""
    return {"name": name, "filings": {"recent": {
        "accessionNumber": [f[0] for f in filings], "form": [f[1] for f in filings],
        "filingDate": [f[2] for f in filings], "acceptanceDateTime": [f"{f[2]}T21:00:00.000Z" for f in filings],
        "reportDate": [""] * len(filings), "items": [""] * len(filings), "primaryDocument": ["doc.htm"] * len(filings),
    }, "files": []}}
