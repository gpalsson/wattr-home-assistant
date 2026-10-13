"""Read-only dated history action with response data, independent of Recorder."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from .api import WattrAuthError, WattrError
from .const import DOMAIN


def history_date(value):
    if not isinstance(value, str) or len(value) != 10:
        raise vol.Invalid("Use YYYY-MM-DD")
    try:
        requested = date.fromisoformat(value)
    except ValueError:
        raise vol.Invalid("Use YYYY-MM-DD") from None
    today = datetime.now(ZoneInfo("Europe/Copenhagen")).date()
    if not today - timedelta(days=30) <= requested <= today:
        raise vol.Invalid("Choose today or one of the previous 30 days")
    return value


def register_history_service(hass):
    async def get_history(call):
        installation = call.data["installation_id"]
        entries = [
            e
            for e in hass.config_entries.async_entries(DOMAIN)
            if e.state is ConfigEntryState.LOADED
        ]
        if entry_id := call.data.get("config_entry_id"):
            entries = [e for e in entries if e.entry_id == entry_id]
        entries = [
            e for e in entries if e.runtime_data.installation(installation) is not None
        ]
        if not entries:
            raise ServiceValidationError(
                "Connect the Wattr account that owns this installation"
            )
        if len(entries) != 1:
            raise ServiceValidationError(
                "Choose the Wattr connection using config_entry_id"
            )
        entry = entries[0]
        try:
            return await entry.runtime_data.api.history(installation, call.data["date"])
        except WattrAuthError:
            entry.async_start_reauth(hass)
            raise HomeAssistantError("Reconnect Wattr to read history") from None
        except WattrError as err:
            raise HomeAssistantError(str(err)) from None

    hass.services.async_register(
        DOMAIN,
        "get_history",
        get_history,
        schema=vol.Schema(
            {
                vol.Required("installation_id"): vol.All(
                    str, vol.Length(min=1, max=80)
                ),
                vol.Required("date"): history_date,
                vol.Optional("config_entry_id"): str,
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )
