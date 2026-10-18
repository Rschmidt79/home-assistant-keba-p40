"""Exercise real loopback TLS; no device access or production credentials."""

import asyncio
import hashlib
import ssl
import unittest
from unittest.mock import patch

import aiohttp
import pytest
import pytest_socket
import trustme
from aiohttp import web

from custom_components.keba_p40 import api as NEW


@pytest.fixture
def loopback_sockets(socket_enabled):
    """HA's test harness blocks all sockets; permit only this loopback peer."""
    pytest_socket.socket_allow_hosts(["127.0.0.1"], allow_unix_socket=True)
    yield


@pytest.mark.usefixtures("loopback_sockets")
class TestTransportTLS(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.ca = trustme.CA()
        cert = self.ca.issue_cert("127.0.0.1")
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        cert.configure_cert(ctx)
        self.pin = hashlib.sha256(
            ssl.PEM_cert_to_DER_cert(cert.cert_chain_pems[0].bytes().decode())
        ).hexdigest()
        self.logins = set()
        self.seen = []
        self.abort_reused = True
        self.abort_all = False
        self.redirect = False
        self.bad_json = False
        self.transports = []

        async def handler(request):
            # Retain object refs: id reuse must not falsely count a new socket as pooled.
            transport = request.transport
            self.transports.append(transport)
            self.seen.append((request.method, request.path, transport))
            if request.path == "/v2/jwt/login":
                self.logins.add(transport)
                return web.json_response(
                    dict(accessToken="test-access", refreshToken="test-refresh")
                )
            if request.method == "POST":
                if self.abort_all or (self.abort_reused and transport in self.logins):
                    transport.abort()
                    return web.Response()  # Received write, no acknowledgement.
                if self.redirect:
                    return web.Response(
                        status=302, headers={"Location": "https://127.0.0.1:1/never-follow"}
                    )
                if self.bad_json:
                    return web.Response(text="not-json")
                return web.json_response(dict(acceptStatus="ACCEPTED"))
            return web.json_response(dict(ok=True))

        app = web.Application()
        app.router.add_route("*", "/{tail:.*}", handler)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, "127.0.0.1", 0, ssl_context=ctx)
        await self.site.start()
        self.port = self.site._server.sockets[0].getsockname()[1]

    async def asyncTearDown(self):
        await self.runner.cleanup()

    def client(self, mod, session, pin=None):
        return mod.P40Api(
            session,
            "127.0.0.1",
            self.port,
            "test-user",
            "test-password",
            fingerprint=self.pin if pin is None else pin,
        )

    def posts(self):
        return [x for x in self.seen if x[1].endswith("stop-charging")]

    async def test_new_control_never_uses_login_or_prior_control_connection(self):
        async with aiohttp.ClientSession() as shared:
            api = self.client(NEW, shared)
            for _ in range(2):
                await api.control("/v2/wallboxes/123/stop-charging")
                self.assertTrue(api.control_result["accepted"])
            posts = self.posts()
            self.assertEqual(len(posts), 2)
            self.assertIsNot(posts[0][2], posts[1][2])
            self.assertTrue(all(x[2] not in self.logins for x in posts))
            await api.get("/version")
            self.assertFalse(shared.closed)
        await asyncio.sleep(0.01)
        self.assertTrue(all(x[2].is_closing() for x in posts))

    async def test_profile_post_uses_injected_shared_session_without_new_session(self):
        self.abort_reused = False
        async with aiohttp.ClientSession() as shared:
            api = self.client(NEW, shared)
            with patch.object(
                NEW.aiohttp,
                "ClientSession",
                side_effect=AssertionError("Unexpected owned profile session"),
            ):
                await api.control("/v2/profiles/chargepointmaxprofilezero", dict(profileItems=[]))
            profiles = [
                x
                for x in self.seen
                if x[0] == "POST" and x[1] == "/v2/profiles/chargepointmaxprofilezero"
            ]
            self.assertEqual(len(profiles), 1)
            self.assertIn(profiles[0][2], self.logins)
            self.assertTrue(api.control_result["accepted"])
            self.assertFalse(shared.closed)

    async def test_all_three_wallbox_commands_use_fresh_connections(self):
        async with aiohttp.ClientSession() as shared:
            api = self.client(NEW, shared)
            for command in ["start-charging", "stop-charging", "change-availability"]:
                await api.control("/v2/wallboxes/123/" + command)
            controls = [
                x for x in self.seen if x[0] == "POST" and x[1].startswith("/v2/wallboxes/")
            ]
            self.assertEqual(len(controls), 3)
            self.assertTrue(all(x[2] not in self.logins for x in controls))
            self.assertEqual(len({x[2] for x in controls}), 3)

    async def test_server_abort_on_fresh_post_stays_uncertain_one_attempt(self):
        self.abort_all = True
        async with aiohttp.ClientSession() as shared:
            api = self.client(NEW, shared)
            with self.assertRaises(NEW.CannotConnect):
                await api.control("/v2/wallboxes/123/stop-charging")
            self.assertEqual(len(self.posts()), 1)
            self.assertFalse(api.control_result["accepted"])
            self.assertTrue(api.control_result["write_attempted"])
            self.assertEqual(api.last_request["subtype"], "disconnected")
            self.assertEqual(await api.get("/version"), dict(ok=True))
            self.assertEqual(len(self.posts()), 1)

    async def test_mismatched_pin_fails_closed_no_control_received(self):
        async with aiohttp.ClientSession() as shared:
            api = self.client(NEW, shared)
            await api._login()
            api._ssl = aiohttp.Fingerprint(bytes.fromhex("00" * 32))
            with self.assertRaises(NEW.CannotConnect):
                await api._request("POST", "/v2/wallboxes/123/stop-charging", token="test-access")
            self.assertEqual(api.last_request["subtype"], "tls")
            self.assertFalse(self.posts())

    async def test_true_verification_does_not_trust_generated_ca(self):
        async with aiohttp.ClientSession() as shared:
            api = NEW.P40Api(
                shared, "127.0.0.1", self.port, "test-user", "test-password", verify_ssl=True
            )
            with self.assertRaises(NEW.CannotConnect):
                await api._request("POST", "/v2/wallboxes/123/stop-charging", token="test-access")
            self.assertEqual(api.last_request["subtype"], "tls")
            self.assertFalse(self.posts())

    async def test_redirect_not_followed_and_invalid_json_not_accepted(self):
        async with aiohttp.ClientSession() as shared:
            api = self.client(NEW, shared)
            self.redirect = True
            with self.assertRaises(NEW.ApiError):
                await api.control("/v2/wallboxes/123/stop-charging")
            self.assertFalse(api.control_result["accepted"])
            self.assertEqual(len(self.posts()), 1)
            self.assertEqual(api.last_request["status"], 302)
            self.redirect = False
            self.bad_json = True
            with self.assertRaises(NEW.ApiError):
                await api.control("/v2/wallboxes/123/stop-charging")
            self.assertFalse(api.control_result["accepted"])
            self.assertEqual(len(self.posts()), 2)
            self.assertEqual(api.last_request["subtype"], "invalid_json")

    async def test_allowlist_fails_before_any_connection(self):
        async with aiohttp.ClientSession() as shared:
            api = self.client(NEW, shared)
            with self.assertRaises(NEW.ApiError):
                await api._request("POST", "/unapproved")
            self.assertFalse(self.seen)
