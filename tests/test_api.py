import asyncio
import time

import pytest
from aiohttp import ClientSession
from aioresponses import aioresponses

from custom_components.wattr.api import (
    DeviceFlowError,
    WattrApi,
    WattrAuthError,
    WattrError,
)
from custom_components.wattr.const import API_URL


async def test_snapshot_bearer_and_no_refresh(tokens, snapshot):
    with aioresponses() as mock:
        mock.get(API_URL + "/snapshot", payload=snapshot)
        async with ClientSession() as session:
            api = WattrApi(session, tokens)
            assert await api.snapshot() == snapshot
        request = next(iter(mock.requests.values()))[0]
        assert request.kwargs["headers"] == {"Authorization": "Bearer test-access"}
        assert request.kwargs["allow_redirects"] is False


async def test_serialized_refresh_persisted_before_use(
    tokens, token_response, snapshot
):
    tokens["expires_at"] = 0
    saved = []
    with aioresponses() as mock:
        mock.post(API_URL + "/auth/token", payload=token_response)
        mock.get(API_URL + "/snapshot", payload=snapshot, repeat=True)
        async with ClientSession() as session:
            api = WattrApi(session, tokens, lambda data: saved.append(dict(data)))
            results = await asyncio.gather(
                api.snapshot(), api.snapshot(), api.snapshot()
            )
            assert all(result == snapshot for result in results)
            assert len(saved) == 1
            assert saved[0]["refresh_token"] == "rotated-refresh"
            assert api.tokens == saved[0]
        calls = [
            v for k, v in mock.requests.items() if str(k[1]).endswith("/auth/token")
        ]
        assert len(calls[0]) == 1


async def test_access_rejection_refreshes_once(tokens, token_response, snapshot):
    with aioresponses() as mock:
        mock.get(API_URL + "/snapshot", status=401, payload={"error": "unauthorized"})
        mock.post(API_URL + "/auth/token", payload=token_response)
        mock.get(API_URL + "/snapshot", payload=snapshot)
        async with ClientSession() as session:
            api = WattrApi(session, tokens)
            assert await api.snapshot() == snapshot
            assert api.tokens["access_token"] == "rotated-access"


async def test_revocation_requests_reauth(tokens):
    tokens["expires_at"] = 0
    with aioresponses() as mock:
        mock.post(
            API_URL + "/auth/token",
            status=400,
            payload={"error": "invalid_grant", "secret": "must-not-leak"},
        )
        async with ClientSession() as session:
            with pytest.raises(WattrAuthError) as error:
                await WattrApi(session, tokens).snapshot()
            assert "must-not-leak" not in str(error.value)


@pytest.mark.parametrize(
    "code", ["authorization_pending", "slow_down", "access_denied", "expired_token"]
)
async def test_device_flow_errors_are_classified(code):
    with aioresponses() as mock:
        mock.post(API_URL + "/auth/token", status=400, payload={"error": code})
        async with ClientSession() as session:
            with pytest.raises(DeviceFlowError) as error:
                await WattrApi(session).device_token("test-device-code")
            assert error.value.code == code


@pytest.mark.parametrize(
    "bad",
    [
        {"account_id": "other"},
        {"scope": "read control"},
        {"expires_in": True},
        {"refresh_token": ""},
    ],
)
async def test_bad_rotation_never_persisted(tokens, token_response, bad):
    tokens["expires_at"] = 0
    saved = []
    with aioresponses() as mock:
        mock.post(API_URL + "/auth/token", payload=token_response | bad)
        async with ClientSession() as session:
            with pytest.raises(WattrError):
                await WattrApi(session, tokens, saved.append).refresh()
            assert saved == []


async def test_account_mismatch_rejected(tokens, snapshot):
    snapshot["account_id"] = "other"
    with aioresponses() as mock:
        mock.get(API_URL + "/snapshot", payload=snapshot)
        async with ClientSession() as session:
            with pytest.raises(WattrAuthError):
                await WattrApi(session, tokens).snapshot()


async def test_timeout_and_server_details_do_not_leak(tokens):
    with aioresponses() as mock:
        mock.get(API_URL + "/snapshot", status=500, payload={"secret": "private"})
        async with ClientSession() as session:
            with pytest.raises(WattrError) as error:
                await WattrApi(session, tokens).snapshot()
            assert str(error.value) == "API HTTP 500"


async def test_refresh_after_other_call_rotated_is_skipped(tokens, token_response):
    tokens["expires_at"] = 0
    with aioresponses() as mock:
        mock.post(API_URL + "/auth/token", payload=token_response)
        async with ClientSession() as session:
            api = WattrApi(session, tokens)
            await api.refresh()
            await api.refresh(rejected_access="test-access")
            assert api.tokens["expires_at"] > time.time()


async def test_redirect_not_followed():
    with aioresponses() as mock:
        mock.post(
            API_URL + "/auth/device",
            status=302,
            payload={},
            headers={"Location": "https://other.example"},
        )
        async with ClientSession() as session:
            with pytest.raises(WattrError):
                await WattrApi(session).start_device_flow()


async def test_streamed_response_waits_for_eof(tokens, snapshot):
    import json

    from aiohttp import web

    async def serve(request):
        response = web.StreamResponse(headers={"Content-Type": "application/json"})
        await response.prepare(request)
        raw = json.dumps(snapshot).encode()
        await response.write(raw[:15])
        await asyncio.sleep(0.01)
        await response.write(raw[15:])
        await response.write_eof()
        return response

    app = web.Application()
    app.router.add_get("/snapshot", serve)
    runner = web.AppRunner(app)
    await runner.setup()
    server = web.TCPSite(runner, "127.0.0.1", 0)
    await server.start()
    port = server._server.sockets[0].getsockname()[1]
    try:
        async with ClientSession() as session:
            assert (
                await WattrApi(
                    session, tokens, base_url=f"http://127.0.0.1:{port}"
                ).snapshot()
                == snapshot
            )
    finally:
        await runner.cleanup()
