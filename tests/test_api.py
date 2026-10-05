import asyncio
from unittest.mock import AsyncMock

import aiohttp
import pytest
from aioresponses import aioresponses

from custom_components.keba_p40.api import ApiError, CannotConnect, InvalidAuth, P40Api, WrongDevice

BASE = "https://p40.local:8443"


@pytest.fixture
async def client():
    async with aiohttp.ClientSession() as session:
        yield P40Api(session, "p40.local", 8443, "example-user", "example-password")


async def test_real_login_schema_and_header(client):
    with aioresponses() as mock:
        mock.post(
            BASE + "/v2/jwt/login",
            payload={"accessToken": "fake-access", "refreshToken": "fake-refresh"},
        )
        mock.get(BASE + "/serialnumber", payload=12345678)
        assert await client.identity() == "12345678"
        calls = list(mock.requests.items())
        post = next(v[0] for (method, _), v in calls if method == "POST")
        get = next(v[0] for (method, _), v in calls if method == "GET")
        assert post.kwargs["json"] == {"username": "example-user", "password": "example-password"}
        assert get.kwargs["headers"]["Authorization"] == "Bearer fake-access"
        assert get.kwargs["allow_redirects"] is False
    assert "example-password" not in repr(client)
    client.close()
    assert client._access_token is None and client._refresh_token is None
    assert client._password == ""


async def test_expired_access_refresh_endpoint_and_rotation(client):
    with aioresponses() as mock:
        mock.post(BASE + "/v2/jwt/login", payload={"accessToken": "old", "refreshToken": "refresh"})
        mock.get(BASE + "/version", status=401)
        mock.post(
            BASE + "/v2/jwt/refresh", payload={"accessToken": "new", "refreshToken": "rotated"}
        )
        mock.get(BASE + "/version", payload="2.5.0")
        assert await client.get("/version") == "2.5.0"
        assert client._refresh_token == "rotated"
        refresh_call = next(
            v[0]
            for (method, url), v in mock.requests.items()
            if method == "POST" and str(url).endswith("/refresh")
        )
        assert refresh_call.kwargs["headers"]["Authorization"] == "Bearer refresh"
        assert refresh_call.kwargs["json"] is None


async def test_expired_refresh_relogin(client):
    with aioresponses() as mock:
        mock.post(BASE + "/v2/jwt/login", payload={"accessToken": "old", "refreshToken": "expired"})
        mock.get(BASE + "/version", status=401)
        mock.post(BASE + "/v2/jwt/refresh", status=401)
        mock.post(
            BASE + "/v2/jwt/login", payload={"accessToken": "new", "refreshToken": "new-refresh"}
        )
        mock.get(BASE + "/version", payload="2.5.0")
        assert await client.get("/version") == "2.5.0"


async def test_nonfresh_refresh_falls_back_to_login(client):
    client._access_token, client._refresh_token = "old", "refresh"
    with aioresponses() as mock:
        mock.get(BASE + "/version", status=401)
        mock.post(BASE + "/v2/jwt/refresh", payload={"accessToken": "nonfresh"})
        mock.get(BASE + "/version", status=403)
        mock.post(BASE + "/v2/jwt/login", payload={"accessToken": "fresh"})
        mock.get(BASE + "/version", payload="2.5.0")
        assert await client.get("/version") == "2.5.0"


async def test_invalid_credentials_no_response_body_leaks(client, caplog):
    with aioresponses() as mock:
        mock.post(
            BASE + "/v2/jwt/login", status=401, payload={"echo": "example-password secret-jwt"}
        )
        with pytest.raises(InvalidAuth) as err:
            await client.get("/version")
    assert "example-password" not in str(err.value) + caplog.text
    assert "secret-jwt" not in str(err.value) + caplog.text


