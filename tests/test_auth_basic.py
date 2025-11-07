import asyncio
import httpx
import unittest
from mcp import types
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from pydantic import AnyHttpUrl
from reboot.aio.applications import Application
from reboot.aio.tests import Reboot
from reboot.mcp.client import connect, reconnect
from reboot.mcp.server import DurableMCP
from typing import AsyncGenerator


class SimpleTokenVerifier(TokenVerifier):
    """Simple token verifier for testing (server-side)."""

    def __init__(self):
        self.calls: list[str | None] = []

    async def verify_token(self, token: str) -> AccessToken | None:
        # Track all verification attempts.
        self.calls.append(token)
        # Accept any non-empty token for testing.
        if token:
            return AccessToken(
                token=token,
                client_id="test_client",
                scopes=["read"],
            )
        return None


class SimpleAuth(httpx.Auth):
    """Simple `httpx.Auth` for testing (client-side)."""

    def __init__(self, token: str):
        self.token = token

    async def async_auth_flow(
        self, request: httpx.Request
    ) -> AsyncGenerator[httpx.Request, httpx.Response]:
        # Add Bearer token to outgoing requests.
        request.headers["Authorization"] = f"Bearer {self.token}"
        yield request

# Module-level token verifier to track verification calls.
token_verifier = SimpleTokenVerifier()

# `DurableMCP` server which will handle HTTP requests at path "/mcp".
mcp = DurableMCP(
    path="/mcp",
    auth=AuthSettings(
        issuer_url=AnyHttpUrl("https://auth.example.com"),
        resource_server_url=AnyHttpUrl("http://localhost:3001"),
    ),
    token_verifier=token_verifier,
)


@mcp.tool()
async def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b


# Reboot application that runs everything necessary for `DurableMCP`.
application: Application = mcp.application()


class TestAuthBasic(unittest.TestCase):
    """Test that auth parameters can be passed to DurableMCP constructor."""

    def test_auth_with_token_verifier(self) -> None:
        """Test creating DurableMCP with auth and token_verifier."""
        auth_settings = AuthSettings(
            issuer_url=AnyHttpUrl("https://auth.example.com"),
            resource_server_url=AnyHttpUrl("http://localhost:3001"),
            required_scopes=["read"],
        )
        token_verifier = SimpleTokenVerifier()

        # Should not raise any exceptions.
        mcp = DurableMCP(
            path="/mcp",
            auth=auth_settings,
            token_verifier=token_verifier,
        )

        assert mcp._auth == auth_settings
        assert mcp._token_verifier == token_verifier
        assert mcp._auth_server_provider is None

    def test_auth_without_provider_raises_error(self) -> None:
        """Test that auth without provider or verifier raises error."""
        auth_settings = AuthSettings(
            issuer_url=AnyHttpUrl("https://auth.example.com"),
            resource_server_url=AnyHttpUrl("http://localhost:3001"),
        )

        # Should raise `ValueError` when `auth` is provided without
        # `auth_server_provider` or `token_verifier`.
        with self.assertRaises(ValueError) as context:
            DurableMCP(
                path="/mcp",
                auth=auth_settings,
            )

        self.assertIn(
            "Must specify either auth_server_provider or token_verifier",
            str(context.exception),
        )

    def test_provider_without_auth_raises_error(self) -> None:
        """Test that provider without auth raises error."""
        token_verifier = SimpleTokenVerifier()

        # Should raise `ValueError` when `token_verifier` is provided
        # without auth settings.
        with self.assertRaises(ValueError) as context:
            DurableMCP(
                path="/mcp",
                token_verifier=token_verifier,
            )

        self.assertIn(
            "Cannot specify auth_server_provider or token_verifier without "
            "auth settings",
            str(context.exception),
        )

    def test_no_auth_works(self) -> None:
        """Test that DurableMCP without auth still works."""
        # Should not raise any exceptions.
        mcp = DurableMCP(path="/mcp")

        assert mcp._auth is None
        assert mcp._auth_server_provider is None
        assert mcp._token_verifier is None


class TestAuthIntegration(unittest.IsolatedAsyncioTestCase):
    """Integration test that auth actually works end-to-end."""

    async def asyncSetUp(self) -> None:
        self.rbt = Reboot()
        await self.rbt.start()

    async def asyncTearDown(self) -> None:
        await self.rbt.stop()

    async def test_auth_with_reconnect(self) -> None:
        """Test that auth works with durability/reconnect (positive case)."""
        revision = await self.rbt.up(application)

        auth = SimpleAuth("test_token")

        async with connect(
            self.rbt.url() + "/mcp",
            auth=auth,
            terminate_on_close=False,
        ) as (session, session_id, protocol_version):
            result = await session.call_tool("add", arguments={"a": 5, "b": 3})
            self.assertFalse(result.isError)

        print(f"Rebooting application running at {self.rbt.url()}...")

        await self.rbt.down()
        await self.rbt.up(revision=revision)

        print(f"... application now at {self.rbt.url()}")

        async with reconnect(
            self.rbt.url() + "/mcp",
            session_id=session_id,
            protocol_version=protocol_version,
            # MCP bug: need to start using the "next" request ID in
            # the `session` as required by the spec:
            # modelcontextprotocol.io/specification/2025-06-18/basic#requests
            next_request_id=session._request_id,
            auth=auth,
        ) as session:
            result = await session.call_tool("add", arguments={"a": 5, "b": 3})
            self.assertFalse(result.isError)

    async def test_auth_rejects_missing_token(self) -> None:
        """Test that requests without auth are rejected (negative case)."""
        await self.rbt.up(application)

        # Connect without `auth` should fail.
        with self.assertRaises(Exception):
            async with connect(
                self.rbt.url() + "/mcp",
                terminate_on_close=False,
            ) as (session, session_id, protocol_version):
                await session.call_tool("add", arguments={"a": 5, "b": 3})


if __name__ == "__main__":
    unittest.main()
