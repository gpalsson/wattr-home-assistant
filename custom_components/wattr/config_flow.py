"""Browser-approved, read-only connection; HA never asks for a Wattr password."""

import asyncio
import time

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import DeviceFlowError, WattrApi, WattrAuthError, WattrError
from .const import DOMAIN


class WattrConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self):
        self._device = None
        self._task = None
        self._deadline = 0
        self._reauth_entry = None
        self._api = None

    async def async_step_user(self, user_input=None):
        self._api = WattrApi(async_get_clientsession(self.hass))
        try:
            self._device = await self._api.start_device_flow()
        except WattrError:
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema({}),
                errors={"base": "cannot_connect"},
            )
        self._deadline = time.monotonic() + self._device["expires_in"]
        return await self.async_step_approve()

    async def async_step_reauth(self, entry_data):
        self._reauth_entry = self._get_reauth_entry()
        return await self.async_step_user()

    async def async_step_approve(self, user_input=None):
        if user_input is not None:
            self._task = self.hass.async_create_task(
                self._poll(), "Wattr device approval"
            )
            return await self.async_step_wait()
        return self.async_show_form(
            step_id="approve",
            data_schema=vol.Schema({}),
            description_placeholders={
                "url": self._device["verification_uri_complete"],
                "code": self._device["user_code"],
            },
        )

    async def _poll(self):
        interval = self._device["interval"]
        while time.monotonic() < self._deadline:
            try:
                return await self._api.device_token(self._device["device_code"])
            except DeviceFlowError as err:
                if err.code == "slow_down":
                    interval += 5
                elif err.code != "authorization_pending":
                    raise
            await asyncio.sleep(interval)
        raise DeviceFlowError("expired_token")

    async def async_step_wait(self, user_input=None):
        if not self._task.done():
            return self.async_show_progress(
                step_id="wait", progress_action="waiting", progress_task=self._task
            )
        return self.async_show_progress_done(next_step_id="finish")

    async def async_step_finish(self, user_input=None):
        try:
            tokens = self._task.result()
        except DeviceFlowError as err:
            return self.async_abort(reason=err.code)
        except WattrAuthError:
            return self.async_abort(reason="access_denied")
        except WattrError:
            return self.async_abort(reason="cannot_connect")
        if self._reauth_entry:
            if tokens["account_id"] != self._reauth_entry.unique_id:
                await self._revoke_unused(tokens)
                return self.async_abort(reason="wrong_account")
            return self.async_update_reload_and_abort(
                self._reauth_entry, data_updates=tokens
            )
        await self.async_set_unique_id(tokens["account_id"])
        if self._async_current_entries():
            if any(
                e.unique_id == tokens["account_id"]
                for e in self._async_current_entries()
            ):
                await self._revoke_unused(tokens)
                return self.async_abort(reason="already_configured")
        return self.async_create_entry(title="Wattr", data=tokens)

    async def _revoke_unused(self, tokens):
        try:
            await WattrApi(async_get_clientsession(self.hass), tokens).revoke()
        except WattrError:
            pass
