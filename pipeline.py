"""Safe discovery only; creates local proposals, never writes to CRM."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
from dotenv import load_dotenv
from crm import CRM
from matching import build_proposals
from queue_db import add
from scraper import scrape_all
load_dotenv()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--offline", help="Read CRM accounts from JSON instead of API")
    args = p.parse_args()
    locations, audit = scrape_all()
    print("Website audit:", audit)
    if audit["complete_against_homepage"] is False:
        raise RuntimeError("Website count mismatch; stopping to avoid unsafe proposals")
    if args.offline:
        blob = json.loads(Path(args.offline).read_text(encoding="utf-8"))
        accounts = blob["accounts"] if isinstance(blob, dict) else blob
    else:
        accounts = CRM().accounts()
    if not args.offline and len(accounts) < 100:
        raise RuntimeError(f"Only {len(accounts)} accounts fetched; expected around 120. Verify API pagination before any review.")
    parent_id = os.environ.get("BELLHAVEN_PARENT_ID")
    if not parent_id:
        candidates = [a for a in accounts if "bellhaven" in str(a.get("name", "")).lower() and ("senior living" in str(a.get("name", "")).lower() or "corporate" in str(a.get("name", "")).lower())]
        print("Possible parent account IDs:", [(a.get("account_id"),a.get("name")) for a in candidates])
        raise RuntimeError("Set BELLHAVEN_PARENT_ID to the CORRECT parent company account ID")
    proposals = build_proposals(locations, accounts, parent_id)
    new_count = add(proposals)
    print(f"Read {len(accounts)} CRM accounts; made {len(proposals)} candidates; {new_count} newly queued")
    print("Run: streamlit run app.py")


if __name__ == "__main__":
    main()
