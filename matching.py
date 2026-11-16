"""Rule-based, evidence-driven matching with conservative ambiguity handling."""
from __future__ import annotations
from difflib import SequenceMatcher
import hashlib
import json
import re


def norm(value):
    value = str(value or "").casefold().strip()
    substitutions = {"street": "st", "avenue": "ave", "road": "rd", "boulevard": "blvd", "drive": "dr", "lane": "ln", "suite": "ste"}
    value = re.sub(r"[^a-z0-9 ]+", " ", value)
    words = [substitutions.get(w, w) for w in value.split()]
    return " ".join(words)


def account_id(a):
    """Real API uses account_id; the fallback keeps old fixture tests readable."""
    return a.get("account_id") or a.get("id")


def textval(a, field):
    # Keep mapping narrow and visible to reviewers; verify against Swagger response.
    aliases = {"address": ["billing_street", "address", "street_address", "address_line1"],
               "zip": ["billing_zip", "zip", "zip_code", "postal_code"],
               "name": ["name", "account_name"],
               "city": ["billing_city", "city"], "state": ["billing_state", "state"]}
    return next((a[x] for x in aliases.get(field, [field]) if a.get(x) is not None), "")


def money(value):
    try:
        return float(str(value or 0).replace(",", "").replace("$", ""))
    except (TypeError, ValueError):
        return 0.0


def chow_required(a):
    return money(a.get("lifetime_revenue")) > 0 and money(a.get("outstanding_ar")) > 0


def similarity(left, right):
    return SequenceMatcher(None, norm(left), norm(right)).ratio()


def candidate_score(loc, account):
    """Address and zip are stronger identity signals than a mutable facility name."""
    street = similarity(loc["address"], textval(account, "address"))
    zip_exact = norm(loc["zip"]) == norm(textval(account, "zip"))
    city_exact = norm(loc["city"]) == norm(textval(account, "city"))
    state_exact = norm(loc["state"]) == norm(textval(account, "state"))
    name = similarity(loc["name"], textval(account, "name"))
    score = round(0.45 * street + 0.20 * float(zip_exact) + 0.10 * float(city_exact) + 0.05 * float(state_exact) + 0.20 * name, 3)
    return score, {"street_similarity": round(street, 3), "name_similarity": round(name, 3),
                   "zip_exact": zip_exact, "city_exact": city_exact, "state_exact": state_exact}


def proposal(kind, loc, account=None, fields=None, evidence=None, extra=None):
    aid = str(account_id(account)) if account is not None else "new"
    # Same requested change => same key after a rerun; a later DIFFERENT change
    # => a new key, so this still works as an ongoing daily reconciliation.
    signature = {"fields":fields or {}, "extra":extra or {},
                 "website_fields":{k:loc.get(k) for k in ("name", "address", "city", "state", "zip", "care_offerings")}}
    digest = hashlib.sha256(json.dumps(signature, sort_keys=True, default=str).encode()).hexdigest()[:14]
    key = f"{kind}:{loc.get('slug', 'unknown')}:{aid}:{digest}"
    return {"dedupe_key": key, "kind": kind, "facility": loc["name"],
            "payload": {"location": loc, "account_id": account_id(account) if account else None,
                        "fields": fields or {}, **(extra or {})},
            "evidence": {"website": loc.get("source_url"),
                         "crm_account": account, **(evidence or {})}}


def build_proposals(locations, accounts, parent_id):
    parent_id = str(parent_id)
    proposals, selected = [], set()
    account_index = {str(account_id(a)): a for a in accounts}
    # The parent is an account, not an actual facility.
    facility_accounts = [a for a in accounts if str(account_id(a)) != parent_id]
    matched_to_site = set()
    for loc in locations:
        ranked = sorted(((candidate_score(loc, a)[0], a) for a in facility_accounts),
            key=lambda x:(x[0], str(x[1].get("parent_id") or "") == parent_id,
                          not bool(x[1].get("chow_current_account"))), reverse=True)
        best_score, best = ranked[0] if ranked else (0, None)
        runnerup = ranked[1][0] if len(ranked) > 1 else 0.0
        # Valid CHOW history naturally has two same-address records. Not an ambiguity.
        if len(ranked) > 1 and str(ranked[1][1].get("chow_current_account") or "") == str(account_id(best) if best else ""):
            runnerup = 0.0
        # A renamed facility at the exact same street and ZIP is still a strong identity match.
        best_signals = candidate_score(loc, best)[1] if best is not None else {}
        if best is not None and best_score < 0.66 and best_signals.get("name_similarity", 0) > .89 and best_signals.get("city_exact"):
            matched_to_site.add(str(account_id(best)))
            proposals.append(proposal("investigate", loc, best, evidence={"reason":"Same name/city but different address; could be moved or stale CRM data", "score":best_score, "signals":best_signals}))
            continue
        if best is None or best_score < 0.66:
            proposals.append(proposal("create", loc, fields={"name":loc["name"], "billing_street":loc["address"],
              "billing_city":loc["city"], "billing_state":loc["state"], "billing_zip":loc["zip"],
              "parent_id":parent_id,"status":"Active"},
              evidence={"best_crm_score":best_score, "reason":"No sufficiently close CRM match"}))
            continue
        matched_to_site.add(str(account_id(best)))
        if runnerup > best_score - 0.09 and runnerup > 0.74:
            proposals.append(proposal("investigate", loc, best, evidence={"reason":"Two plausible CRM matches; manual resolution required", "best_score":best_score, "runner_up_score":runnerup}))
            continue
        exact_address_identity = (best_signals.get("street_similarity", 0) >= 0.98
                                  and best_signals.get("zip_exact") and best_signals.get("city_exact")
                                  and best_signals.get("state_exact"))
        if best_score < 0.82 and not exact_address_identity:
            proposals.append(proposal("investigate", loc, best, evidence={"reason":"Weak match; do not mutate automatically", "score":best_score}))
            continue
        if str(account_id(best)) in selected:
            proposals.append(proposal("investigate", loc, best, evidence={"reason":"One CRM account matches several website locations"}))
            continue
        selected.add(str(account_id(best)))
        old_parent = str(best.get("parent_id") or "")
        comparison = candidate_score(loc, best)[1]
        if old_parent != parent_id:
            if best.get("chow_current_account"):
                # Already CHOW'ed: do not repeatedly create a second replacement.
                continue
            if chow_required(best):
                proposals.append(proposal("chow", loc, best, evidence={"reason":"Revenue AND outstanding AR are positive: preserve old parent",
                  "score":best_score, "signals":comparison, "lifetime_revenue":best.get("lifetime_revenue"), "outstanding_ar":best.get("outstanding_ar")},
                  extra={"target_parent_id":parent_id}))
            else:
                fields = {"parent_id":parent_id}
                if norm(textval(best, "name")) != norm(loc["name"]):
                    fields["name"] = loc["name"]
                proposals.append(proposal("update", loc, best, fields=fields, evidence={"reason":"Re-parent directly (no revenue OR no outstanding AR)", "signals":comparison, "score":best_score}))
        elif norm(textval(best, "name")) != norm(loc["name"]):
            proposals.append(proposal("update", loc, best, fields={"name":loc["name"]},
              evidence={"reason":"Same address; likely outdated account name", "signals":comparison, "score":best_score}))

    # Conservative duplicate detection: exact normalized address+ZIP+parent only.
    # Do not mark a financially active account inactive or erase a CHOW historical copy.
    groups = {}
    for a in facility_accounts:
        key = (norm(textval(a, "address")), norm(textval(a, "zip")), str(a.get("parent_id") or ""))
        if key[0] and key[1]:
            groups.setdefault(key, []).append(a)
    for key, group in groups.items():
        if len(group) < 2:
            continue
        group.sort(key=lambda a: (money(a.get("lifetime_revenue")) > 0,
                                  money(a.get("outstanding_ar")) > 0,
                                  str(a.get("status", "")).lower() == "active",
                                  bool(a.get("name"))), reverse=True)
        winner = group[0]
        matched_to_site.update(str(account_id(a)) for a in group)
        for loser in group[1:]:
            if (str(loser.get("duplicate_of_account") or "") == str(account_id(winner))
                    and str(loser.get("status") or "").lower() == "inactive"):
                continue  # Already deactivated as a duplicate: no second proposal.
            if similarity(textval(loser, "name"), textval(winner, "name")) < .75:
                continue  # Two tenants could legitimately share one street address.
            context = next((l for l in locations if norm(l["address"]) == key[0] and norm(l["zip"]) == key[1]), None)
            context = context or {"name": textval(loser,"name"), "address": textval(loser,"address"),
                                  "source_url":"", "slug":f"crm-{account_id(loser)}"}
            if (money(loser.get("lifetime_revenue")) > 0 or money(loser.get("outstanding_ar")) > 0
                    or loser.get("chow_current_account")):
                proposals.append(proposal("investigate", context, loser, evidence={
                    "reason":"Potential duplicate, but losing account has billing history or a CHOW pointer. Preserve for manual investigation.",
                    "winner_account_id":account_id(winner)}))
            else:
                prior_note = str(loser.get("note") or "")
                fields = {"duplicate_of_account":account_id(winner), "status":"Inactive",
                          "note":(prior_note + " | " if prior_note else "") +
                                 f"Reconciliation: duplicate of account {account_id(winner)}; same street, ZIP and parent."}
                proposals.append(proposal("duplicate", context, loser, fields=fields, evidence={
                    "reason":"Likely duplicate: same normalized street, ZIP and parent; no billing balances on losing copy",
                    "winner_account_id":account_id(winner), "winner": winner}))

    # A CRM account absent from the official directory isn't proof of sale/disposition.
    for account in facility_accounts:
        aid = str(account_id(account))
        if aid in matched_to_site or str(account.get("parent_id") or "") != parent_id:
            continue
        # CHOW historical records must be retained for billing.
        if account.get("chow_current_account"):
            continue
        placeholder = {"name":textval(account, "name"), "slug":f"crm-{aid}", "source_url":"", "address":textval(account,"address")}
        proposals.append(proposal("investigate", placeholder, account, evidence={"reason":"Under Bellhaven in CRM, but absent from website; review before marking inactive"}))
    return proposals