@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", "/v2/wallboxes/12345678/unlock"),
        ("PUT", "/v2/configs/modbus"),
        ("PATCH", "/v2/wallboxes/12345678"),
        ("DELETE", "/v2/rfids"),
        ("GET", "/v2/mvas/synch/12345678/LOG"),
        ("GET", "/v2/configs/diagnostics/export"),
    ],
)
async def test_forbidden_requests_rejected_before_network(client, method, path):
    with pytest.raises(ApiError, match="allowlist"):
        await client._request(method, path)


async def test_http_failure_and_redirect_are_not_zero(client):
    client._access_token = "fake"
    with aioresponses() as mock:
        mock.get(BASE + "/version", status=500, payload={"password": "example-password"})
        with pytest.raises(ApiError, match="HTTP 500"):
            await client.get("/version")
        mock.get(BASE + "/version", status=302, headers={"Location": BASE + "/unsafe"})
        with pytest.raises(ApiError, match="HTTP 302"):
            await client.get("/version")
        mock.get(BASE + "/version", exception=asyncio.TimeoutError())
        with pytest.raises(CannotConnect):
            await client.get("/version")


async def test_wrong_serial_and_concurrent_single_login(client, payloads):
    with aioresponses() as mock:
        mock.post(BASE + "/v2/jwt/login", payload={"accessToken": "fake"})
        mock.get(BASE + "/version", payload="2.5.0", repeat=2)
        assert await asyncio.gather(client.get("/version"), client.get("/version")) == [
            "2.5.0",
            "2.5.0",
        ]
        post_calls = [v for (method, _), v in mock.requests.items() if method == "POST"]
        assert len(post_calls) == 1
        mock.get(BASE + "/v2/wallboxes/123", payload=payloads["wallbox"])
        with pytest.raises(WrongDevice):
            await client.wallbox("123")


async def test_fingerprint_and_unrecoverable_auth(client):
    with pytest.raises(ValueError):
        P40Api(client._session, "p40.local", 8443, "x", "y", fingerprint="bad")
    pinned = P40Api(client._session, "p40.local", 8443, "x", "y", fingerprint="a" * 64)
    assert isinstance(pinned._ssl, aiohttp.Fingerprint)
    client._access_token = "bad"
    client._request = AsyncMock(
        side_effect=[(401, None), (200, {"accessToken": "also-bad"}), (401, None)]
    )
    with pytest.raises(InvalidAuth):
        await client.get("/version")
    assert client._access_token is None


@pytest.mark.parametrize("payload", [{}, {"accessToken": 123}, {"accessToken": ""}, []])
async def test_malformed_login_response_is_never_accepted(client, payload):
    with aioresponses() as mock:
        mock.post(BASE + "/v2/jwt/login", payload=payload)
        with pytest.raises(ApiError):
            await client.identity()


async def test_invalid_json_and_rate_limit_are_api_errors(client):
    client._access_token = "fake"
    with aioresponses() as mock:
        mock.get(BASE + "/version", body="not-json")
        with pytest.raises(ApiError, match="JSON"):
            await client.get("/version")
        mock.get(BASE + "/version", status=429)
        with pytest.raises(ApiError, match="HTTP 429"):
            await client.get("/version")


async def test_sessions_filter_and_identity_types(client, payloads):
    from urllib.parse import urlencode

    client._access_token = "fake"
    params = {
        "limit": "3",
        "orderField": "SESSION_START_DATE",
        "orderDir": "DESC",
        "filters": "SOCKET_SERIAL_NUMBER=12345678",
    }
    with aioresponses() as mock:
        mock.get(BASE + "/v2/sessions?" + urlencode(params), payload=payloads["sessions"])
        assert (await client.sessions("12345678"))["sessions"][0]["energyConsumed"] == 15123400
        mock.get(BASE + "/serialnumber", payload=True)
        with pytest.raises(ApiError, match="serial"):
            await client.identity()
        mock.get(BASE + "/serialnumber", payload="bad")
        with pytest.raises(ApiError, match="serial"):
            await client.identity()
        mock.get(BASE + "/v2/wallboxes/12345678", payload=[])
        with pytest.raises(ApiError, match="wallbox"):
            await client.wallbox("12345678")
