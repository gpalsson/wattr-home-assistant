"""Bounded HTTPS client; secrets never occur in URLs, logs or exceptions."""

import asyncio
import json
import time
from collections.abc import Callable

from aiohttp import ClientError, ClientSession, ClientTimeout

from .const import API_URL


class WattrError(Exception):
    """Connection or protocol error, without response content."""


class WattrAuthError(WattrError):
    """The connection needs new browser consent."""


class DeviceFlowError(WattrError):
    """A bounded OAuth device-flow error."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class WattrApi:
    """One client per entry, with serialized refresh-token rotation."""

    def __init__(
        self,
        session: ClientSession,
        tokens: dict | None = None,
        save_tokens: Callable[[dict], None] | None = None,
        *,
        base_url: str = API_URL,
    ):
        self.session = session
        self.base_url = base_url
        self.tokens = dict(tokens or {})
        self.save_tokens = save_tokens
        self._refresh_lock = asyncio.Lock()

    async def request(self, method: str, path: str, *, payload=None, access=None):
        headers = {"Authorization": f"Bearer {access}"} if access else {}
        try:
            async with self.session.request(
                method,
                self.base_url + path,
                json=payload,
                headers=headers,
                timeout=ClientTimeout(total=20),
                allow_redirects=False,
            ) as response:
                if (
                    response.content_length
                    and response.content_length > 8 * 1024 * 1024
                ):
                    raise WattrError("Response exceeds limit")
                raw = bytearray()
                async for chunk in response.content.iter_chunked(64 * 1024):
                    raw.extend(chunk)
                    if len(raw) > 8 * 1024 * 1024:
                        raise WattrError("Response exceeds limit")
                try:
                    data = json.loads(raw)
                except (ValueError, UnicodeDecodeError):
                    raise WattrError("Invalid API response") from None
                if not isinstance(data, dict):
                    raise WattrError("Invalid API response")
                if response.status == 401:
                    raise WattrAuthError("Authorization expired")
                if response.status == 400 and data.get("error") in {
                    "authorization_pending",
                    "slow_down",
                    "access_denied",
                    "expired_token",
                    "invalid_grant",
                }:
                    code = data["error"]
                    if code == "invalid_grant":
                        raise WattrAuthError("Connection revoked")
                    raise DeviceFlowError(code)
                if response.status != 200:
                    raise WattrError(f"API HTTP {response.status}")
                return data
        except (ClientError, TimeoutError):
            raise WattrError("Cannot reach Wattr") from None

    async def start_device_flow(self):
        data = await self.request(
            "POST", "/auth/device", payload={"client_name": "Home Assistant"}
        )
        for key in ("device_code", "user_code", "verification_uri_complete"):
            if not isinstance(data.get(key), str) or not data[key]:
                raise WattrError("Invalid device flow")
        # Consent links must remain on the Wattr origin; no arbitrary HTML/URLs from errors.
        if not data["verification_uri_complete"].startswith(
            "https://wattr.dk/portal/home-assistant?"
        ):
            raise WattrError("Invalid consent link")
        data["interval"] = max(5, min(60, int(data.get("interval", 5))))
        data["expires_in"] = max(1, min(600, int(data.get("expires_in", 600))))
        return data

    @staticmethod
    def parse_tokens(data: dict) -> dict:
        if any(
            not isinstance(data.get(k), str) or not data[k]
            for k in ("access_token", "refresh_token", "account_id")
        ):
            raise WattrError("Invalid token response")
        if (
            data.get("token_type", "").lower() != "bearer"
            or data.get("scope") != "read"
        ):
            raise WattrError("Unexpected authorization scope")
        expiry = data.get("expires_in")
        if (
            not isinstance(expiry, (float, int))
            or isinstance(expiry, bool)
            or not 0 < expiry <= 3600
        ):
            raise WattrError("Invalid token expiry")
        return {k: data[k] for k in ("access_token", "refresh_token", "account_id")} | {
            "expires_at": time.time() + expiry
        }

    async def device_token(self, code: str):
        return self.parse_tokens(
            await self.request(
                "POST",
                "/auth/token",
                payload={
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    "device_code": code,
                },
            )
        )

    async def refresh(self, rejected_access: str | None = None):
        async with self._refresh_lock:
            if rejected_access is not None:
                if self.tokens.get("access_token") != rejected_access:
                    return
            elif self.tokens.get("expires_at", 0) > time.time() + 60:
                return
            refreshed = self.parse_tokens(
                await self.request(
                    "POST",
                    "/auth/token",
                    payload={
                        "grant_type": "refresh_token",
                        "refresh_token": self.tokens["refresh_token"],
                    },
                )
            )
            if refreshed["account_id"] != self.tokens["account_id"]:
                raise WattrAuthError("Account changed")
            # HA updates the config entry synchronously before another caller can use this pair.
            if self.save_tokens:
                self.save_tokens(refreshed)
            self.tokens = refreshed

    async def snapshot(self):
        await self.refresh()
        access = self.tokens["access_token"]
        try:
            data = await self.request("GET", "/snapshot", access=access)
        except WattrAuthError:
            await self.refresh(rejected_access=access)
            data = await self.request(
                "GET", "/snapshot", access=self.tokens["access_token"]
            )
        if (
            data.get("api_version") != 1
            or data.get("account_id") != self.tokens["account_id"]
        ):
            raise WattrAuthError("Unexpected snapshot account or version")
        sites = data.get("installations")
        if (
            not isinstance(sites, list)
            or len(sites) > 100
            or any(
                not isinstance(s, dict) or not isinstance(s.get("id"), str)
                for s in sites
            )
        ):
            raise WattrError("Invalid installations")
        return data

    async def revoke(self):
        if token := self.tokens.get("refresh_token"):
            await self.request("POST", "/auth/revoke", payload={"token": token})
