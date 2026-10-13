import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant import loader
from homeassistant.config_entries import ConfigEntries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.wattr.api import DeviceFlowError
from custom_components.wattr.config_flow import WattrConfigFlow


@pytest.fixture
async def hass(tmp_path):
    config = tmp_path / "config"
    (config / "custom_components").mkdir(parents=True)
    (config / "custom_components" / "wattr").symlink_to(
        Path(__file__).resolve().parents[1] / "custom_components" / "wattr",
        target_is_directory=True,
    )
    hass = HomeAssistant(str(config))
    loader.async_setup(hass)
    from homeassistant.helpers import frame

    frame.async_setup(hass)
    hass.config_entries = ConfigEntries(hass, {})
    await hass.config_entries.async_initialize()
    with patch(
        "custom_components.wattr.config_flow.async_get_clientsession",
        return_value=Mock(),
    ):
        yield hass
    await hass.async_stop(force=True)


def device():
    return {
        "device_code": "test-device",
        "user_code": "TEST1234",
        "verification_uri_complete": "https://wattr.dk/portal/home-assistant?code=TEST1234",
        "expires_in": 600,
        "interval": 5,
    }


async def test_real_flow_manager_approve_and_store(hass, token_response):
    from custom_components.wattr.api import WattrApi

    credentials = WattrApi.parse_tokens(token_response)
    with (
        patch(
            "custom_components.wattr.config_flow.WattrApi.start_device_flow",
            AsyncMock(return_value=device()),
        ),
        patch(
            "custom_components.wattr.config_flow.WattrApi.device_token",
            AsyncMock(return_value=credentials),
        ),
        patch(
            "custom_components.wattr.async_setup_entry", AsyncMock(return_value=True)
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            "wattr", context={"source": "user"}
        )
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "approve"
        assert "test-device" not in str(result)
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
        assert result["type"] in (
            FlowResultType.SHOW_PROGRESS,
            FlowResultType.CREATE_ENTRY,
        )
        await asyncio.sleep(0)
        await hass.async_block_till_done()
        # A completed progress task advances through finish automatically.
        entries = hass.config_entries.async_entries("wattr")
        if not entries:
            progresses = hass.config_entries.flow.async_progress()
            result = await hass.config_entries.flow.async_configure(
                progresses[0]["flow_id"]
            )
            if result["type"] == FlowResultType.SHOW_PROGRESS_DONE:
                result = await hass.config_entries.flow.async_configure(
                    result["flow_id"]
                )
            entries = hass.config_entries.async_entries("wattr")
        assert len(entries) == 1
        assert entries[0].unique_id == "test-account"
        assert entries[0].data["refresh_token"] == "rotated-refresh"
        assert "password" not in entries[0].data


async def test_slow_down_waits_longer_then_succeeds(hass, token_response):
    from custom_components.wattr.api import WattrApi

    flow = WattrConfigFlow()
    flow.hass = hass
    flow._device = device()
    flow._deadline = __import__("time").monotonic() + 600
    flow._api = AsyncMock()
    credentials = WattrApi.parse_tokens(token_response)
    flow._api.device_token.side_effect = [
        DeviceFlowError("slow_down"),
        DeviceFlowError("authorization_pending"),
        credentials,
    ]
    with patch(
        "custom_components.wattr.config_flow.asyncio.sleep", AsyncMock()
    ) as sleep:
        assert await flow._poll() == credentials
    assert [call.args[0] for call in sleep.call_args_list] == [10, 10]


async def test_denial_and_expiry_finish_cleanly(hass):
    flow = WattrConfigFlow()
    flow.hass = hass
    flow.flow_id = "test"
    flow.handler = "wattr"
    flow._task = asyncio.create_task(
        AsyncMock(side_effect=DeviceFlowError("access_denied"))()
    )
    await asyncio.sleep(0)
    result = await flow.async_step_finish()
    assert result["reason"] == "access_denied"


async def test_wrong_account_reauth_does_not_replace_connection(hass, token_response):
    from custom_components.wattr.api import WattrApi

    flow = WattrConfigFlow()
    flow.hass = hass
    flow.flow_id = "test"
    flow.handler = "wattr"
    flow._reauth_entry = type("Entry", (), {"unique_id": "original"})()
    flow._task = asyncio.create_task(
        AsyncMock(return_value=WattrApi.parse_tokens(token_response))()
    )
    await asyncio.sleep(0)
    with patch.object(flow, "_revoke_unused", AsyncMock()) as revoke:
        result = await flow.async_step_finish()
        assert result["reason"] == "wrong_account"
        revoke.assert_awaited_once()


async def test_actual_platform_setup_and_recovery(hass, tokens, snapshot):
    from types import MappingProxyType

    from homeassistant.config_entries import ConfigEntry, ConfigEntryState
    from homeassistant.helpers import device_registry, entity_registry

    from custom_components.wattr import async_setup_entry, async_unload_entry
    from custom_components.wattr.api import WattrError

    entry = ConfigEntry(
        domain="wattr",
        data=tokens,
        title="Wattr",
        source="user",
        unique_id="test-account",
        version=1,
        minor_version=1,
        options={},
        discovery_keys=MappingProxyType({}),
        subentries_data=[],
        state=ConfigEntryState.SETUP_IN_PROGRESS,
    )
    hass.config_entries._entries[entry.entry_id] = entry
    if hasattr(device_registry, "async_setup"):
        device_registry.async_setup(hass)
    await device_registry.async_load(hass)
    await entity_registry.async_load(hass)
    with (
        patch("custom_components.wattr.async_get_clientsession", return_value=Mock()),
        patch(
            "custom_components.wattr.api.WattrApi.snapshot",
            AsyncMock(return_value=snapshot),
        ),
    ):
        async with entry.setup_lock:
            assert await async_setup_entry(hass, entry)
        await hass.async_block_till_done()
        states = hass.states.async_all()
        assert len(states) >= 20, [(s.entity_id, s.state) for s in states]
        soc = next(
            s
            for s in states
            if s.attributes.get("device_class") == "battery" and s.state == "50.5"
        )
        coordinator = entry.runtime_data
        with patch.object(
            coordinator.api,
            "snapshot",
            AsyncMock(side_effect=WattrError("Cannot reach Wattr")),
        ):
            await coordinator.async_refresh()
        await hass.async_block_till_done()
        assert hass.states.get(soc.entity_id).state == "unavailable"
        await coordinator.async_refresh()
        await hass.async_block_till_done()
        assert hass.states.get(soc.entity_id).state == "50.5"
        assert await async_unload_entry(hass, entry)
