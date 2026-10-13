"""Wattr measurements and plans for Home Assistant."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import WattrApi, WattrError
from .const import PLATFORMS
from .coordinator import WattrCoordinator
from .history import register_history_service


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    register_history_service(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    def save_tokens(tokens):
        hass.config_entries.async_update_entry(entry, data=tokens)

    api = WattrApi(async_get_clientsession(hass), dict(entry.data), save_tokens)
    coordinator = WattrCoordinator(hass, entry, api)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    # Removal, not a restart/unload, revokes this connection. Website revocation works offline too.
    api = WattrApi(async_get_clientsession(hass), dict(entry.data))
    try:
        await api.revoke()
    except WattrError:
        pass
