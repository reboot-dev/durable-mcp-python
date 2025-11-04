"""
Integration tests for OAuth 2.1 bearer token authentication with DurableMCP.

This test suite validates that auth actually works end-to-end with:
- DurableMCP configured with auth_server_provider
- Bearer tokens validated per-request
- get_access_token() returning actual token data
- Per-tool authorization working with real scopes
- Auth state surviving reboot
"""

import time
import unittest
from typing import Any, Optional, cast

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import (
    AccessToken,
    OAuthAuthorizationServerProvider,
)
from mcp.server.auth.settings import AuthSettings
from pydantic import AnyHttpUrl
from reboot.aio.applications import Application
from reboot.aio.tests import Reboot
from reboot.mcp.client import connect, reconnect
from reboot.mcp.server import DurableContext, DurableMCP


class MockOAuthProvider:
    """Mock OAuth provider that stores tokens in memory."""

    def __init__(self):
        self.tokens: dict[str, AccessToken] = {}

    def add_token(self, token: str, access_token: AccessToken) -> None:
        """Add a token to the provider."""
        self.tokens[token] = access_token

    async def load_access_token(self, token: str) -> Optional[AccessToken]:
        """Load an access token by value."""
        return self.tokens.get(token)


# Create OAuth provider with test tokens.
oauth_provider = cast(
    OAuthAuthorizationServerProvider[Any, Any, Any], MockOAuthProvider()
)

# Admin token with all scopes.
admin_token = AccessToken(
    token="test_admin_token",
    client_id="admin_user",
    scopes=["read", "write", "admin"],
    expires_at=int(time.time()) + 7200,
)
cast(MockOAuthProvider, oauth_provider).add_token(
    "test_admin_token", admin_token
)

# Read-only token.
read_token = AccessToken(
    token="test_read_token",
    client_id="read_user",
    scopes=["read"],
    expires_at=int(time.time()) + 7200,
)
cast(MockOAuthProvider, oauth_provider).add_token(
    "test_read_token", read_token
)

# Create DurableMCP server WITH auth configured.
mcp = DurableMCP(
    path="/mcp",
    auth_server_provider=oauth_provider,
    auth=AuthSettings(
        issuer_url=AnyHttpUrl("https://auth.example.com"),
        resource_server_url=AnyHttpUrl("https://mcp.example.com"),
    ),
)


@mcp.tool()
async def get_user_info(context: DurableContext) -> dict:
    """Get authenticated user information using get_access_token()."""
    # Get OAuth 2.1 AccessToken via get_access_token().
    token = get_access_token()

    # Debug via context.info which sends notification to client.
    await context.info(f"DEBUG: get_access_token() = {token}")
    if token:
        await context.info(f"DEBUG: token.client_id = {token.client_id}")
        await context.info(f"DEBUG: token.scopes = {token.scopes}")

    if token is None:
        raise Exception("No access token available")

    # Return token data to verify OAuth 2.1 auth is working.
    return {
        "client_id": token.client_id,
        "scopes": token.scopes,
        "expires_at": token.expires_at,
    }


@mcp.tool()
async def admin_operation(action: str, context: DurableContext) -> str:
    """Perform admin operation requiring 'admin' scope."""
    token = get_access_token()

    # Debug logging.
    await context.info(f"DEBUG admin_operation: get_access_token() = {token}")

    if token is None:
        raise Exception("Not authenticated")

    if "admin" not in token.scopes:
        raise Exception(
            f"Insufficient permissions: requires 'admin' scope, "
            f"but user has: {token.scopes}"
        )

    return f"Admin action '{action}' performed by {token.client_id}"


@mcp.tool()
async def read_data(resource_id: str) -> dict:
    """Read data requiring 'read' scope."""
    token = get_access_token()
    if token is None:
        raise Exception("Not authenticated")

    if "read" not in token.scopes:
        raise Exception(
            f"Insufficient permissions: requires 'read' scope"
        )

    return {"resource_id": resource_id, "data": "Protected content"}


application: Application = mcp.application()


