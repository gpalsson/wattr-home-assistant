"""Read cached Wattr measurements without polling equipment."""

import logging
from datetime import timedelta

from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import WattrApi, WattrAuthError, WattrError
from .const import DOMAIN, POLL_SECONDS


class WattrCoordinator(DataUpdateCoordinator[dict]):
    def __init__(self, hass, entry, api: WattrApi):
        super().__init__(
            hass,
            logging.getLogger(__name__),
            name=DOMAIN,
            config_entry=entry,
            update_interval=timedelta(seconds=POLL_SECONDS),
        )
        self.api = api
        self.account_id = entry.unique_id

    async def _async_update_data(self):
        try:
            return await self.api.snapshot()
        except WattrAuthError as err:
            raise ConfigEntryAuthFailed("Reconnect Wattr") from err
        except WattrError as err:
            raise UpdateFailed(str(err)) from err

    def installation(self, site_id):
        return (
            next(
                (s for s in self.data.get("installations", []) if s["id"] == site_id),
                None,
            )
            if self.data
            else None
        )
