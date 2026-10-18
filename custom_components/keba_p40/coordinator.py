"""One coordinator, atomic snapshots and staggered REST polling."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from datetime import timedelta
from uuid import uuid4

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import ApiError, InvalidAuth, P40Api, WrongDevice
from .const import CONFIG_INTERVAL, DOMAIN, LIVE_INTERVAL, SESSION_INTERVAL, STATIC_INTERVAL
from .diagnostics import safe_profile_shape, safe_request
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
        # Passive timing history of normal fetches only; never adds API calls.
        self.meter_observations = deque(maxlen=2048)
        self.meter_continuity_token = uuid4().hex
        self.meter_continuity_start = None
        self.control_receipts = {}
        self._meter_listeners = set()
        self.last_control = {}
        self.profile_observation = {"outcome": "not_observed"}
        self._control_lock = asyncio.Lock()
        self._feedback_requested = self._feedback_consumed = 0
        self.api = api
        self.serial = entry.unique_id
        self._session_due = self._config_due = self._static_due = 0.0

    def async_add_meter_listener(self, listener):
        """Subscribe only the cumulative meter to passive fetch completion."""
        self._meter_listeners.add(listener)
        return lambda: self._meter_listeners.discard(listener)

    def _publish_meter_observation(self):
        """Runs after DUC commits data/success, including equal-data fetches."""
        history = self.meter_observations
        if history and (
            self.data is None or self.data.live.get("total_energy") != history[-1]["meter"]
        ):
            # Never publish timing evidence against an uncommitted meter value.
            return
        for listener in tuple(self._meter_listeners):
            listener()

    def _invalidate_meter_history(self) -> None:
        """New opaque runtime/continuity binding on every failure or gap."""
        self.meter_observations.clear()
        self.meter_continuity_start = None
        self.meter_continuity_token = uuid4().hex

    async def async_control(self, action: str, current: float | None = None) -> None:
        """Only explicit HA entity actions invoke this path; polling never writes."""
        from .controls import execute_control

        async with self._control_lock:
            self.last_control = dict(
                attempt_id=uuid4().hex,
                attempted_at=time.time(),
                action=action
                if action in {"start", "stop", "current", "enable", "disable"}
                else "unknown",
                outcome="attempted",
                accepted=False,
                write_attempted=False,
                phase="preflight",
            )
            self._publish_meter_observation()
            try:
                await execute_control(self, action, current)
            finally:
                from copy import deepcopy

                try:
                    # Read physical state even after a timeout or rejected command.
                    self._feedback_requested += 1
                    await self.async_refresh()
                    self.last_control["feedback_available"] = self.last_update_success
                    self.last_control["feedback_request"] = safe_request(self.api.last_request)
                    self._publish_meter_observation()
                    if not self.last_update_success:
                        self.last_control["feedback_error"] = "unavailable"
                        if self.last_control.get("outcome") == "accepted":
                            self.last_control["outcome"] = "feedback_failed"
                        self._publish_meter_observation()
                        raise HomeAssistantError(
                            "KEBA feedback unavailable; command outcome is uncertain"
                        )
                finally:
                    # Retain each result under the same control lock, including
                    # failed feedback; a subsequent CURRENT cannot overwrite START.
                    self.control_receipts[action] = deepcopy(self.last_control)
                    self._publish_meter_observation()

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
            self._invalidate_meter_history()
            raise ConfigEntryAuthFailed("P40 authentication rejected") from None
        except ApiError:
            self._invalidate_meter_history()
            # Never interpolate API payloads/credentials into HA logs.
            raise UpdateFailed("P40 REST data unavailable") from None
        except Exception:
            self._invalidate_meter_history()
            raise
        finally:
            # DataUpdateCoordinator commits data and last_update_success before
            # yielding. Equal P40Data suppresses its ordinary listeners, but
            # passive observation bounds still changed. Publish the meter only
            # on the next loop turn, never an uncommitted response/header pair.
            asyncio.get_running_loop().call_soon(self._publish_meter_observation)

    async def _fetch(self) -> P40Data:
        assert self.serial is not None
        # Snapshot before any await: an in-flight poll cannot consume a later request.
        feedback_request = self._feedback_requested
        force_feedback = feedback_request > self._feedback_consumed
        now = time.monotonic()
        previous = self.data or P40Data()
        request_start = time.time()
        live = parse_wallbox(await self.api.wallbox(self.serial))
        request_end = time.time()
        sessions = previous.session
        config = previous.configuration
        device = previous.device
        session_due, config_due, static_due = self._session_due, self._config_due, self._static_due
        transitioned = any(
            live.get(key) != previous.live.get(key) for key in ("session_active", "vehicle_plugged")
        )
        if force_feedback or now >= session_due or transitioned:
            sessions = parse_sessions(await self.api.sessions(self.serial), self.serial)
            session_due = now + SESSION_INTERVAL
        if force_feedback or now >= config_due:
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
            self.profile_observation = {"outcome": "fetch_failed"}
            try:
                profile = await self.api.get(PROFILE_PATH)
            except ApiError as err:
                if str(err) != "P40 data HTTP 404":
                    raise
                self.profile_observation = {"outcome": "not_found"}
            else:
                self.profile_observation = {
                    "outcome": "parser_rejected",
                    "shape": safe_profile_shape(profile),
                }
                try:
                    limit = profile_current(profile)
                    config["charging_current_limit"] = limit if 6 <= limit <= 16 else None
                    self.profile_observation["outcome"] = (
                        "accepted" if 6 <= limit <= 16 else "out_of_range"
                    )
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
        self._feedback_consumed = feedback_request
        meter = live.get("total_energy")
        observation = dict(
            start=request_start, end=request_end, meter=meter, plugged=live.get("vehicle_plugged")
        )
        history = self.meter_observations
        valid_observation = (
            meter is not None
            and observation["plugged"] is True
            and 0 <= request_end - request_start <= 10
        )
        if not valid_observation or (
            history
            and (
                request_start < history[-1]["end"]
                or request_start - history[-1]["end"] > 15
                or meter < history[-1]["meter"]
            )
        ):
            self._invalidate_meter_history()
        if valid_observation:
            if self.meter_continuity_start is None:
                self.meter_continuity_start = request_start
            history.append(observation)
        while history and request_end - history[0]["start"] > 7200:
            history.popleft()
        return P40Data(live=live, session=sessions, configuration=config, device=device)
