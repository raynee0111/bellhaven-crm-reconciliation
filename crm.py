"""CRM API client with verified Bellhaven pagination and account IDs.

GETs are safe. create/patch must only be called after explicit reviewer approval.
"""
from __future__ import annotations
import os
import requests
from dotenv import load_dotenv
load_dotenv()


class CRM:
    def __init__(self, base=None, token=None):
        self.base = (base or os.environ.get("BELLHAVEN_BASE_URL", "https://analyst-assessment-production.up.railway.app")).rstrip("/") + "/api/v1"
        self.token = token or os.environ.get("BELLHAVEN_TOKEN")
        if not self.token:
            raise RuntimeError("BELLHAVEN_TOKEN missing: set it only in local .env")
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {self.token}", "Accept": "application/json"})

    def request(self, method, path, **kwargs):
        response = self.session.request(method, self.base + path, timeout=30, **kwargs)
        if not response.ok:
            raise RuntimeError(f"CRM {method} {path} returned HTTP {response.status_code}: {response.text[:450]}")
        return response.json() if response.content else {}

    def accounts(self):
        """Fetch ALL accounts, checking total and ID uniqueness before matching."""
        records, seen = [], set()
        page_size, page = 50, 1
        expected_total = None
        while page <= 30:
            blob = self.request("GET", f"/accounts?page={page}&page_size={page_size}")
            if not isinstance(blob, dict) or not isinstance(blob.get("data"), list):
                raise ValueError("Unexpected /accounts format; expected {data, page, page_size, total}")
            total = int(blob["total"])
            if expected_total is None:
                expected_total = total
            elif expected_total != total:
                raise RuntimeError("CRM account count changed during pagination; retry from page 1")
            for record in blob["data"]:
                account_id = record.get("account_id")
                if not account_id:
                    raise ValueError("CRM account missing account_id")
                if str(account_id) in seen:
                    raise RuntimeError("Duplicate account_id across pages; pagination may be inconsistent")
                seen.add(str(account_id))
                records.append(record)
            if len(records) >= expected_total:
                break
            if not blob["data"]:
                raise RuntimeError("CRM returned an empty page before total was reached")
            page += 1
        if len(records) != expected_total:
            raise RuntimeError(f"Incomplete CRM response: got {len(records)} / expected {expected_total}")
        return records

    def get(self, account_id):
        return as_record(self.request("GET", f"/accounts/{account_id}"))

    def create(self, fields):
        return self.request("POST", "/accounts", json=fields)

    def patch(self, account_id, fields):
        return self.request("PATCH", f"/accounts/{account_id}", json=fields)


def as_record(response):
    if not isinstance(response, dict):
        raise ValueError("Unexpected CRM response")
    for key in ("account", "data"):
        if isinstance(response.get(key), dict):
            return response[key]
    return response
