"""Explicit reviewer-approved CRM actions, with financial/duplicate safety checks.

No function in this module is called by the read-only pipeline.
Only the app's real Approve button calls commit().
"""
from __future__ import annotations
import json
import re
from matching import account_id, chow_required, money, norm, textval
from crm import as_record


def _street_key(value):
    value = norm(value)
    for long_name, short_name in (
        ("west", "w"), ("east", "e"),
        ("north", "n"), ("south", "s")
    ):
        value = re.sub(r"\b" + long_name + r"\b", short_name, value)
    return value


class ReviewBlocked(RuntimeError):
    """Proposal can no longer be applied safely; refresh CRM and review again."""


def _has_matching_facility(accounts, loc, parent_id, exclude_ids=()):
    """Avoid accidentally creating another facility that already exists at this address.

    Uses exact normalized address + ZIP. Excludes only explicitly given old IDs;
    if any same-site CRM record already belongs to target parent, stop.
    """
    excluded = {str(i) for i in exclude_ids}
    return [a for a in accounts
            if str(account_id(a)) not in excluded
            and str(a.get("parent_id") or "") == str(parent_id)
            and norm(textval(a, "address")) == norm(loc["address"])
            and norm(textval(a, "zip")) == norm(loc["zip"])]


def commit(item, crm, save_partial):
    """Run only after a human explicitly approves. save_partial persists CHOW phase.

    crm must implement get, accounts, create, patch. save_partial(state, details)
    persists partial CHOW progress so a failed pointer update won't create twice.
    """
    if item["state"] not in ("pending", "error"):
        raise ReviewBlocked("This proposal has already been decided")
    p, evidence = json.loads(item["payload"]), json.loads(item["evidence"])
    kind, aid = item["kind"], p.get("account_id")
    loc = p.get("location") or {}

    if kind == "create":
        fields = p["fields"]
        if _has_matching_facility(crm.accounts(), loc, fields["parent_id"]):
            raise ReviewBlocked("A target-parent CRM account already exists at this address/ZIP. Refresh the queue; do not create a duplicate.")
        created = as_record(crm.create(fields))
        if not account_id(created):
            raise ReviewBlocked("Create returned no id. Inspect CRM manually before retrying; the create may have succeeded.")
        return {"created_account_id": account_id(created)}

    if not aid:
        raise ReviewBlocked("Missing CRM account ID")
    current = crm.get(aid)  # Fresh, not the cached account captured during discovery.
    if not current or str(account_id(current)) != str(aid):
        raise ReviewBlocked("Account ID missing or inconsistent; refresh before approving")

    if kind == "update":
        fields = p["fields"]
        if "parent_id" in fields:
            # SOP always checked at time of write, even if the queue is old.
            if chow_required(current):
                raise ReviewBlocked("CHOW SOP: current record now has positive lifetime revenue AND outstanding AR. Do not re-parent; re-run pipeline.")
            if current.get("chow_current_account"):
                raise ReviewBlocked("Historical CHOW account has successor; do not re-parent it")
            if str(current.get("parent_id") or "") == str(fields["parent_id"]):
                if set(fields) == {"parent_id"}:
                    return {"already_correct": True, "account_id": aid}
        if current.get("duplicate_of_account"):
            raise ReviewBlocked("This is a known duplicate; do not update it without fresh review")
        crm.patch(aid, fields)
        return {"updated_account_id": aid, "changes": fields}

    if kind == "duplicate":
        if (money(current.get("lifetime_revenue")) > 0 or
            money(current.get("outstanding_ar")) > 0 or
            current.get("chow_current_account")):
            raise ReviewBlocked("Potential duplicate now has billing history or a CHOW successor. Do not inactivate automatically.")
        survivor = str(p["fields"]["duplicate_of_account"])
        surviving_record = crm.get(survivor)
        if not surviving_record:
            raise ReviewBlocked("Surviving account not found")
        if (_street_key(textval(surviving_record, "address")) != _street_key(textval(current, "address"))
            or norm(textval(surviving_record, "zip")) != norm(textval(current, "zip"))
            or norm(textval(surviving_record, "city")) != norm(textval(current, "city"))
            or norm(textval(surviving_record, "state")) != norm(textval(current, "state"))):
            raise ReviewBlocked("Survivor's address/ZIP no longer matches this candidate")
        crm.patch(aid, p["fields"])
        return {"deactivated_duplicate_id": aid, "survivor_id": survivor}

    if kind == "investigate":
        reason = evidence.get("reason", "Needs manual review")
        note = f"Bellhaven reconciliation: {reason}. Website evidence: {evidence.get('website') or 'none'}"
        crm.patch(aid, {"status": "Needs Review", "note": note})
        return {"marked_needs_review": aid}

    if kind == "chow":
        target_parent_id = p["target_parent_id"]
        prior = json.loads(item.get("result") or "{}")
        new_id = prior.get("created_account_id")
        linked_id = current.get("chow_current_account")
        if linked_id:
            if new_id and str(linked_id) == str(new_id):
                return {"created_account_id": new_id, "old_account_id": aid,
                        "chow_pointer_set": True, "already_applied": True}
            raise ReviewBlocked("Old account already has a different CHOW successor; stop and inspect")
        if str(current.get("parent_id")) == str(target_parent_id):
            raise ReviewBlocked("Old account already has target parent; CHOW no longer applies")
        if not chow_required(current):
            raise ReviewBlocked("Financial state changed; re-run pipeline to evaluate direct re-parenting")
        if not new_id:
            existing = _has_matching_facility(crm.accounts(), loc, target_parent_id, exclude_ids=(aid,))
            if existing:
                raise ReviewBlocked("Target-parent facility record already exists at this address/ZIP. Manually inspect before creating CHOW successor.")
            payload = {"name": loc["name"], "billing_street": loc["address"], "billing_city": loc["city"],
                       "billing_state": loc["state"], "billing_zip": loc["zip"],
                       "parent_id": target_parent_id, "status": "Active"}
            new_account = as_record(crm.create(payload))
            new_id = account_id(new_account)
            if not new_id:
                raise ReviewBlocked("CHOW new account may have been created but has no response ID. Inspect CRM before retrying.")
            # Save BEFORE the second write. This prevents accidental double creation.
            save_partial("error", {"created_account_id": new_id,
                                   "phase": "new account created; old pointer pending"})
        # CHOW: deliberately leave EVERY old-account field untouched except pointer.
        crm.patch(aid, {"chow_current_account": new_id})
        return {"created_account_id": new_id, "old_account_id": aid, "chow_pointer_set": True}

    raise ReviewBlocked(f"Unsupported proposal type: {kind}")
