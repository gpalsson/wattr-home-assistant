from datetime import datetime, timedelta
from types import MappingProxyType, SimpleNamespace
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import pytest
import voluptuous as vol
from aiohttp import ClientSession
from aioresponses import aioresponses
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from custom_components.wattr import async_setup
from custom_components.wattr.api import WattrApi, WattrAuthError, WattrError
from custom_components.wattr.const import API_URL
from custom_components.wattr.history import history_date


def day(days=0):
    return (
        datetime.now(ZoneInfo("Europe/Copenhagen")).date() - timedelta(days=days)
    ).isoformat()


def history(tokens, count=96):
    return {
        "api_version": 1,
        "account_id": tokens["account_id"],
        "installation_id": "test-home",
        "date": day(1),
        "timezone": "Europe/Copenhagen",
        "intervals": [{"grid_import_kwh": None, "battery_charge_kwh": 0}] * count,
    }


def entry(hass, tokens, response):
    result = ConfigEntry(
        domain="wattr",
        data=tokens,
        title="Wattr",
        source="user",
        unique_id=tokens["account_id"],
        version=1,
        minor_version=1,
        options={},
        discovery_keys=MappingProxyType({}),
        subentries_data=[],
        state=ConfigEntryState.LOADED,
    )
    result.runtime_data = SimpleNamespace(
        installation=lambda id: {} if id == "test-home" else None,
        api=SimpleNamespace(history=AsyncMock(return_value=response)),
    )
    hass.config_entries._entries[result.entry_id] = result
    return result


async def test_history_response_uses_bearer_and_preserves_nulls(tokens):
    response = history(tokens)
    with aioresponses() as mock:
        mock.get(
            API_URL + "/history?installation_id=test-home&date=" + day(1),
            payload=response,
        )
        async with ClientSession() as session:
            assert (
                await WattrApi(session, tokens).history("test-home", day(1)) == response
            )
        assert next(iter(mock.requests.values()))[0].kwargs["headers"] == {
            "Authorization": "Bearer test-access"
        }


@pytest.mark.parametrize(
    "changes",
    [
        {"installation_id": "other"},
        {"date": "2000-01-01"},
        {"account_id": "other"},
        {"intervals": [{}] * 101},
    ],
)
async def test_history_response_must_match_request(tokens, changes):
    response = history(tokens) | changes
    with aioresponses() as mock:
        mock.get(
            API_URL + "/history?installation_id=test-home&date=" + day(1),
            payload=response,
        )
        async with ClientSession() as session:
            with pytest.raises(WattrError):
                await WattrApi(session, tokens).history("test-home", day(1))


@pytest.mark.parametrize("count", [92, 96, 100])
async def test_dst_day_lengths_are_accepted(tokens, count):
    response = history(tokens, count)
    with aioresponses() as mock:
        mock.get(
            API_URL + "/history?installation_id=test-home&date=" + day(1),
            payload=response,
        )
        async with ClientSession() as session:
            assert (
                len(
                    (await WattrApi(session, tokens).history("test-home", day(1)))[
                        "intervals"
                    ]
                )
                == count
            )


def test_window_and_strict_date():
    assert history_date(day(30)) == day(30)
    assert history_date(day()) == day()
    for invalid in [day(31), day(-1), "20261013", "bad", "2026-13-01"]:
        with pytest.raises(vol.Invalid):
            history_date(invalid)


async def test_history_service_returns_data_without_recorder_writes(hass, tokens):
    response = history(tokens)
    e = entry(hass, tokens, response)
    assert await async_setup(hass, {})
    result = await hass.services.async_call(
        "wattr",
        "get_history",
        {"installation_id": "test-home", "date": day(1)},
        blocking=True,
        return_response=True,
    )
    assert result == response
    e.runtime_data.api.history.assert_awaited_once_with("test-home", day(1))
    assert hass.states.async_all() == []


async def test_history_unowned_or_unloaded_rejected_before_http(hass, tokens):
    e = entry(hass, tokens, history(tokens))
    await async_setup(hass, {})
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "wattr",
            "get_history",
            {"installation_id": "other-home", "date": day(1)},
            blocking=True,
            return_response=True,
        )
    e.runtime_data.api.history.assert_not_awaited()


async def test_history_error_is_bounded_and_revocation_starts_reauth(hass, tokens):
    e = entry(hass, tokens, history(tokens))
    e.runtime_data.api.history.side_effect = WattrAuthError("Connection revoked")
    await async_setup(hass, {})
    with patch.object(ConfigEntry, "async_start_reauth") as reauth:
        with pytest.raises(HomeAssistantError, match="Reconnect Wattr"):
            await hass.services.async_call(
                "wattr",
                "get_history",
                {"installation_id": "test-home", "date": day(1)},
                blocking=True,
                return_response=True,
            )
        reauth.assert_called_once_with(hass)


async def test_multiple_account_entry_selection(hass, tokens):
    first = entry(hass, tokens, history(tokens))
    second = entry(hass, tokens | {"account_id": "second"}, history(tokens))
    await async_setup(hass, {})
    with pytest.raises(ServiceValidationError, match="config_entry_id"):
        await hass.services.async_call(
            "wattr",
            "get_history",
            {"installation_id": "test-home", "date": day(1)},
            blocking=True,
            return_response=True,
        )
    await hass.services.async_call(
        "wattr",
        "get_history",
        {
            "installation_id": "test-home",
            "date": day(1),
            "config_entry_id": first.entry_id,
        },
        blocking=True,
        return_response=True,
    )
    second.runtime_data.api.history.assert_not_awaited()
