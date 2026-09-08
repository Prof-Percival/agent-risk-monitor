"""The ingestion side: what the API accepts, refuses, and stores."""

import pytest

from conftest import AGENT_KEY, event


def test_readiness_reports_the_database(api):
    response = api.call("GET", "/health/ready")

    assert response.status == 200
    assert response.body == {"status": "ok"}


def test_liveness_needs_no_key(api):
    assert api.call("GET", "/health/live").status == 200


@pytest.mark.parametrize("key", [None, "not-a-real-key", ""])
def test_refuses_a_request_without_a_usable_key(api, agent_id, key):
    response = api.post_event(event(agent_id, "file_read", {"path": "/tmp/x"}), key=key)

    assert response.status == 401
    assert response.body == {"error": "unauthorized"}


def test_accepts_a_valid_event(api, agent_id):
    response = api.post_event(event(agent_id, "file_read", {"path": "/tmp/notes.txt"}))

    assert response.status == 202
    assert response.body["result"] == "stored"


def test_reposting_the_same_event_is_a_duplicate_not_an_error(api, agent_id):
    submitted = event(agent_id, "file_read", {"path": "/tmp/notes.txt"})

    first = api.post_event(submitted)
    second = api.post_event(submitted)

    assert first.body["result"] == "stored"
    assert second.status == 202
    assert second.body["result"] == "duplicate"


@pytest.mark.parametrize("missing", ["event_id", "agent_id", "timestamp", "type", "payload"])
def test_refuses_an_event_missing_a_required_field(api, agent_id, missing):
    submitted = event(agent_id, "file_read", {"path": "/tmp/x"})
    del submitted[missing]

    response = api.post_event(submitted)

    assert response.status == 400
    assert response.body["error"] == "invalid event"


def test_refuses_a_timestamp_with_no_offset(api, agent_id):
    submitted = event(agent_id, "file_read", {"path": "/tmp/x"})
    submitted["timestamp"] = "2026-09-08 10:15"

    assert api.post_event(submitted).status == 400


def test_a_batch_reports_each_item_separately(api, agent_id):
    good = event(agent_id, "file_read", {"path": "/tmp/a.txt"})
    bad = event(agent_id, "file_read", {"path": "/tmp/b.txt"})
    del bad["type"]

    response = api.post_batch([good, bad])

    assert response.status == 202
    assert response.body["submitted"] == 2
    assert response.body["accepted"] == 1
    assert response.body["rejected"] == 1
    assert response.body["results"][0]["accepted"] is True
    assert response.body["results"][1]["accepted"] is False


def test_one_bad_item_does_not_lose_the_rest_of_the_batch(api, agent_id):
    broken = event(agent_id, "file_read", {"path": "/tmp/broken.txt"})
    del broken["payload"]
    events = [
        event(agent_id, "file_read", {"path": "/tmp/1.txt"}),
        broken,
        event(agent_id, "file_read", {"path": "/tmp/2.txt"}),
    ]

    response = api.post_batch(events)

    assert response.body["accepted"] == 2
    assert [item["accepted"] for item in response.body["results"]] == [True, False, True]


@pytest.mark.parametrize(
    ("hours", "limit"),
    [(0, 100), (-1, 100), (721, 100), (24, 0), (24, 501)],
)
def test_refuses_a_window_or_page_outside_the_allowed_range(api, hours, limit):
    response = api.alerts(hours=hours, limit=limit)

    assert response.status == 400


def test_an_agent_with_no_events_reports_an_empty_summary(api, agent_id):
    response = api.summary(agent_id)

    assert response.status == 200
    assert response.body["agent_id"] == agent_id
    assert response.body["total_alerts"] == 0
    assert response.body["total_events"] == 0


def test_the_agent_key_may_read_as_well_as_write(api, agent_id):
    assert api.alerts(agent_id=agent_id, key=AGENT_KEY).status == 200
