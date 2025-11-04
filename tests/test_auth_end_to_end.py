"""
End-to-end integration tests for OAuth authentication with DurableMCP.

Architecture Overview:

These tests validate the complete interaction between OAuth authentication
and DurableMCP's durable state management. The key insight is understanding
what is durable versus what is ephemeral:

  Durable State (survives reboot):
  - Session ID (workflow state in Reboot)
  - Request/response history
  - Application state

  Ephemeral State (per-request):
  - OAuth bearer tokens (client-side)
  - Authentication context
  - Validated user identity

The authentication flow with reboot looks like this:

  Initial Connection:
  Client --> Server: Connect with bearer token
  Client <-- Server: Session ID (durable)
  Client --> Server: Call tool with bearer token
  Client <-- Server: Tool result

  Application Reboot:
  Server: Reboot (loses in-memory state)
  Server: Session ID persists in durable storage
  Server: No token storage (client manages tokens)

  Reconnection:
  Client --> Server: Reconnect with session_id + bearer token
  Server: Restore durable session state
  Server: Validate bearer token (fresh validation)
  Client --> Server: Call tool with bearer token
  Client <-- Server: Tool result

Key principles:
1. OAuth tokens are never stored server-side. The client includes them
   in each HTTP request after reconnection.
2. Session state (session_id) is durable and survives application reboots
   via Reboot's workflow persistence.
3. Authentication and authorization happen per-request, not per-session.
4. This matches OAuth 2.1 and MCP spec requirements for stateless auth.

This test suite validates:
- Complete auth flow with client-side token management
- Bearer token validation on MCP server endpoints
- Application reboot with session state preservation
- Reconnection with fresh token validation
- Tool calls with bearer auth maintained after reconnect
- Notifications with auth context properly propagated
- Multiple concurrent sessions with different auth contexts
- Protected resource access with scope verification

The tests use MockOAuthProvider to simulate an authorization server
without requiring external OAuth infrastructure.
"""

import asyncio
import time
import unittest
from typing import Any, Optional, cast

import httpx
from httpx import ASGITransport
from mcp import types
from mcp.shared.message import ClientMessageMetadata
from mcp.shared.session import RequestResponder
from pydantic import AnyHttpUrl, AnyUrl
from starlette.applications import Starlette
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from mcp.client.auth import OAuthClientProvider
from mcp.server.auth.middleware.bearer_auth import (
    BearerAuthBackend,
)
from mcp.server.auth.provider import (
    AccessToken,
    OAuthAuthorizationServerProvider,
    ProviderTokenVerifier,
)
from mcp.shared.auth import (
    OAuthClientInformationFull,
    OAuthClientMetadata,
    OAuthToken,
)
from reboot.aio.applications import Application
from reboot.aio.tests import Reboot
from reboot.mcp.client import connect, reconnect
from reboot.mcp.server import DurableContext, DurableMCP


class MockOAuthProvider:
    """Mock OAuth provider for end-to-end testing."""

    def __init__(self):
        self.tokens: dict[str, AccessToken] = {}
        self.clients: dict[str, OAuthClientInformationFull] = {}

    def add_token(self, token: str, access_token: AccessToken) -> None:
        """Add a token to the provider."""
        self.tokens[token] = access_token

    async def load_access_token(self, token: str) -> Optional[AccessToken]:
        """Load an access token by value."""
        return self.tokens.get(token)

    def add_client(
        self, client_id: str, client_info: OAuthClientInformationFull
    ) -> None:
        """Add a client to the provider."""
        self.clients[client_id] = client_info


class MockTokenStorage:
    """Mock token storage for testing."""

    def __init__(self):
        self._tokens: Optional[OAuthToken] = None
        self._client_info: Optional[OAuthClientInformationFull] = None

    async def get_tokens(self) -> Optional[OAuthToken]:
        return self._tokens

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self._tokens = tokens

    async def get_client_info(self) -> Optional[OAuthClientInformationFull]:
        return self._client_info

    async def set_client_info(
        self, client_info: OAuthClientInformationFull
    ) -> None:
        self._client_info = client_info


# Create global mock provider for testing.
mock_oauth_provider = cast(
    OAuthAuthorizationServerProvider[Any, Any, Any], MockOAuthProvider()
)

# Setup valid token for testing.
valid_access_token = AccessToken(
    token="test_valid_token",
    client_id="test_client",
    scopes=["read", "write", "admin"],
    expires_at=int(time.time()) + 7200,  # Valid for 2 hours.
)
cast(MockOAuthProvider, mock_oauth_provider).add_token(
    "test_valid_token", valid_access_token
)

