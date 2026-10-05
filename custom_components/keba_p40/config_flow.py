"""Manual, mDNS, reauthentication and reconfiguration flows."""

from __future__ import annotations

import ipaddress
import re
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME, CONF_VERIFY_SSL
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig, TextSelectorType
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from . import make_api
from .api import ApiError, CannotConnect, InvalidAuth, WrongDevice
from .const import CONF_FINGERPRINT, DEFAULT_PORT, DOMAIN
from .models import config_pairs, text


def schema(defaults: dict[str, Any]) -> vol.Schema:
    """Never pre-fill or echo a stored password in the form."""
    return vol.Schema(
        {
            vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, "")): str,
            vol.Required(CONF_PORT, default=defaults.get(CONF_PORT, DEFAULT_PORT)): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=65535)
            ),
            vol.Required(CONF_USERNAME, default=defaults.get(CONF_USERNAME, "")): str,
            vol.Required(CONF_PASSWORD): TextSelector(
                TextSelectorConfig(type=TextSelectorType.PASSWORD)
            ),
            vol.Optional(CONF_VERIFY_SSL, default=defaults.get(CONF_VERIFY_SSL, True)): bool,
            vol.Optional(CONF_FINGERPRINT, default=defaults.get(CONF_FINGERPRINT, "")): str,
        }
    )


def normalize(data: dict[str, Any]) -> dict[str, Any]:
    result = dict(data)
    host = result[CONF_HOST].strip().rstrip(".")
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    try:
        ipaddress.ip_address(host)
    except ValueError:
        if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", host):
            raise ValueError("Invalid hostname") from None
    result[CONF_HOST] = host
    fingerprint = result.get(CONF_FINGERPRINT, "").replace(":", "").strip().lower()
    if fingerprint and not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
        raise ValueError("Invalid certificate fingerprint")
    result[CONF_FINGERPRINT] = fingerprint
    return result


class P40ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 2

    def __init__(self) -> None:
        self._defaults: dict[str, Any] = {}
        self._discovered_serial: str | None = None
        self._mode = "user"

    async def _validate(self, data: dict[str, Any]) -> tuple[str, str]:
        api = make_api(self.hass, data)
        try:
            serial = await api.identity()
            if self._discovered_serial and serial != self._discovered_serial:
                raise WrongDevice("Discovery identity mismatch")
            await api.wallbox(serial)
            alias_body = await api.get("/v2/configs/restapi/restapi_alias")
            alias = text(config_pairs(alias_body).get("restapi_alias"))
            return serial, alias or f"KEBA P40 {serial}"
        finally:
            api.close()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors = {}
        if user_input is not None:
            try:
                data = normalize(user_input)
                serial, title = await self._validate(data)
                if self._mode in ("reauth_confirm", "reconfigure"):
                    entry = (
                        self._get_reauth_entry()
                        if self._mode == "reauth_confirm"
                        else self._get_reconfigure_entry()
                    )
                    if serial != entry.unique_id:
                        raise WrongDevice("Entry identity mismatch")
                    return self.async_update_reload_and_abort(entry, data_updates=data)
                await self.async_set_unique_id(serial)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=title, data=data)
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except WrongDevice:
                errors["base"] = "wrong_device"
            except ApiError:
                errors["base"] = "invalid_response"
            except ValueError:
                errors["base"] = "invalid_host_or_fingerprint"
        return self.async_show_form(
            step_id=self._mode, data_schema=schema(self._defaults), errors=errors
        )

    async def async_step_zeroconf(self, discovery_info: ZeroconfServiceInfo) -> FlowResult:
        if discovery_info.port is None:
            return self.async_abort(reason="invalid_discovery")
        properties = discovery_info.properties
        serial = str(properties.get("serialnumber", ""))
        if not re.fullmatch(r"[0-9]+", serial):
            return self.async_abort(reason="invalid_discovery")
        self._discovered_serial = serial
        await self.async_set_unique_id(serial)
        self._abort_if_unique_id_configured(
            updates={CONF_HOST: discovery_info.host, CONF_PORT: discovery_info.port}
        )
        alias = properties.get("alias")
        title = alias if isinstance(alias, str) and alias else f"KEBA P40 {serial}"
        self.context["title_placeholders"] = {"name": title}
        self._defaults = {CONF_HOST: discovery_info.host, CONF_PORT: discovery_info.port}
        return await self.async_step_user()

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> FlowResult:
        self._defaults = {k: v for k, v in entry_data.items() if k != CONF_PASSWORD}
        self._mode = "reauth_confirm"
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None) -> FlowResult:
        return await self.async_step_user(user_input)

    async def async_step_reconfigure(self, user_input=None) -> FlowResult:
        entry = self._get_reconfigure_entry()
        self._defaults = {k: v for k, v in entry.data.items() if k != CONF_PASSWORD}
        self._mode = "reconfigure"
        return await self.async_step_user(user_input)
