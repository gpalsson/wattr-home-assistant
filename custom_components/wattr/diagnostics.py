"""Diagnostics contain no credentials, household data, plans, names or IDs."""


async def async_get_config_entry_diagnostics(hass, entry):
    coordinator = entry.runtime_data
    return {
        "integration_version": "0.2.0",
        "api_version": (coordinator.data or {}).get("api_version"),
        "last_update_success": coordinator.last_update_success,
        "installation_count": len((coordinator.data or {}).get("installations", [])),
    }