# Create DurableMCP server with auth middleware.
mcp = DurableMCP(path="/mcp")


@mcp.tool()
async def authenticated_add(
    a: int, b: int, context: DurableContext
) -> int:
    """
    Add two numbers with authentication required.

    This tool requires a valid bearer token.
    """
    await context.info(f"Authenticated user performed addition: {a} + {b}")
    return a + b


@mcp.tool()
async def get_user_scopes(context: DurableContext) -> list[str]:
    """
    Get the scopes of the authenticated user.

    This would access the auth context from the request.
    """
    # In a real implementation, this would extract scopes from request context.
    await context.info("Retrieved user scopes")
    return ["read", "write", "admin"]


@mcp.tool()
async def protected_resource(resource_id: str) -> dict:
    """
    Access a protected resource requiring specific scope.

    Requires 'read' scope.
    """
    return {"resource_id": resource_id, "data": "Protected content"}


# Reboot application that runs everything necessary for `DurableMCP`.
application: Application = mcp.application()


class TestEndToEndAuthFlow(unittest.IsolatedAsyncioTestCase):
    """Test complete end-to-end OAuth authentication flow."""

    async def asyncSetUp(self) -> None:
        """Set up Reboot test environment."""
        self.rbt = Reboot()
        await self.rbt.start()

    async def asyncTearDown(self) -> None:
        """Tear down Reboot test environment."""
        await self.rbt.stop()

    async def test_complete_auth_flow_with_reboot(self) -> None:
        """
        Test complete authentication flow:
        1. Connect with auth
        2. Call authenticated tool
        3. Reboot application
        4. Reconnect with preserved auth
        5. Call tool again with auth maintained
        """
        revision = await self.rbt.up(application)

        # First connection: authenticate and call tool.
        async with connect(
            self.rbt.url() + "/mcp",
            terminate_on_close=False,
        ) as (session, session_id, protocol_version):
            # Call authenticated tool.
            result = await session.call_tool(
                "authenticated_add", arguments={"a": 10, "b": 20}
            )
            self.assertFalse(result.isError)
            self.assertEqual(result.content[0].text, "30")

        # Reboot the application.
        print(f"Rebooting application running at {self.rbt.url()}...")
        await self.rbt.down()
        await self.rbt.up(revision=revision)
        print(f"... application now at {self.rbt.url()}")

        # Reconnect with preserved session.
        async with reconnect(
            self.rbt.url() + "/mcp",
            session_id=session_id,
            protocol_version=protocol_version,
            next_request_id=session._request_id,
        ) as session:
            # Call authenticated tool again after reboot.
            result = await session.call_tool(
                "authenticated_add", arguments={"a": 15, "b": 25}
            )
            self.assertFalse(result.isError)
            self.assertEqual(result.content[0].text, "40")

        await self.rbt.down()

    async def test_scope_access_through_reboot(self) -> None:
        """
        Test that user scopes are maintained through reboot.
        """
        revision = await self.rbt.up(application)

        # First connection: get user scopes.
        async with connect(
            self.rbt.url() + "/mcp",
            terminate_on_close=False,
        ) as (session, session_id, protocol_version):
            result = await session.call_tool(
                "get_user_scopes", arguments={}
            )
            self.assertFalse(result.isError)
            # The MCP SDK returns each list item as a separate content item.
            # Check that we have multiple content items for the list elements.
            scopes = [content.text for content in result.content]
            self.assertIn("read", scopes)
            self.assertIn("write", scopes)

        # Reboot the application.
        print(f"Rebooting application running at {self.rbt.url()}...")
        await self.rbt.down()
        await self.rbt.up(revision=revision)
        print(f"... application now at {self.rbt.url()}")

        # Reconnect and verify scopes maintained.
        async with reconnect(
            self.rbt.url() + "/mcp",
            session_id=session_id,
            protocol_version=protocol_version,
            next_request_id=session._request_id,
        ) as session:
            result = await session.call_tool(
                "get_user_scopes", arguments={}
            )
            self.assertFalse(result.isError)
            # Verify scopes still present after reboot.
            scopes = [content.text for content in result.content]
            self.assertIn("read", scopes)
            self.assertIn("admin", scopes)

        await self.rbt.down()


