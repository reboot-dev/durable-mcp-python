import asyncio
import httpx
import unittest
from mcp import types
from mcp.server.auth.middleware.auth_context import get_access_token
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

    async def verify_token(self, token: str) -> AccessToken | None:
        # Accept any non-empty token for testing.
        if token:
            return AccessToken(
                token=token,
                client_id="test_client",
                scopes=["read", "write"],
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


# Module-level token verifier.
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
async def get_token_info() -> str:
    """Get information about the current access token."""
    access_token = get_access_token()
    if access_token is None:
        return "No access token"

    return f"token={access_token.token},client_id={access_token.client_id},scopes={','.join(access_token.scopes)}"


@mcp.tool()
async def admin_only_tool() -> str:
    """Tool that requires 'admin' scope."""
    access_token = get_access_token()
    if access_token is None:
        raise PermissionError("Authentication required")

    if "admin" not in access_token.scopes:
        raise PermissionError(
            f"Required scope 'admin' not in {access_token.scopes}"
        )

    return "Admin access granted"


@mcp.tool()
async def specific_client_tool(allowed_client: str) -> str:
    """Tool that requires a specific client_id."""
    access_token = get_access_token()
    if access_token is None:
        raise PermissionError("Authentication required")

    if access_token.client_id != allowed_client:
        raise PermissionError(
            f"Access denied for client '{access_token.client_id}'"
        )

    return f"Access granted for {access_token.client_id}"


# Reboot application that runs everything necessary for `DurableMCP`.
application: Application = mcp.application()


class TestAuthContext(unittest.IsolatedAsyncioTestCase):
    """Test that `get_access_token()` works correctly in tools."""

    async def asyncSetUp(self) -> None:
        self.rbt = Reboot()
        await self.rbt.start()

    async def asyncTearDown(self) -> None:
        await self.rbt.stop()

    async def test_get_access_token_in_tool(self) -> None:
        """Test that `get_access_token()` returns correct token in tool."""
        await self.rbt.up(application)

        auth = SimpleAuth("my_test_token_123")

        async with connect(
            self.rbt.url() + "/mcp",
            auth=auth,
            terminate_on_close=False,
        ) as (session, session_id, protocol_version):
            result = await session.call_tool(
                "get_token_info", arguments={}
            )
            self.assertFalse(result.isError)

            # Extract the content from the result.
            content = result.content[0].text
            self.assertEqual(
                content,
                "token=my_test_token_123,client_id=test_client,scopes=read,write"
            )

    async def test_get_access_token_survives_reboot(self) -> None:
        """Test that `get_access_token()` works after reboot."""
        revision = await self.rbt.up(application)

        auth = SimpleAuth("my_test_token_456")

        async with connect(
            self.rbt.url() + "/mcp",
            auth=auth,
            terminate_on_close=False,
        ) as (session, session_id, protocol_version):
            result = await session.call_tool(
                "get_token_info", arguments={}
            )
            self.assertFalse(result.isError)
            content = result.content[0].text
            self.assertEqual(
                content,
                "token=my_test_token_456,client_id=test_client,scopes=read,write"
            )

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
            result = await session.call_tool(
                "get_token_info", arguments={}
            )
            self.assertFalse(result.isError)
            content = result.content[0].text
            self.assertEqual(
                content,
                "token=my_test_token_456,client_id=test_client,scopes=read,write"
            )

    async def test_scope_based_access_denial(self) -> None:
        """Test that tools can deny access based on missing scopes."""
        await self.rbt.up(application)

        auth = SimpleAuth("test_token")

        async with connect(
            self.rbt.url() + "/mcp",
            auth=auth,
            terminate_on_close=False,
        ) as (session, session_id, protocol_version):
            # Call admin_only_tool without admin scope.
            result = await session.call_tool("admin_only_tool", arguments={})

            # Should return an error.
            self.assertTrue(result.isError)
            # Check the error message contains information about missing scope.
            error_text = result.content[0].text
            self.assertIn("admin", error_text)
            self.assertIn("read", error_text)
            self.assertIn("write", error_text)

    async def test_client_based_access_denial(self) -> None:
        """Test that tools can deny access based on client_id."""
        await self.rbt.up(application)

        auth = SimpleAuth("test_token")

        async with connect(
            self.rbt.url() + "/mcp",
            auth=auth,
            terminate_on_close=False,
        ) as (session, session_id, protocol_version):
            # Call specific_client_tool with wrong client.
            result = await session.call_tool(
                "specific_client_tool",
                arguments={"allowed_client": "different_client"}
            )

            # Should return an error.
            self.assertTrue(result.isError)
            # Check the error message contains the denied client_id.
            error_text = result.content[0].text
            self.assertIn("test_client", error_text)

    async def test_client_based_access_granted(self) -> None:
        """Test that tools grant access for correct client_id."""
        await self.rbt.up(application)

        auth = SimpleAuth("test_token")

        async with connect(
            self.rbt.url() + "/mcp",
            auth=auth,
            terminate_on_close=False,
        ) as (session, session_id, protocol_version):
            # Call specific_client_tool with correct client.
            result = await session.call_tool(
                "specific_client_tool",
                arguments={"allowed_client": "test_client"}
            )

            # Should succeed.
            self.assertFalse(result.isError)
            content = result.content[0].text
            self.assertEqual(content, "Access granted for test_client")


if __name__ == "__main__":
    unittest.main()
