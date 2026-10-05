from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import (
    SOURCE_REAUTH,
    SOURCE_RECONFIGURE,
    SOURCE_USER,
    SOURCE_ZEROCONF,
)
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.keba_p40.api import ApiError, CannotConnect, InvalidAuth, WrongDevice
from custom_components.keba_p40.config_flow import normalize

DATA = {
    "host": "p40.local",
    "port": 8443,
    "username": "example-user",
    "password": "example-password",
    "verify_ssl": False,
    "certificate_sha256": "",
}


@pytest.fixture(autouse=True)
def flow_mocks(mock_api):
    with (
        patch("custom_components.keba_p40.config_flow.make_api", return_value=mock_api),
        patch("custom_components.keba_p40.async_setup_entry", return_value=True),
    ):
        yield


async def test_manual_setup_and_duplicate(hass, mock_api):
    result = await hass.config_entries.flow.async_init("keba_p40", context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(result["flow_id"], DATA)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == "12345678"
    assert result["title"] == "P40_12345678"
    assert result["data"]["password"] == "example-password"
    assert "accessToken" not in result["data"]
    await hass.async_block_till_done()
    result = await hass.config_entries.flow.async_init(
        "keba_p40", context={"source": SOURCE_USER}, data=DATA
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    mock_api.close.assert_called()


@pytest.mark.parametrize(
    "exception,error",
    [
        (InvalidAuth(), "invalid_auth"),
        (CannotConnect(), "cannot_connect"),
        (ApiError(), "invalid_response"),
        (WrongDevice(), "wrong_device"),
    ],
)
async def test_errors_not_exposed(hass, mock_api, exception, error):
    mock_api.identity.side_effect = exception
    result = await hass.config_entries.flow.async_init(
        "keba_p40", context={"source": SOURCE_USER}, data=DATA
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}
    assert "example-password" not in repr(result["data_schema"])


def discovery(serial="12345678", host="192.0.2.14"):
    return ZeroconfServiceInfo(
        ip_address=__import__("ipaddress").ip_address(host),
        ip_addresses=[__import__("ipaddress").ip_address(host)],
        hostname="p40.local.",
        type="_rest-P40-keba-wallbox._tcp.local.",
        name="KeContact P40._rest-P40-keba-wallbox._tcp.local.",
        port=8443,
        properties={"serialnumber": serial, "alias": "P40_12345678"},
    )


async def test_discovery_serial_and_wrong_device(hass, mock_api):
    result = await hass.config_entries.flow.async_init(
        "keba_p40", context={"source": SOURCE_ZEROCONF}, data=discovery()
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    mock_api.identity.return_value = "123"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], DATA)
    assert result["errors"] == {"base": "wrong_device"}
    result = await hass.config_entries.flow.async_init(
        "keba_p40", context={"source": SOURCE_ZEROCONF}, data=discovery("bad")
    )
    assert result["reason"] == "invalid_discovery"


async def test_discovery_duplicate_updates_address(hass):
    entry = MockConfigEntry(domain="keba_p40", unique_id="12345678", data=DATA)
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        "keba_p40", context={"source": SOURCE_ZEROCONF}, data=discovery()
    )
    assert result["reason"] == "already_configured"
    assert entry.data["host"] == "192.0.2.14"
    assert entry.unique_id == "12345678"


@pytest.mark.parametrize(
    "source,step", [(SOURCE_REAUTH, "reauth_confirm"), (SOURCE_RECONFIGURE, "reconfigure")]
)
async def test_reauth_and_reconfigure(hass, source, step):
    entry = MockConfigEntry(domain="keba_p40", unique_id="12345678", data=DATA)
    entry.add_to_hass(hass)
    with patch(
        "homeassistant.config_entries.ConfigEntries.async_reload", new=AsyncMock(return_value=True)
    ):
        result = await hass.config_entries.flow.async_init(
            "keba_p40",
            context={"source": source, "entry_id": entry.entry_id},
            data=DATA if source == SOURCE_REAUTH else None,
        )
        assert result["step_id"] == step
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {**DATA, "password": "new-example-password"}
        )
        assert result["type"] is FlowResultType.ABORT
        assert entry.data["password"] == "new-example-password"


async def test_invalid_host_and_missing_alias(hass, mock_api):
    result = await hass.config_entries.flow.async_init(
        "keba_p40", context={"source": SOURCE_USER}, data={**DATA, "host": "https://wrong/"}
    )
    assert result["errors"]["base"] == "invalid_host_or_fingerprint"
    mock_api.get.return_value = {"configs": []}
    mock_api.get.side_effect = None
    result = await hass.config_entries.flow.async_init(
        "keba_p40", context={"source": SOURCE_USER}, data=DATA
    )
    assert result["title"] == "KEBA P40 12345678"
    assert normalize({**DATA, "host": "[::1]"})["host"] == "::1"


async def test_reconfigure_cannot_change_serial(hass, mock_api):
    entry = MockConfigEntry(domain="keba_p40", unique_id="12345678", data=DATA)
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        "keba_p40", context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id}
    )
    mock_api.identity.return_value = "123"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], DATA)
    assert result["errors"] == {"base": "wrong_device"}
    assert entry.unique_id == "12345678"


async def test_invalid_fingerprint_and_discovery_without_port(hass):
    result = await hass.config_entries.flow.async_init(
        "keba_p40", context={"source": SOURCE_USER}, data={**DATA, "certificate_sha256": "bad"}
    )
    assert result["errors"] == {"base": "invalid_host_or_fingerprint"}
    info = discovery()
    info.port = None
    result = await hass.config_entries.flow.async_init(
        "keba_p40", context={"source": SOURCE_ZEROCONF}, data=info
    )
    assert result["reason"] == "invalid_discovery"
