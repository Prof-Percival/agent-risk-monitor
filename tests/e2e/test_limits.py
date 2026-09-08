"""The two constraints the brief states about request handling.

Bodies may be up to a few hundred kilobytes, and the service must not hang indefinitely on a slow or
malformed request. Neither is visible to a unit test, as both are properties of the running server.
"""

import socket
import time

from conftest import AGENT_KEY, BASE_URL, event

KILOBYTE = 1024


def test_accepts_a_few_hundred_kilobytes(api, agent_id):
    padded = event(agent_id, "http_request", {"url": "https://api.openai.com/v1/chat"})
    padded["payload"]["blob"] = "x" * (300 * KILOBYTE)

    response = api.post_event(padded)

    assert response.status == 202
    assert response.body["result"] == "stored"


def test_refuses_a_body_past_the_limit(api, agent_id):
    oversized = event(agent_id, "http_request", {"url": "https://api.openai.com/v1/chat"})
    oversized["payload"]["blob"] = "x" * (600 * KILOBYTE)

    assert api.post_event(oversized).status == 413


def test_a_client_that_declares_a_body_then_stalls_is_cut_off():
    """A socket that goes quiet mid body must be closed, not held open.

    requestTimeout alone does not do this: Node sweeps for expired requests on an interval, so the
    per socket connectionTimeout is what ends it.
    """
    host, _, port = BASE_URL.removeprefix("http://").partition(":")
    body = b'{"event_id":"stall","agent_id":"a","timestamp":"2026-01-01T00:00:00Z","type":"x"'

    request = (
        b"POST /v1/events HTTP/1.1\r\n"
        b"Host: " + host.encode() + b"\r\n"
        b"Content-Type: application/json\r\n"
        b"X-Api-Key: " + AGENT_KEY.encode() + b"\r\n"
        b"Content-Length: " + str(len(body) + 5000).encode() + b"\r\n"
        b"\r\n" + body
    )

    sock = socket.create_connection((host, int(port or 80)), timeout=60)
    started = time.monotonic()

    try:
        sock.sendall(request)
        sock.settimeout(60)
        sock.recv(4096)
        elapsed = time.monotonic() - started
    except TimeoutError:
        raise AssertionError("the stalled request was never closed") from None
    finally:
        sock.close()

    assert elapsed < 45, f"took {elapsed:.1f}s to give up on a stalled client"
