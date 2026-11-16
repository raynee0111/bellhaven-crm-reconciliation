"""Regression tests based on the actual CRM field names from read-only inspection."""
import json
from crm import CRM
from matching import build_proposals, candidate_score, chow_required
from review_actions import commit, ReviewBlocked

LOC = {"name":"Bellhaven of Maplewood", "address":"210 Orchard Lane", "city":"Maplewood", "state":"OH", "zip":"44280", "care_offerings":["Assisted Living"], "slug":"maplewood", "source_url":"https://example.com/maplewood"}
REAL = {"account_id":"001OLD", "name":LOC["name"], "billing_street":LOC["address"], "billing_city":LOC["city"], "billing_state":LOC["state"], "billing_zip":LOC["zip"], "parent_id":"001OTHER", "lifetime_revenue":12000, "outstanding_ar":300, "status":"Active", "chow_current_account":None, "duplicate_of_account":None}


def test_real_fields_score_exact():
    score, signals = candidate_score(LOC, REAL)
    assert score == 1
    assert signals["zip_exact"]


def test_real_chow_id_and_fields():
    proposals=build_proposals([LOC],[REAL],"001BELL")
    assert [p["kind"] for p in proposals] == ["chow"]
    assert proposals[0]["payload"]["account_id"] == "001OLD"


def test_real_reparent_when_no_ar():
    p = build_proposals([LOC],[{**REAL,"outstanding_ar":0}],"001BELL")[0]
    assert p["kind"] == "update"
    assert p["payload"]["fields"] == {"parent_id":"001BELL"}


def test_real_create_has_real_address_fields():
    p = build_proposals([LOC],[],"001BELL")[0]
    assert p["kind"] == "create"
    assert p["payload"]["fields"]["billing_street"] == LOC["address"]
    assert "care_offerings" not in p["payload"]["fields"]


def test_pagination_fetches_all_three_pages():
    c = CRM(token="IN_MEMORY_DUMMY_TOKEN")
    called = []
    def fake_request(method, path):
        called.append(path)
        page = int(path.split("page=")[1].split("&")[0])
        start = (page-1)*50
        data = [{"account_id":f"A{i}"} for i in range(start,min(121,start+50))]
        return {"data":data,"page":page,"page_size":50,"total":121}
    c.request = fake_request
    records = c.accounts()
    assert len(records) == 121
    assert len({x["account_id"] for x in records}) == 121
    assert len(called) == 3


def test_approve_direct_reparent_rechecks_chow():
    item={"state":"pending","kind":"update","payload":json.dumps({"account_id":"001OLD","location":LOC,"fields":{"parent_id":"001BELL"}}),"evidence":"{}"}
    class CRMFake:
        def get(self, account_id): return REAL
        def patch(self, *args): raise AssertionError("must not patch CHOW account")
    try:
        commit(item,CRMFake(),lambda *_:None)
    except ReviewBlocked as e:
        assert "CHOW" in str(e)
    else:
        assert False,"must block direct re-parent"
