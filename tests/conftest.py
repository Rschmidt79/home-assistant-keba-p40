"""Tests use captured non-secret responses and fake credentials; no LAN access."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.keba_p40.api import P40Api

FIXTURES = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIXTURES / f"{name}.json").read_text())


@pytest.fixture(autouse=True)
def custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def payloads():
    return {
        name: load(name)
        for name in ("wallbox", "sessions", "modbus", "lmgmt", "device", "versions", "alias")
    }


@pytest.fixture
def mock_api(payloads):
    api = MagicMock(spec=P40Api)
    api.identity = AsyncMock(return_value="12345678")
    api.wallbox = AsyncMock(side_effect=lambda serial: load("wallbox"))
    api.sessions = AsyncMock(side_effect=lambda serial: load("sessions"))

    async def get(path):
        names = {
            "/v2/configs/modbus": "modbus",
            "/v2/configs/lmgmt": "lmgmt",
            "/v2/configs/system/device_info": "device",
            "/v2/configs/system/application_version": "versions",
            "/v2/configs/restapi/restapi_alias": "alias",
        }
        if path == "/v2/profiles/chargepointmaxprofilezero":
            return {
                "name": "CPMP0",
                "socketNumber": 0,
                "profilePurpose": "CHARGE_POINT_MAX_PROFILE",
                "stackLevel": 0,
                "items": [
                    {
                        "startTime": "00:00:00",
                        "stopTime": "24:00:00",
                        "daysOfWeek": [
                            "MONDAY",
                            "TUESDAY",
                            "WEDNESDAY",
                            "THURSDAY",
                            "FRIDAY",
                            "SATURDAY",
                            "SUNDAY",
                        ],
                        "maxCurrentOffered": 16000,
                    }
                ],
            }
        if path == "/v2/wallboxes":
            return {"wallboxes": [load("wallbox")]}
        if path == "/version":
            return "2.5.0"
        if path == "/v2/configs/system/application_version_package":
            return {
                "configs": [{"key": "application_version_package", "value": "1.5.1+cert-meter"}]
            }
        return load(names[path])

    api.get = AsyncMock(side_effect=get)
    return api


@pytest.fixture(autouse=True)
def aiohttp_mock_compatibility():
    """aioresponses 0.7.9 lacks aiohttp 3.14's stream_writer argument.

    Adapt only the mocked response constructor; production aiohttp is untouched.
    """
    from types import SimpleNamespace
    from unittest.mock import patch

    import aiohttp

    class MockResponse(aiohttp.ClientResponse):
        def __init__(self, *args, **kwargs):
            kwargs.setdefault("stream_writer", SimpleNamespace(output_size=0))
            super().__init__(*args, **kwargs)

    with patch("aioresponses.core.ClientResponse", MockResponse):
        yield
