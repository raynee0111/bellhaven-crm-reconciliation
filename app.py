"""Human-in-the-loop review UI. Only an explicit Approve button calls CRM writes."""
from __future__ import annotations
import json
import streamlit as st
from crm import CRM, as_record
from queue_db import by_id, list_items, update

st.set_page_config(page_title="Bellhaven CRM review", page_icon="🔎", layout="wide")
st.title("Bellhaven · CRM ownership review")
st.caption("Review website evidence and CRM record side-by-side. No CRM writes happen until you click Approve.")


from review_actions import commit


def approve(item):
    crm = CRM()
    return commit(item, crm, lambda state, result: update(item["id"], state, result))


items = list_items()
if not items:
    st.success("No pending/error proposals. Re-run pipeline after upstream changes.")
else:
    kinds = sorted(set(p["kind"] for p in items))
    kind_choice = st.selectbox("Filter type", ["All"] + kinds)
    visible = [p for p in items if kind_choice == "All" or p["kind"] == kind_choice]
    st.metric("Awaiting review / retry", len(items))
    for item in visible:
        p, evidence = json.loads(item["payload"]), json.loads(item["evidence"])
        with st.expander(f"#{item['id']} · {item['kind'].upper()} · {item['facility']} · {item['state']}"):
            left, right = st.columns(2)
            with left:
                st.subheader("Website location")
                st.json(p.get("location", {}), expanded=True)
                if evidence.get("website"):
                    st.markdown(f"[Open website evidence]({evidence['website']})")
            with right:
                st.subheader("Existing CRM record / signals")
                st.json(evidence.get("crm_account") or {}, expanded=False)
                st.json({k:v for k,v in evidence.items() if k not in ("crm_account", "website")}, expanded=True)
            st.subheader("Exact proposed CRM action")
            if item["kind"] == "chow":
                st.warning("CHOW: CREATE a new facility under the target parent, then PATCH ONLY old.chow_current_account. Do NOT re-parent the old account.")
                st.json({"new_account_parent_id":p.get("target_parent_id"), "old_account_mutation":"chow_current_account only"})
            else:
                st.json({"account_id":p.get("account_id"), "fields":p.get("fields")})
            if item["state"] == "error":
                st.error(f"Previous attempt needs investigation: {item['result']}")
            col1, col2 = st.columns(2)
            if col1.button("Approve and write to CRM", key=f"approve_{item['id']}", type="primary"):
                try:
                    # A row may have changed since UI render. Check database state again.
                    fresh = by_id(item["id"])
                    result = approve(fresh)
                    update(item["id"], "approved", result)
                    st.success("Approved; CRM write completed. Verify in the CRM browser.")
                    st.rerun()
                except Exception as exc:
                    # Preserve any partial CHOW phase state for safe retry.
                    fresh = by_id(item["id"])
                    saved = json.loads(fresh.get("result") or "{}")
                    saved["last_error"] = str(exc)
                    update(item["id"], "error", saved)
                    st.error(f"Write incomplete: {exc}. Check CRM before retrying.")
            if col2.button("Reject (do not write)", key=f"reject_{item['id']}"):
                update(item["id"], "rejected", {"note":"Reviewer rejected after inspecting evidence"})
                st.success("Rejected; this decision persists across future runs.")
                st.rerun()

st.divider()
st.caption("Reviewer SOP: confirm identity and billing balances; demonstrate approving AND rejecting items; inspect updated CRM in browser. Never expose your API token on screen.")
