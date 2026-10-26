"""Account groups: several accounts shown as one tile in the console.

A group is a view. Merging stores which accounts go together; splitting
removes that and nothing else, because nothing else was ever merged.
"""
import pytest
from fastapi.testclient import TestClient

from gigamail.core import account_groups


@pytest.fixture(autouse=True)
def accounts(tmp_path, monkeypatch):
    """Four accounts, ids 1-4, and an empty groups database."""
    existing = [{"id": i, "name": f"acc{i}", "email": f"acc{i}@example.com"}
                for i in (1, 2, 3, 4)]
    monkeypatch.setattr(account_groups, "_db_path", lambda: str(tmp_path / "acc.db"))
    monkeypatch.setattr(account_groups.accounts, "get_accounts", lambda: list(existing))
    return existing


@pytest.fixture()
def client():
    from gigamail import http_api
    with TestClient(http_api.app) as c:
        yield c


def test_merging_two_accounts_makes_one_group():
    g = account_groups.merge(source_id=2, target_id=1)
    assert g["account_ids"] == [1, 2]                 # the target comes first
    assert account_groups.get_groups() == [g]
    assert account_groups.group_of(2) == g
    assert account_groups.group_of(3) is None


def test_a_third_account_joins_the_group():
    g = account_groups.merge(2, 1)
    assert account_groups.merge(3, 1) == {"id": g["id"], "account_ids": [1, 2, 3]}
    assert len(account_groups.get_groups()) == 1


def test_dropping_on_a_grouped_account_joins_its_group():
    g = account_groups.merge(2, 1)
    assert account_groups.merge(3, 2)["id"] == g["id"]
    assert account_groups.get_groups()[0]["account_ids"] == [1, 2, 3]


def test_two_groups_merge_into_the_target_one():
    a = account_groups.merge(2, 1)
    b = account_groups.merge(4, 3)
    merged = account_groups.merge(source_id=3, target_id=1)
    assert merged == {"id": a["id"], "account_ids": [1, 2, 3, 4]}
    assert [g["id"] for g in account_groups.get_groups()] == [a["id"]]
    assert b["id"] != a["id"]


def test_split_brings_back_the_single_accounts():
    g = account_groups.merge(2, 1)
    assert account_groups.split(g["id"])
    assert account_groups.get_groups() == []
    assert not account_groups.split(g["id"])           # already gone


@pytest.mark.parametrize("source,target", [(1, 1), (9, 1), (1, 9)])
def test_merges_that_make_no_sense_are_refused(source, target):
    with pytest.raises(ValueError):
        account_groups.merge(source, target)
    assert account_groups.get_groups() == []


def test_accounts_already_together_are_not_merged_twice():
    account_groups.merge(2, 1)
    with pytest.raises(ValueError):
        account_groups.merge(1, 2)


def test_a_deleted_account_leaves_its_group(accounts):
    account_groups.merge(2, 1)
    account_groups.merge(3, 1)
    accounts[:] = [a for a in accounts if a["id"] != 2]
    assert account_groups.get_groups()[0]["account_ids"] == [1, 3]
    accounts[:] = [a for a in accounts if a["id"] != 3]
    assert account_groups.get_groups() == []           # one account is no group


# ── the console API ──────────────────────────────────────────────────

def test_http_merge_list_and_split(client):
    r = client.post("/accounts/groups/merge", json={"source_id": 2, "target_id": 1})
    assert r.status_code == 200
    group = r.json()
    assert group["account_ids"] == [1, 2]
    assert client.get("/accounts/groups").json() == [group]
    assert client.delete(f"/accounts/groups/{group['id']}").json() == {"success": True}
    assert client.get("/accounts/groups").json() == []
    assert client.delete(f"/accounts/groups/{group['id']}").status_code == 404


def test_http_refuses_an_unknown_account(client):
    r = client.post("/accounts/groups/merge", json={"source_id": 9, "target_id": 1})
    assert r.status_code == 400


def test_groups_are_not_an_mcp_tool():
    """Groups are a console view: the agent keeps seeing separate accounts."""
    import inspect

    from gigamail import server
    assert "account_groups" not in inspect.getsource(server)
