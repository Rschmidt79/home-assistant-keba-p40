"""One coordinator, atomic snapshots and staggered REST polling."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import ApiError, InvalidAuth, P40Api, WrongDevice
from .const import CONFIG_INTERVAL, DOMAIN, LIVE_INTERVAL, SESSION_INTERVAL, STATIC_INTERVAL
from .models import P40Data, config_number, config_pairs, parse_sessions, parse_wallbox, text

_LOGGER = logging.getLogger(__name__)


class P40Coordinator(DataUpdateCoordinator[P40Data]):
    """All entities become unavailable when any scheduled API group fails."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, api: P40Api) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=LIVE_INTERVAL),
            always_update=False,
        )
        self._control_lock = asyncio.Lock()
        self.api = api
        self.serial = entry.unique_id
        self._session_due = self._config_due = self._static_due = 0.0

    async def async_control(self, action: str, current: float | None = None) -> None:
        """Only explicit HA entity actions invoke this path; polling never writes."""
        from .controls import execute_control

        async with self._control_lock:
            try:
                await execute_control(self, action, current)
            finally:
                # Read physical state even after a timeout or rejected command.
                self._session_due = self._config_due = 0
                await self.async_refresh()
                if not self.last_update_success:
                    raise HomeAssistantError(
                        "KEBA feedback unavailable; command outcome is uncertain"
                    )

    async def _async_setup(self) -> None:
        try:
            if await self.api.identity() != self.serial:
                raise WrongDevice("P40 serial number changed")
        except InvalidAuth:
            raise ConfigEntryAuthFailed("P40 authentication rejected") from None
        except ApiError:
            raise UpdateFailed("P40 setup data unavailable") from None

    async def _async_update_data(self) -> P40Data:
        try:
            return await self._fetch()
        except InvalidAuth:
            raise ConfigEntryAuthFailed("P40 authentication rejected") from None
        except ApiError:
            # Never interpolate API payloads/credentials into HA logs.
            raise UpdateFailed("P40 REST data unavailable") from None

    async def _fetch(self) -> P40Data:
        assert self.serial is not None
        now = time.monotonic()
        previous = self.data or P40Data()
        live = parse_wallbox(await self.api.wallbox(self.serial))
        sessions = previous.session
        config = previous.configuration
        device = previous.device
        session_due, config_due, static_due = self._session_due, self._config_due, self._static_due
        transitioned = any(
            live.get(key) != previous.live.get(key) for key in ("session_active", "vehicle_plugged")
        )
        if now >= session_due or transitioned:
            sessions = parse_sessions(await self.api.sessions(self.serial), self.serial)
            session_due = now + SESSION_INTERVAL
        if now >= config_due:
            modbus = config_pairs(await self.api.get("/v2/configs/modbus"))
            lmgmt = config_pairs(await self.api.get("/v2/configs/lmgmt"))
            config = {
                "failsafe_current": config_number(modbus, "modbus_failsafe_current", 1000),
                "failsafe_timeout": config_number(modbus, "modbus_failsafe_timeout"),
                "load_management_budget": config_number(lmgmt, "max_available_current", 1000),
            }
            # The optional profile endpoint was not physically audited. A 404 or
            # complex schedule disables current control, not monitoring.
            from .controls import PROFILE_PATH, profile_current

            config["charging_current_limit"] = None
            try:
                profile = await self.api.get(PROFILE_PATH)
            except ApiError as err:
                if str(err) != "P40 data HTTP 404":
                    raise
            else:
                try:
                    limit = profile_current(profile)
                    config["charging_current_limit"] = limit if 6 <= limit <= 16 else None
                except ApiError:
                    pass
            config_due = now + CONFIG_INTERVAL
        if now >= static_due:
            info = config_pairs(await self.api.get("/v2/configs/system/device_info"))
            versions = config_pairs(await self.api.get("/v2/configs/system/application_version"))
            package = config_pairs(
                await self.api.get("/v2/configs/system/application_version_package")
            )
            alias = config_pairs(await self.api.get("/v2/configs/restapi/restapi_alias"))
            api_version = await self.api.get("/version")
            device = {
                "serial": self.serial,
                "model": text(info.get("wallboxmodel")),
                "package_version": text(package.get("application_version_package")),
                "api_version": text(api_version),
                "rest_alias": text(alias.get("restapi_alias")),
                "hardware_revision": text(info.get("revision")),
                "package_base_version": text(versions.get("package")),
            }
            static_due = now + STATIC_INTERVAL
        # Commit deadlines only after every scheduled group succeeds.
        self._session_due, self._config_due, self._static_due = session_due, config_due, static_due
        return P40Data(live=live, session=sessions, configuration=config, device=device)
