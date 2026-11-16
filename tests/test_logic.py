from matching import build_proposals, chow_required, candidate_score

LOC = {"name":"Bellhaven of Maplewood", "address":"210 Orchard Lane", "city":"Maplewood", "state":"OH", "zip":"44280", "care_offerings":["Assisted Living"], "slug":"bellhaven-of-maplewood", "source_url":"https://example.com/bellhaven-of-maplewood"}
OLD = {"id":42, "name":"Bellhaven of Maplewood", "address":"210 Orchard Lane", "city":"Maplewood", "state":"OH", "zip":"44280", "parent_id":100, "lifetime_revenue":10000, "outstanding_ar":300, "status":"Active"}

def test_chow_requires_both_balances_positive():
    assert chow_required(OLD)
    assert not chow_required({**OLD, "outstanding_ar":0})
    assert not chow_required({**OLD, "lifetime_revenue":0})

def test_chow_never_directly_reparents():
    proposals = build_proposals([LOC], [OLD], 900)
    assert [p["kind"] for p in proposals] == ["chow"]
    assert not proposals[0]["payload"]["fields"].get("parent_id")

def test_no_ar_means_reparent():
    proposals = build_proposals([LOC], [{**OLD,"outstanding_ar":0}], 900)
    assert proposals[0]["kind"] == "update"
    assert proposals[0]["payload"]["fields"]["parent_id"] == "900"

def test_stable_proposal_key():
    p1 = build_proposals([LOC], [{**OLD,"outstanding_ar":0}], 900)[0]
    p2 = build_proposals([LOC], [{**OLD,"outstanding_ar":0}], 900)[0]
    assert p1["dedupe_key"] == p2["dedupe_key"]

def test_exact_address_high_confidence():
    score, why = candidate_score(LOC, OLD)
    assert score == 1.0 and why["zip_exact"]


def test_exact_address_can_identify_renamed_facility():
    former = {**OLD, "name":"Completely Different Brand", "parent_id":900}
    proposals = build_proposals([LOC], [former], 900)
    assert proposals and proposals[0]["kind"] == "update"
    assert proposals[0]["payload"]["fields"]["name"] == LOC["name"]


def test_safe_duplicate_is_proposed():
    two = [{**OLD, "id": 42, "parent_id":900, "lifetime_revenue":2000, "outstanding_ar":0},
           {**OLD, "id": 43, "parent_id":900, "lifetime_revenue":0, "outstanding_ar":0}]
    proposals = build_proposals([LOC], two, 900)
    duplicates = [p for p in proposals if p["kind"] == "duplicate"]
    assert len(duplicates) == 1
    assert duplicates[0]["payload"]["account_id"] == 43
    assert duplicates[0]["payload"]["fields"]["duplicate_of_account"] == 42


def test_chow_rerun_does_not_repropose():
    historical = {**OLD, "id":42, "chow_current_account":99}
    current = {**OLD, "id":99, "parent_id":900, "lifetime_revenue":0, "outstanding_ar":0}
    proposals = build_proposals([LOC], [historical, current], 900)
    assert not [p for p in proposals if p["kind"] in ("chow", "create", "update")]


def test_new_website_change_gets_new_decision_key():
    a = {**OLD, "parent_id":900, "name":"Legacy Facility"}
    p1 = build_proposals([LOC], [a], 900)[0]
    p2 = build_proposals([{**LOC, "name":"Bellhaven Maplewood New"}], [a], 900)[0]
    assert p1["dedupe_key"] != p2["dedupe_key"]
