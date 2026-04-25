"""Tests for AgamemnonClient HTTP interactions."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from telemachy.agamemnon_client import AgamemnonClient, AgamemnonError
from telemachy.models import AgentSpec


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_response(status_code: int, body: object) -> MagicMock:
    """Return a mock httpx.Response-like object."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.is_error = status_code >= 400
    resp.json.return_value = body
    resp.text = str(body)
    return resp


def _local_agent_spec(name: str = "worker") -> AgentSpec:
    return AgentSpec(name=name, runtime="local")


async def _enter_client(url: str = "http://localhost:8080", **kwargs: object) -> AgamemnonClient:
    """Return an AgamemnonClient that has been entered as async context manager."""
    client = AgamemnonClient(url=url, **kwargs)  # type: ignore[arg-type]
    # Manually install a real-ish AsyncClient so _http property works
    import httpx
    client._client = httpx.AsyncClient(base_url=url)
    return client


# ---------------------------------------------------------------------------
# TEST 1 — create_agent returns agent ID on success
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_agent_returns_agent_id() -> None:
    client = await _enter_client()
    ok_resp = _make_response(201, {"agent": {"id": "agent-123"}})

    with patch.object(client._client, "request", new_callable=AsyncMock, return_value=ok_resp):
        agent_id = await client.create_agent(_local_agent_spec())

    assert agent_id == "agent-123"


# ---------------------------------------------------------------------------
# TEST 2 — create_agent raises AgamemnonError on 4xx
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_agent_raises_on_4xx() -> None:
    client = await _enter_client()
    err_resp = _make_response(400, {"detail": "bad request"})
    err_resp.json.return_value = {"detail": "bad request"}

    with patch.object(client._client, "request", new_callable=AsyncMock, return_value=err_resp):
        with pytest.raises(AgamemnonError) as exc_info:
            await client.create_agent(_local_agent_spec())

    assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# TEST 3 — create_agent raises AgamemnonError on malformed response
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_agent_raises_on_malformed_response() -> None:
    """Response missing 'agent.id' key should raise AgamemnonError."""
    client = await _enter_client()
    # Response is 201 OK but body has unexpected shape
    bad_resp = _make_response(201, {"result": "ok"})

    with patch.object(client._client, "request", new_callable=AsyncMock, return_value=bad_resp):
        with pytest.raises(AgamemnonError) as exc_info:
            await client.create_agent(_local_agent_spec())

    # Error should reference the missing key
    assert "agent" in str(exc_info.value).lower() or exc_info.value.status_code == 0


# ---------------------------------------------------------------------------
# TEST 4 — retry on 503: two failures then success
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_agent_retries_on_503() -> None:
    client = await _enter_client()
    fail_resp = _make_response(503, {"detail": "service unavailable"})
    ok_resp = _make_response(201, {"agent": {"id": "retry-id"}})

    # 503, 503, then 201
    mock_request = AsyncMock(side_effect=[fail_resp, fail_resp, ok_resp])

    with patch.object(client._client, "request", mock_request):
        # Patch asyncio.sleep so the test doesn't actually wait
        with patch("telemachy.agamemnon_client.asyncio.sleep", new_callable=AsyncMock):
            agent_id = await client.create_agent(_local_agent_spec())

    assert agent_id == "retry-id"
    assert mock_request.call_count == 3


# ---------------------------------------------------------------------------
# TEST 5 — start_agent calls correct endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_agent_calls_correct_endpoint() -> None:
    client = await _enter_client()
    ok_resp = _make_response(200, {})
    ok_resp.is_error = False

    mock_request = AsyncMock(return_value=ok_resp)
    with patch.object(client._client, "request", mock_request):
        await client.wake_agent("agent-123")

    mock_request.assert_called_once()
    call_args = mock_request.call_args
    assert call_args[0][0] == "POST"
    assert "/v1/agents/agent-123/start" in call_args[0][1]


# ---------------------------------------------------------------------------
# TEST 6 — delete_agent calls correct endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_agent_calls_correct_endpoint() -> None:
    client = await _enter_client()
    ok_resp = _make_response(204, {})
    ok_resp.is_error = False

    mock_request = AsyncMock(return_value=ok_resp)
    with patch.object(client._client, "request", mock_request):
        await client.delete_agent("agent-123")

    mock_request.assert_called_once()
    call_args = mock_request.call_args
    assert call_args[0][0] == "DELETE"
    assert "/v1/agents/agent-123" in call_args[0][1]


# ---------------------------------------------------------------------------
# TEST 7 — TLS enforcement raises on http:// when require_tls=True
# ---------------------------------------------------------------------------


def test_tls_enforcement_raises_on_http_url() -> None:
    """AgamemnonClient with require_tls=True and http:// URL must raise AgamemnonError."""
    with pytest.raises(AgamemnonError) as exc_info:
        AgamemnonClient(
            url="http://localhost:8080",
            require_tls=True,
        )

    assert exc_info.value.status_code == 0
    assert "TLS" in str(exc_info.value) or "https" in str(exc_info.value).lower()