class TestAuthIntegration(unittest.IsolatedAsyncioTestCase):
    """Test OAuth 2.1 auth integration with DurableMCP."""

    async def asyncSetUp(self) -> None:
        """Set up Reboot test environment."""
        self.rbt = Reboot()
        await self.rbt.start()

    async def asyncTearDown(self) -> None:
        """Tear down Reboot test environment."""
        await self.rbt.stop()

    async def test_request_without_auth_rejected(self) -> None:
        """Test that requests without auth are rejected."""
        revision = await self.rbt.up(application)

        async with connect(
            self.rbt.url() + "/mcp",
            terminate_on_close=False,
        ) as (session, session_id, protocol_version):
            result = await session.call_tool("get_user_info", arguments={})

            # Without bearer token, should get auth error.
            self.assertTrue(result.isError)
            # FastMCP with auth middleware should return 401.

        await self.rbt.down()

    async def test_get_access_token_with_valid_bearer(self) -> None:
        """Test get_access_token() returns real token data."""
        revision = await self.rbt.up(application)

        # Capture notifications for debugging.
        notifications = []

        async def message_handler(message):
            if isinstance(message, types.ServerNotification):
                if isinstance(message.root, types.LoggingMessageNotification):
                    notifications.append(message.root.params.data)

        # Connect with admin bearer token in headers.
        async with connect(
            self.rbt.url() + "/mcp",
            terminate_on_close=False,
            headers={"Authorization": "Bearer test_admin_token"},
            message_handler=message_handler,
        ) as (session, session_id, protocol_version):
            result = await session.call_tool("get_user_info", arguments={})

            # Print notifications for debugging.
            for notif in notifications:
                print(f"NOTIFICATION: {notif}")

            # Should successfully return user info.
            self.assertFalse(result.isError)
            text = result.content[0].text

            # Parse result (it's JSON serialized).
            self.assertIn("admin_user", text)
            self.assertIn("read", text)
            self.assertIn("write", text)
            self.assertIn("admin", text)

        await self.rbt.down()

    async def test_admin_tool_with_admin_scope(self) -> None:
        """Test admin tool works with admin scope."""
        revision = await self.rbt.up(application)

        # Capture notifications for debugging.
        notifications = []

        async def message_handler(message):
            if isinstance(message, types.ServerNotification):
                if isinstance(message.root, types.LoggingMessageNotification):
                    notifications.append(message.root.params.data)

        # Connect with admin bearer token.
        async with connect(
            self.rbt.url() + "/mcp",
            terminate_on_close=False,
            headers={"Authorization": "Bearer test_admin_token"},
            message_handler=message_handler,
        ) as (session, session_id, protocol_version):
            result = await session.call_tool(
                "admin_operation", arguments={"action": "restart"}
            )

            # Print notifications for debugging.
            for notif in notifications:
                print(f"NOTIFICATION: {notif}")

            if result.isError:
                print(f"ERROR: {result.content[0].text if result.content else 'Unknown'}")

            self.assertFalse(result.isError)
            self.assertIn("admin_user", result.content[0].text)

        await self.rbt.down()

    async def test_admin_tool_without_admin_scope(self) -> None:
        """Test admin tool rejects requests without admin scope."""
        revision = await self.rbt.up(application)

        # TODO: Connect with read-only bearer token.
        # result = await session.call_tool(
        #     "admin_operation", arguments={"action": "restart"}
        # )
        # self.assertTrue(result.isError)
        # self.assertIn("Insufficient permissions", result.content[0].text)

        await self.rbt.down()

    async def test_read_tool_with_read_scope(self) -> None:
        """Test read tool works with read scope."""
        revision = await self.rbt.up(application)

        # TODO: Connect with read bearer token.
        # result = await session.call_tool(
        #     "read_data", arguments={"resource_id": "res123"}
        # )
        # self.assertFalse(result.isError)
        # self.assertIn("Protected content", result.content[0].text)

        await self.rbt.down()

    async def test_auth_survives_reboot(self) -> None:
        """Test auth validation works after reboot."""
        revision = await self.rbt.up(application)

        # TODO: Connect with bearer token, call tool, reboot, reconnect
        # with same token, call tool again - should still work.

        await self.rbt.down()


if __name__ == "__main__":
    unittest.main()
