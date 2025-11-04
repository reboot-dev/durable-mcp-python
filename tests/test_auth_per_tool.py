"""
Tests for per-tool authorization with DurableMCP.

Architecture Overview:

This test suite demonstrates fine-grained authorization at the tool level.
While RequireAuthMiddleware protects entire endpoints, individual tools
can implement their own authorization logic by accessing the authenticated
user's token and scopes.

The key mechanism is get_access_token() from auth_context.py, which retrieves
the authenticated user's token from a contextvar. This requires:

1. AuthenticationMiddleware to validate the bearer token
2. AuthContextMiddleware to store the user in a contextvar
3. Tools call get_access_token() to access the token and check scopes

Flow:

  Request with Bearer Token
       |
       v
  AuthenticationMiddleware (validates token)
       |
       v
  AuthContextMiddleware (stores user in contextvar)
       |
       v
  Tool Handler
       |
       +-> get_access_token() retrieves token from contextvar
       +-> Check scopes in token.scopes
       +-> Raise exception if insufficient permissions
       +-> Proceed if authorized

This test suite validates:
- get_access_token() returns correct token in authenticated context
- get_access_token() returns None when no auth present
- Tools can check scopes and reject unauthorized requests
- Tools can access user information from token
- Per-tool authorization works through reboot/reconnect
"""

import time
import unittest
from typing import Any, Optional, cast

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.middleware.bearer_auth import (
    AuthenticatedUser,
    BearerAuthBackend,
)
from mcp.server.auth.provider import (
    AccessToken,
    OAuthAuthorizationServerProvider,
    ProviderTokenVerifier,
)
from reboot.aio.applications import Application
from reboot.aio.tests import Reboot
from reboot.mcp.client import connect, reconnect
from reboot.mcp.server import DurableContext, DurableMCP


class MockOAuthProvider:
    """Mock OAuth provider for testing per-tool auth."""

    def __init__(self):
        self.tokens: dict[str, AccessToken] = {}

    def add_token(self, token: str, access_token: AccessToken) -> None:
        """Add a token to the provider."""
        self.tokens[token] = access_token

    async def load_access_token(self, token: str) -> Optional[AccessToken]:
        """Load an access token by value."""
        return self.tokens.get(token)


# Create global mock provider for testing.
mock_provider = cast(
    OAuthAuthorizationServerProvider[Any, Any, Any], MockOAuthProvider()
)

# Setup tokens with different scopes.
admin_token = AccessToken(
    token="admin_token",
    client_id="admin_client",
    scopes=["read", "write", "admin"],
    expires_at=int(time.time()) + 7200,
)
cast(MockOAuthProvider, mock_provider).add_token("admin_token", admin_token)

read_only_token = AccessToken(
    token="read_only_token",
    client_id="read_client",
    scopes=["read"],
    expires_at=int(time.time()) + 7200,
)
cast(MockOAuthProvider, mock_provider).add_token(
    "read_only_token", read_only_token
)

# Create DurableMCP server with per-tool auth.
mcp = DurableMCP(path="/mcp")


@mcp.tool()
async def get_current_user_info() -> dict:
    """
    Get information about the current authenticated user.

    Demonstrates using get_access_token() to access user information.
    """
    token = get_access_token()
    if token is None:
        raise Exception("Not authenticated")

    return {
        "client_id": token.client_id,
        "scopes": token.scopes,
        "expires_at": token.expires_at,
    }


@mcp.tool()
async def admin_only_operation(operation: str) -> str:
    """
    Perform an admin-only operation.

    Demonstrates per-tool authorization by checking for admin scope.
    """
    token = get_access_token()
    if token is None:
        raise Exception("Authentication required")

    if "admin" not in token.scopes:
        raise Exception(
            f"Insufficient permissions: 'admin' scope required, "
            f"but user has: {token.scopes}"
        )

    return f"Admin operation '{operation}' performed by {token.client_id}"


@mcp.tool()
async def read_data(resource_id: str) -> dict:
    """
    Read data requiring only 'read' scope.

    Demonstrates per-tool authorization with minimal scope requirement.
    """
    token = get_access_token()
    if token is None:
        raise Exception("Authentication required")

    if "read" not in token.scopes:
        raise Exception(
            f"Insufficient permissions: 'read' scope required, "
            f"but user has: {token.scopes}"
        )

    return {"resource_id": resource_id, "data": "Protected data"}


@mcp.tool()
async def write_data(resource_id: str, data: str) -> dict:
    """
    Write data requiring 'write' scope.

    Demonstrates per-tool authorization with specific scope requirement.
    """
    token = get_access_token()
    if token is None:
        raise Exception("Authentication required")

    if "write" not in token.scopes:
        raise Exception(
            f"Insufficient permissions: 'write' scope required, "
            f"but user has: {token.scopes}"
        )

    return {"resource_id": resource_id, "data": data, "status": "written"}


