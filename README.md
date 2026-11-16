# Bellhaven CRM Reconciliation · Local Assessment Starter

**This is a starter, not a verified final submission.** It was prepared from the exercise brief and the public Bellhaven website. The assessment's authenticated CRM API schema was **not** accessible in this environment. Before any write, inspect the real Swagger docs at `/api/docs` and adapt `crm.py`'s endpoints, `app.py` field names, pagination, and response parsing to the actual documented contract. Do not upload this unverified draft as a finished submission.

## Critical discoveries
- The directory advertises **34** facilities across **3 pages**.
- The homepage advertises **35** and separately links the new **Bellhaven Meadows of Findlay**. The scraper checks the homepage as well as the directory so it does not silently miss Findlay.
- Billing SOP: when `lifetime_revenue > 0` **AND** `outstanding_ar > 0`, preserve the old account's parent; create a new correct-parent account and update only the old account's `chow_current_account` pointer.
- Reconcile to CRM only after a human explicitly approves in the Streamlit app. Approved/rejected proposals remain stored in SQLite for later runs.

## Setup (local Windows/Mac/Linux)

```bash
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env  # Windows PowerShell: Copy-Item .env.example .env
```

Paste your token **only into local `.env`** (`BELLHAVEN_TOKEN=...`). Set `BELLHAVEN_PARENT_ID` to the right parent-company account ID after inspecting accounts. **Never commit `.env`, put the token in a public GitHub repo, or display it during the recording.**

```bash
python inspect_api.py              # READ ONLY, inspect field names and CRM count
python scraper.py > website.json   # READ ONLY, verify 35 distinct communities
python pipeline.py                 # READ ONLY, stores local queue
streamlit run app.py               # UI: only Approve writes to CRM
pytest -q                         # test key reconciliation rules
```

For offline testing, `python pipeline.py --offline my_accounts.json` expects an array of account objects or `{ "accounts": [...] }` (the website scrape still needs access).

## Review and write flow
1. Verify each proposal's URL, address, city/state/ZIP, candidate score, original parent, revenue and AR. Reject uncertain associations.
2. For change of ownership involving **both positive revenue and positive AR**, inspect the CHOW proposal: old parent is retained, new account gets the correct parent, old account only receives `chow_current_account`.
3. Click **Approve and write to CRM** for high-confidence cases, **Reject** for low-confidence cases. The click triggers API writes and saves the decision locally. The UI has no automatic write path.
4. Confirm modifications in the separate CRM browser, including duplicates and CHOW pointers. You must actually approve correct changes before submission — a pending queue alone earns no credit.
5. Re-run `python pipeline.py` and check for no duplicate proposals. If a write failed partway through a CHOW, inspect CRM first and use persisted new-account ID to retry safely.

## Known things you must verify/fix
- **Schema:** `POST /accounts`, `PATCH /accounts/{id}`, pagination, `care_offerings`, `note`, and all account field names must be checked in `/api/docs` before the first approved write.
- **Pagination:** `crm.py` handles lists and some wrappers, but may need adapting to `limit/offset` or cursor pagination if the API requires it; make sure you retrieve all ~120 records.
- **Scraping:** Test the real fetched HTML on your computer; if the address/care-offerings label structure differs, adjust `scraper.py`.
- **Matching:** Current thresholds are heuristics. Basic same-address+ZIP+parent duplicate proposals are included, but ambiguous facilities, location moves, billing-heavy duplicates and historical CHOW copies still require manual review. Improve alias/renaming logic before submission.
- **Daily runs:** `cron.example` runs once daily on the same local computer, preserving the SQLite decisions across runs. Windows users can configure Task Scheduler for `python pipeline.py` with the project folder as the working directory. A cloud schedule would require durable database storage before deployment.
- **Concurrency:** intended for one local reviewer; production needs optimistic locking, transactions/idempotency keys and durable shared DB.
- **Evidence:** Save a crawl snapshot / reviewed match audit in your final writeup.

## Two-minute demo script
- 0:00–0:20: explain reconciliation purpose and 34+1 website discovery.
- 0:20–0:55: open a proposed update; compare website evidence and old CRM parent/balances.
- 0:55–1:20: approve one supported update (CHOW if you can show it safely).
- 1:20–1:35: reject one uncertain proposal; explain conservative review decision.
- 1:35–2:00: open read-only CRM browser and show approved mutation landed.

The assessment also mentions a **45-minute live walkthrough** with a small live system change. Prepare to explain and edit any part of your code without AI prompting.

## Suggested writeup outline
1. Match keys: normalized street and ZIP are stronger than facility names (which may be renamed). Show scores, thresholds and ambiguity routing.
2. Evidence: scraped source URL, current CRM record, mismatch details and financial balances in every proposal.
3. Safety: review-only API writes, historical billing SOP, persisted decisions and rerun safety.
4. AI use: precisely state which models you used and what you validated yourself. Do not claim tests you didn't run.
5. Next steps: deeper dedupe logic, robust API pagination, audit logging, persistent hosted DB and scheduled notifications.

**Track your actual focused working time honestly.**
