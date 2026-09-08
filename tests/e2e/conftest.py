"""Fixtures for the end to end tests.

These run against a stack that is already up. They talk to it only over HTTP, the way a caller
would, so nothing here reaches into the database or either service.
"""

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

BASE_URL = os.environ.get("E2E_BASE_URL", "http://localhost:8080")
AGENT_KEY = os.environ.get("E2E_AGENT_KEY", "dev-agent-key-0000000001")
DASHBOARD_KEY = os.environ.get("E2E_DASHBOARD_KEY", "dev-dashboard-key-000001")

# The analyzer polls on an interval, so an alert is never instant. This is the ceiling, not a sleep.
ALERT_TIMEOUT_SECONDS = float(os.environ.get("E2E_ALERT_TIMEOUT", "60"))


@dataclass(frozen=True)
class Response:
    status: int
    body: dict


class Api:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url

    def call(
        self,
        method: str,
        path: str,
        *,
        body: dict | None = None,
        key: str | None = None,
    ) -> Response:
        payload = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(f"{self.base_url}{path}", data=payload, method=method)

        if payload is not None:
            request.add_header("Content-Type", "application/json")
        if key is not None:
            request.add_header("X-Api-Key", key)

        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                raw = response.read()
                return Response(response.status, json.loads(raw) if raw else {})
        except urllib.error.HTTPError as error:
            raw = error.read()
            return Response(error.code, json.loads(raw) if raw else {})

    def post_event(self, event: dict, *, key: str | None = AGENT_KEY) -> Response:
        return self.call("POST", "/v1/events", body=event, key=key)

    def post_batch(self, events: list[dict], *, key: str | None = AGENT_KEY) -> Response:
        return self.call("POST", "/v1/events/batch", body={"events": events}, key=key)

    def alerts(self, *, key: str | None = DASHBOARD_KEY, **filters: object) -> Response:
        query = urllib.parse.urlencode({k: v for k, v in filters.items() if v is not None})
        return self.call("GET", f"/v1/alerts?{query}", key=key)

    def summary(self, agent_id: str, *, hours: int = 24) -> Response:
        return self.call(
            "GET", f"/v1/agents/{agent_id}/summary?hours={hours}", key=DASHBOARD_KEY
        )

    def timeline(self, agent_id: str, *, hours: int = 24, limit: int = 100) -> Response:
        return self.call(
            "GET",
            f"/v1/agents/{agent_id}/timeline?hours={hours}&limit={limit}",
            key=DASHBOARD_KEY,
        )

    def await_alerts(
        self,
        agent_id: str,
        *,
        rule: str | None = None,
        minimum: int = 1,
        timeout: float = ALERT_TIMEOUT_SECONDS,
    ) -> list[dict]:
        """Polls until at least `minimum` alerts match, then returns them. Fails on timeout."""
        deadline = time.monotonic() + timeout
        found: list[dict] = []

        while time.monotonic() < deadline:
            response = self.alerts(agent_id=agent_id, rule=rule, limit=500)
            if response.status == 200:
                found = response.body["alerts"]
                if len(found) >= minimum:
                    return found
            time.sleep(1)

        pytest.fail(
            f"expected at least {minimum} alert(s) for {agent_id}"
            f"{f' on rule {rule}' if rule else ''} within {timeout:.0f}s, saw {len(found)}"
        )

    def assert_stays_quiet(self, agent_id: str, *, seconds: float = 15) -> None:
        """Proves an event raised nothing, which needs a wait rather than a single look."""
        deadline = time.monotonic() + seconds

        while time.monotonic() < deadline:
            response = self.alerts(agent_id=agent_id, limit=500)
            assert response.status == 200
            raised = response.body["alerts"]
            assert raised == [], (
                f"expected no alerts for {agent_id}, got {[a['rule'] for a in raised]}"
            )
            time.sleep(1)


@pytest.fixture(scope="session")
def api() -> Api:
    client = Api(BASE_URL)
    deadline = time.monotonic() + 90

    while time.monotonic() < deadline:
        try:
            if client.call("GET", "/health/ready").status == 200:
                return client
        except OSError:
            pass
        time.sleep(1)

    pytest.fail(f"{BASE_URL} never became ready. Is the stack up?")


@pytest.fixture
def agent_id() -> str:
    """A fresh agent per test, so one test's events cannot satisfy another's assertions."""
    return f"e2e-{uuid.uuid4().hex[:12]}"


def event(agent_id: str, event_type: str, payload: dict, *, event_id: str | None = None) -> dict:
    return {
        "event_id": event_id or f"evt-{uuid.uuid4().hex}",
        "agent_id": agent_id,
        "timestamp": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "type": event_type,
        "payload": payload,
    }