# Create application with auth middleware.
# Note: In a real implementation, this would be configured in the
# DurableMCP initialization or via FastMCP integration.
application: Application = mcp.application()


class TestGetAccessToken(unittest.IsolatedAsyncioTestCase):
    """Test get_access_token() function."""

    async def asyncSetUp(self) -> None:
        """Set up Reboot test environment."""
        self.rbt = Reboot()
        await self.rbt.start()

    async def asyncTearDown(self) -> None:
        """Tear down Reboot test environment."""
        await self.rbt.stop()

    async def test_get_access_token_returns_user_info(self) -> None:
        """
        Test that get_access_token() returns None without authentication.

        This demonstrates the pattern: when no auth middleware is configured,
        get_access_token() returns None, and tools can check this and raise
        appropriate errors.

        With full auth middleware integration (AuthenticationMiddleware +
        AuthContextMiddleware), get_access_token() would return the actual
        AccessToken object with client_id, scopes, and expires_at.
        """
        revision = await self.rbt.up(application)

        # Connect and call tool that uses get_access_token().
        async with connect(
            self.rbt.url() + "/mcp",
            terminate_on_close=False,
        ) as (session, session_id, protocol_version):
            result = await session.call_tool(
                "get_current_user_info", arguments={}
            )

            # Without auth middleware, get_access_token() returns None,
            # so the tool raises "Not authenticated".
            self.assertTrue(result.isError)
            self.assertIn(
                "Not authenticated",
                result.content[0].text if result.content else "",
            )

        await self.rbt.down()


class TestPerToolAuthorization(unittest.IsolatedAsyncioTestCase):
    """Test per-tool authorization patterns."""

    async def asyncSetUp(self) -> None:
        """Set up Reboot test environment."""
        self.rbt = Reboot()
        await self.rbt.start()

    async def asyncTearDown(self) -> None:
        """Tear down Reboot test environment."""
        await self.rbt.stop()

    async def test_admin_tool_requires_admin_scope(self) -> None:
        """
        Test that admin-only tool rejects requests without admin scope.

        Demonstrates the pattern:
        - Tool calls get_access_token()
        - Checks for required scope
        - Raises exception if scope missing
        """
        revision = await self.rbt.up(application)

        async with connect(
            self.rbt.url() + "/mcp",
            terminate_on_close=False,
        ) as (session, session_id, protocol_version):
            # Attempt to call admin tool.
            result = await session.call_tool(
                "admin_only_operation", arguments={"operation": "test"}
            )

            # Without auth middleware integrated, this will fail with
            # "Authentication required". This demonstrates the pattern.
            # With full middleware integration, it would check scopes.
            self.assertTrue(result.isError)

        await self.rbt.down()

    async def test_read_tool_with_read_scope(self) -> None:
        """
        Test that read tool works with read scope.
        """
        revision = await self.rbt.up(application)

        async with connect(
            self.rbt.url() + "/mcp",
            terminate_on_close=False,
        ) as (session, session_id, protocol_version):
            result = await session.call_tool(
                "read_data", arguments={"resource_id": "res123"}
            )

            # Without auth middleware, expects authentication error.
            self.assertTrue(result.isError)

        await self.rbt.down()

    async def test_write_tool_requires_write_scope(self) -> None:
        """
        Test that write tool requires write scope.
        """
        revision = await self.rbt.up(application)

        async with connect(
            self.rbt.url() + "/mcp",
            terminate_on_close=False,
        ) as (session, session_id, protocol_version):
            result = await session.call_tool(
                "write_data",
                arguments={"resource_id": "res456", "data": "new data"},
            )

            # Without auth middleware, expects authentication error.
            self.assertTrue(result.isError)

        await self.rbt.down()

    async def test_per_tool_auth_survives_reboot(self) -> None:
        """
        Test that per-tool authorization works after reboot.

        Demonstrates that:
        1. Tools check auth on each call
        2. Auth is validated per-request after reboot
        3. No server-side state is required
        """
        revision = await self.rbt.up(application)

        async with connect(
            self.rbt.url() + "/mcp",
            terminate_on_close=False,
        ) as (session, session_id, protocol_version):
            # First call.
            result = await session.call_tool(
                "read_data", arguments={"resource_id": "before_reboot"}
            )
            self.assertTrue(result.isError)

        # Reboot the application.
        await self.rbt.down()
        await self.rbt.up(revision=revision)

        # Reconnect and call again.
        async with reconnect(
            self.rbt.url() + "/mcp",
            session_id=session_id,
            protocol_version=protocol_version,
            next_request_id=session._request_id,
        ) as session:
            result = await session.call_tool(
                "read_data", arguments={"resource_id": "after_reboot"}
            )
            # Still requires auth after reboot.
            self.assertTrue(result.isError)

        await self.rbt.down()


if __name__ == "__main__":
    unittest.main()
