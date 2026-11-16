# Bellhaven CRM Reconciliation

Human-in-the-loop CRM ownership reconciliation using Python, the Bellhaven website, a CRM API, SQLite, and Streamlit.

## Project Summary

The pipeline extracts 35 facilities from the Bellhaven website, retrieves 121 CRM accounts, normalizes facility names and addresses, and generates reconciliation proposals for human review.

The reviewer can inspect website evidence alongside CRM records and explicitly Approve or Reject proposed actions. CRM modifications occur only after approval.

## Implemented Features

- Website scraping across directory pages and homepage links
- Paginated CRM account retrieval
- Facility matching using address, ZIP code, name, and location signals
- Review workflow for creates, updates, duplicates, and ownership changes
- SQLite persistence for review decisions
- Revenue and accounts-receivable safeguards for change-of-ownership (CHOW) cases
- Duplicate-account handling and error checks
- Local scheduling example

## Verification

- 35 website facilities collected
- 121 CRM accounts retrieved
- 26 initial review candidates evaluated
- 15 automated tests passed
- Two CHOW cases verified against CRM records, preserving historical revenue, outstanding AR, and original parent accounts while linking newly created successor accounts

## Run Locally

```bash
python -m venv .venv
python -m pip install -r requirements.txt
python pipeline.py
python -m streamlit run app.py
python -m pytest -q
```

Configure `BELLHAVEN_TOKEN` and `BELLHAVEN_PARENT_ID` in a local `.env` file before connecting to the assessment CRM. Never commit credentials.

## Review and Safety

Only explicit reviewer approval triggers CRM writes. Financially sensitive CHOW cases create a successor account under the new parent and update only the historical account's `chow_current_account` pointer.

Ambiguous matching cases are not automatically merged or reparented. Unresolved cases include Kettering's multiple same-address accounts and Portsmouth's discrepancy between facility and billing ZIP codes.

## Limitations and Next Steps

The Streamlit review interface runs locally. A production deployment would require a hosted application, durable shared database, stronger concurrency handling, and improved automated duplicate resolution.

## AI Assistance

AI assistance was used for implementation support, debugging, and documentation. The workflow was executed and validated against the assessment CRM, including automated tests and manual record checks.

