"""Allowlisted REST client; controls require explicit entity actions."""

from __future__ import annotations

import asyncio
import re
from typing import Any

import aiohttp
from yarl import URL


class ApiError(Exception):
    """Sanitized protocol/API error, never containing a response body."""


class CannotConnect(ApiError):
    """Transport failure."""


class InvalidAuth(ApiError):
    """Authentication cannot be recovered."""


class WrongDevice(ApiError):
    """Server identity does not match this entry."""


# Keep the allowed API surface explicit; no generic data/control method is exposed.
STATIC_GETS = frozenset(
    {
        "/serialnumber",
        "/v2/wallboxes",
        "/v2/profiles/chargepointmaxprofilezero",
        "/version",
        "/v2/configs/modbus",
        "/v2/configs/lmgmt",
        "/v2/configs/system/device_info",
        "/v2/configs/system/application_version",
        "/v2/configs/system/application_version_package",
        "/v2/configs/restapi/restapi_alias",
        "/v2/sessions",
    }
)
AUTH_POSTS = frozenset({"/v2/jwt/login", "/v2/jwt/refresh"})


class P40Api:
    """Serialize requests and keep credentials/tokens out of repr and logs."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        port: int,
        username: str,
        password: str,
        *,
        verify_ssl: bool = True,
        fingerprint: str = "",
    ) -> None:
        self._session = session
        self._base = URL.build(scheme="https", host=host, port=port)
        self._username = username
        self._password = password
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._lock = asyncio.Lock()
        self._ssl: bool | aiohttp.Fingerprint = verify_ssl
        if fingerprint:
            if not re.fullmatch(r"[0-9a-fA-F]{64}", fingerprint):
                raise ValueError("Invalid SHA-256 fingerprint")
            self._ssl = aiohttp.Fingerprint(bytes.fromhex(fingerprint))

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        payload: dict[str, Any] | None = None,
        token: str | None = None,
    ) -> tuple[int, Any]:
        """Reject non-allowlisted methods/paths before touching the network."""
        allowed_get = path in STATIC_GETS or bool(re.fullmatch(r"/v2/wallboxes/[0-9]+", path))
        allowed_control = method == "POST" and (
            path == "/v2/profiles/chargepointmaxprofilezero"
            or bool(
                re.fullmatch(
                    r"/v2/wallboxes/[0-9]+/(start-charging|stop-charging|change-availability)", path
                )
            )
        )
        if not (
            (method == "GET" and allowed_get)
            or (method == "POST" and path in AUTH_POSTS)
            or allowed_control
        ):
            raise ApiError("Endpoint is outside the API allowlist")
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            async with asyncio.timeout(10):
                async with self._session.request(
                    method,
                    self._base.with_path(path),
                    params=params,
                    json=payload,
                    headers=headers,
                    ssl=self._ssl,
                    allow_redirects=False,
                ) as response:
                    # Do not parse/persist error bodies, which may echo credentials.
                    if response.status not in (200, 202):
                        return response.status, None
                    try:
                        body = await response.json(content_type=None)
                    except ValueError, UnicodeDecodeError:
                        raise ApiError("Invalid JSON response") from None
                    return response.status, body
        except aiohttp.ClientError, TimeoutError:
            raise CannotConnect("P40 connection failed") from None

    async def _login(self) -> None:
        status, body = await self._request(
            "POST",
            "/v2/jwt/login",
            payload={"username": self._username, "password": self._password},
        )
        if status in (401, 403, 422):
            self.clear_tokens()
            raise InvalidAuth("P40 login rejected")
        if status != 200:
            raise ApiError(f"P40 login HTTP {status}")
        if not isinstance(body, dict) or not isinstance(body.get("accessToken"), str):
            raise ApiError("Invalid login response")
        if not body["accessToken"]:
            raise InvalidAuth("Empty access token")
        self._access_token = body["accessToken"]
        self._refresh_token = (
            body.get("refreshToken") if isinstance(body.get("refreshToken"), str) else None
        )

    async def _refresh_or_login(self) -> bool:
        """Return true if a refresh succeeded; otherwise login once."""
        if self._refresh_token:
            status, body = await self._request(
                "POST",
                "/v2/jwt/refresh",
                token=self._refresh_token,
            )
            if status == 200:
                if (
                    not isinstance(body, dict)
                    or not body.get("accessToken")
                    or not isinstance(body["accessToken"], str)
                ):
                    raise ApiError("Invalid refresh response")
                self._access_token = body["accessToken"]
                if isinstance(body.get("refreshToken"), str) and body["refreshToken"]:
                    self._refresh_token = body["refreshToken"]
                return True
            if status not in (401, 403, 422):
                raise ApiError(f"P40 refresh HTTP {status}")
        self.clear_tokens()
        await self._login()
        return False

    async def get(self, path: str, *, params: dict[str, str] | None = None) -> Any:
        """Recover expired tokens on 401/403 without clock/expiry assumptions."""
        async with self._lock:
            if self._access_token is None:
                await self._login()
            status, body = await self._request("GET", path, params=params, token=self._access_token)
            if status in (401, 403):
                refreshed = await self._refresh_or_login()
                status, body = await self._request(
                    "GET", path, params=params, token=self._access_token
                )
                # Refreshed tokens are non-fresh. If a GET still rejects one,
                # use the documented login instead of undocumented auth endpoints.
                if refreshed and status in (401, 403):
                    self.clear_tokens()
                    await self._login()
                    status, body = await self._request(
                        "GET", path, params=params, token=self._access_token
                    )
            if status in (401, 403):
                self.clear_tokens()
                raise InvalidAuth("P40 authorization rejected")
            if status not in (200, 202):
                raise ApiError(f"P40 data HTTP {status}")
            return body

    async def identity(self) -> str:
        """Read the authoritative serial number after validating login."""
        value = await self.get("/serialnumber")
        if isinstance(value, bool) or not isinstance(value, (str, int)):
            raise ApiError("Invalid serial number response")
        serial = str(value)
        if not re.fullmatch(r"[0-9]+", serial):
            raise ApiError("Invalid serial number response")
        return serial

    async def wallbox(self, serial: str) -> dict[str, Any]:
        value = await self.get(f"/v2/wallboxes/{serial}")
        if not isinstance(value, dict):
            raise ApiError("Invalid wallbox response")
        if value.get("serialNumber") != serial:
            raise WrongDevice("Unexpected wallbox serial")
        return value

    async def sessions(self, serial: str) -> Any:
        return await self.get(
            "/v2/sessions",
            params={
                "limit": "3",
                "orderField": "SESSION_START_DATE",
                "orderDir": "DESC",
                "filters": f"SOCKET_SERIAL_NUMBER={serial}",
            },
        )

    async def control(self, path: str, payload: dict[str, Any] | None = None) -> Any:
        """Validate HTTP and documented body. Never retry an uncertain write.

        Refresh JWT proactively via login for fresh-token-only control endpoints.
        The same lock serializes authentication with reads. A failed/timeout write
        is not replayed: the caller must inspect subsequent physical data.
        """
        async with self._lock:
            await self._login()
            status, body = await self._request(
                "POST", path, payload=payload, token=self._access_token
            )
            if status in (401, 403):
                self.clear_tokens()
                raise InvalidAuth("P40 control authorization rejected")
            if status not in (200, 202):
                raise ApiError(f"P40 control HTTP {status}")
            if not isinstance(body, dict):
                raise ApiError("Invalid control response")
            if "acceptStatus" in body:
                if body["acceptStatus"] != "ACCEPTED":
                    raise ApiError("P40 control not accepted")
            elif path == "/v2/profiles/chargepointmaxprofilezero" and status == 200:
                # OpenAPI specifies a v2Profile, NOT acceptStatus, for HTTP 200.
                # Validate that exact alternative schema; never accept an empty body.
                from .controls import profile_current

                profile_current(body)
            elif status == 200 and re.fullmatch(
                r"/v2/wallboxes/[0-9]+/(start-charging|stop-charging|change-availability)", path
            ):
                # These endpoints document a v2Wallbox success body.
                serial = path.split("/")[3]
                if (
                    body.get("serialNumber") != serial
                    or type(body.get("number")) is not int
                    or body["number"] < 1
                    or body.get("state")
                    not in {
                        "CHARGING",
                        "IDLE",
                        "READY_FOR_CHARGING",
                        "RECOVER_FROM_ERROR",
                        "INSTALLER_MODE",
                        "SUSPENDED",
                        "TOKEN_PROGRAMMING_MODE",
                        "UNRECOVERABLE_ERROR",
                        "UNAVAILABLE",
                        "OFFLINE",
                        "DEGRADED",
                    }
                ):
                    raise ApiError("Invalid control wallbox response")
            else:
                raise ApiError("Missing control acceptance")
            return body

    def clear_tokens(self) -> None:
        """Discard memory-only auth state; do not logout/change server state."""
        self._access_token = self._refresh_token = None

    def close(self) -> None:
        """Release credentials on unload; shared HA HTTP session stays open."""
        self.clear_tokens()
        self._username = self._password = ""