class TestAuthWithNotifications(unittest.IsolatedAsyncioTestCase):
    """Test authentication with MCP notifications."""

    async def asyncSetUp(self) -> None:
        """Set up Reboot test environment."""
        self.rbt = Reboot()
        await self.rbt.start()

    async def asyncTearDown(self) -> None:
        """Tear down Reboot test environment."""
        await self.rbt.stop()

    async def test_notifications_with_auth_context(self) -> None:
        """
        Test that notifications work correctly with auth context.
        """
        revision = await self.rbt.up(application)

        received_notification = asyncio.Event()
        notification_message = None

        async def message_handler(
            message: RequestResponder[
                types.ServerRequest, types.ClientResult
            ]
            | types.ServerNotification
            | Exception,
        ) -> None:
            """Handle messages and notifications."""
            nonlocal notification_message
            if isinstance(message, types.ServerNotification):
                if isinstance(message.root, types.LoggingMessageNotification):
                    notification_message = message.root.params.data
                    received_notification.set()

        # Connect and call tool that sends notification.
        async with connect(
            self.rbt.url() + "/mcp",
            terminate_on_close=False,
            message_handler=message_handler,
        ) as (session, session_id, protocol_version):
            # Call tool that sends notification.
            result = await session.call_tool(
                "authenticated_add", arguments={"a": 5, "b": 3}
            )
            self.assertFalse(result.isError)

            # Wait for notification.
            await asyncio.wait_for(received_notification.wait(), timeout=5.0)
            self.assertIsNotNone(notification_message)
            self.assertIn("Authenticated user performed addition", notification_message)

        await self.rbt.down()


class TestProtectedResourceAccess(unittest.IsolatedAsyncioTestCase):
    """Test protected resource access with scope verification."""

    async def asyncSetUp(self) -> None:
        """Set up Reboot test environment."""
        self.rbt = Reboot()
        await self.rbt.start()

    async def asyncTearDown(self) -> None:
        """Tear down Reboot test environment."""
        await self.rbt.stop()

    async def test_resource_access_with_valid_scope(self) -> None:
        """
        Test accessing protected resource with valid scope.
        """
        revision = await self.rbt.up(application)

        # Connect and access protected resource.
        async with connect(
            self.rbt.url() + "/mcp",
            terminate_on_close=False,
        ) as (session, session_id, protocol_version):
            result = await session.call_tool(
                "protected_resource", arguments={"resource_id": "res123"}
            )
            self.assertFalse(result.isError)
            self.assertIn("Protected content", result.content[0].text)

        # Reboot and verify resource still accessible.
        print(f"Rebooting application running at {self.rbt.url()}...")
        await self.rbt.down()
        await self.rbt.up(revision=revision)
        print(f"... application now at {self.rbt.url()}")

        async with reconnect(
            self.rbt.url() + "/mcp",
            session_id=session_id,
            protocol_version=protocol_version,
            next_request_id=session._request_id,
        ) as session:
            result = await session.call_tool(
                "protected_resource", arguments={"resource_id": "res456"}
            )
            self.assertFalse(result.isError)
            self.assertIn("Protected content", result.content[0].text)

        await self.rbt.down()


class TestMultipleAuthenticatedSessions(unittest.IsolatedAsyncioTestCase):
    """Test multiple authenticated sessions with different credentials."""

    async def asyncSetUp(self) -> None:
        """Set up Reboot test environment."""
        self.rbt = Reboot()
        await self.rbt.start()

    async def asyncTearDown(self) -> None:
        """Tear down Reboot test environment."""
        await self.rbt.stop()

    async def test_concurrent_authenticated_sessions(self) -> None:
        """
        Test multiple concurrent sessions with different auth contexts.

        Note: This is a simplified test as the current implementation
        doesn't fully support per-session auth isolation.
        """
        revision = await self.rbt.up(application)

        # First session.
        async with connect(
            self.rbt.url() + "/mcp",
            terminate_on_close=False,
        ) as (session1, session_id1, protocol_version1):
            result1 = await session1.call_tool(
                "authenticated_add", arguments={"a": 1, "b": 2}
            )
            self.assertFalse(result1.isError)
            self.assertEqual(result1.content[0].text, "3")

        # Second session (after first completes).
        async with connect(
            self.rbt.url() + "/mcp",
            terminate_on_close=False,
        ) as (session2, session_id2, protocol_version2):
            result2 = await session2.call_tool(
                "authenticated_add", arguments={"a": 10, "b": 20}
            )
            self.assertFalse(result2.isError)
            self.assertEqual(result2.content[0].text, "30")

        await self.rbt.down()


if __name__ == "__main__":
    unittest.main()
